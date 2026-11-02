"""SQLite persistence for rhtracker — the ``SqliteStore`` (task 2).

Ports the three-layer schema and helpers from the flat ``db.py``, retargeted to
the ``model`` dataclasses instead of ad-hoc dicts:

  bronze  -> raw_events        (full API payloads, audit trail)
  silver  -> transactions      (normalized, deduped by hash + reference_id)
             positions_daily   (shares held per ticker, reconstructed from flows)
             price_cache       (historical closing prices)
  gold    -> monthly_tracking  (the 17-column month-end report rows)
  sync_state                   (last sync bookkeeping)

Every statement is parameterized — no SQL string interpolation — which is the
key robustness fix versus the old docker-psql approach. ``:memory:`` is
supported for tests. This is a library-layer module: it imports only ``model``
(plus stdlib).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from rhtracker.model import MonthlySnapshot, PortfolioSnapshot, Position, Price, Transaction

DEFAULT_PATH = Path(__file__).resolve().parent.parent.parent / "robinhood.db"

# The 16 metric columns of monthly_tracking after month_end (17 total). Kept as
# a single list so the write path and schema stay in lockstep with
# MonthlySnapshot.
_SNAPSHOT_COLUMNS = (
    "month_end",
    "gross_value",
    "total_increase",
    "asset_growth",
    "dividends",
    "interest_paid",
    "cash_after_interest",
    "monthly_expenses",
    "margin_used",
    "margin_paid_down",
    "margin_debt",
    "w2_contribution",
    "total_w2_contribution",
    "net_portfolio_value",
    "total_interest_paid",
    "value_flags",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,            -- JSON string
    window_start TEXT,
    window_end   TEXT,
    pulled_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_hash  TEXT PRIMARY KEY,
    transaction_date  TEXT NOT NULL,       -- ISO date YYYY-MM-DD
    transaction_type  TEXT NOT NULL,
    asset             TEXT,
    amount            REAL NOT NULL,       -- signed: + in, - out
    quantity          REAL,
    price             REAL,
    status            TEXT,
    reference_id      TEXT,
    raw_id            INTEGER,
    FOREIGN KEY (raw_id) REFERENCES raw_events(id)
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_txn_ref  ON transactions(reference_id);

CREATE TABLE IF NOT EXISTS positions_daily (
    as_of_date  TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    shares      REAL NOT NULL,
    PRIMARY KEY (as_of_date, ticker)
);

CREATE TABLE IF NOT EXISTS price_cache (
    ticker      TEXT NOT NULL,
    price_date  TEXT NOT NULL,
    close       REAL NOT NULL,
    PRIMARY KEY (ticker, price_date)
);

CREATE TABLE IF NOT EXISTS monthly_tracking (
    month_end             TEXT PRIMARY KEY,   -- ISO date, last day of month
    gross_value           REAL,
    total_increase        REAL,
    asset_growth          REAL,
    dividends             REAL,
    interest_paid         REAL,
    cash_after_interest   REAL,
    monthly_expenses      REAL,
    margin_used           REAL,
    margin_paid_down      REAL,
    margin_debt           REAL,
    w2_contribution       REAL,
    total_w2_contribution REAL,
    net_portfolio_value   REAL,
    total_interest_paid   REAL,
    value_flags           TEXT
);


CREATE TABLE IF NOT EXISTS portfolio_snapshot (
    captured_at TEXT PRIMARY KEY,
    gross_value REAL, equity REAL, cash REAL, margin_borrowed REAL,
    outstanding_interest REAL, buying_power REAL, excess_maintenance REAL,
    withdrawable REAL, equity_previous_close REAL,
    market_value_previous_close REAL,
    portfolio_cash REAL, overnight_buying_power REAL, overnight_ratio REAL,
    ext_gross_value REAL, ext_equity REAL
);

CREATE TABLE IF NOT EXISTS sync_state (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    last_sync_at           TEXT,
    last_transaction_date  TEXT,
    status                 TEXT,
    details                TEXT
);
"""


def _iso(value):
    """Render a date (or already-ISO string / None) as an ISO date string."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class SqliteStore:
    """Owns the SQLite connection and all SQL for the tracker.

    Pass ``":memory:"`` for an ephemeral in-memory database (tests). The
    connection stays open for the lifetime of the store so an in-memory
    database persists across calls.
    """

    def __init__(self, db_path=DEFAULT_PATH):
        self.db_path = db_path
        self._conn = sqlite3.connect(
            db_path if db_path == ":memory:" else str(db_path)
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON;")

    # -- lifecycle ---------------------------------------------------------

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- writes ------------------------------------------------------------

    def save_raw_event(
        self, event_type, payload_json, window_start=None, window_end=None
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO raw_events "
            "(event_type, payload, window_start, window_end, pulled_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                event_type,
                payload_json,
                window_start,
                window_end,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def save_transactions(self, txns: list[Transaction], raw_id=None) -> int:
        """Insert normalized transactions, deduping on identity.

        A transaction is rejected when its ``reference_id`` already exists, then
        the ``transaction_hash`` primary key rejects any remaining hash
        collisions. Returns the number of rows actually inserted.
        """
        inserted = 0
        for txn in txns:
            ref = txn.reference_id or ""
            if ref:
                existing = self._conn.execute(
                    "SELECT 1 FROM transactions WHERE reference_id = ? LIMIT 1",
                    (ref,),
                ).fetchone()
                if existing:
                    continue
            try:
                self._conn.execute(
                    "INSERT INTO transactions "
                    "(transaction_hash, transaction_date, transaction_type, asset, "
                    " amount, quantity, price, status, reference_id, raw_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        txn.hash,
                        _iso(txn.transaction_date),
                        txn.transaction_type,
                        txn.asset,
                        txn.amount if txn.amount is not None else 0.0,
                        txn.quantity,
                        txn.price,
                        txn.status,
                        ref,
                        raw_id,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                # transaction_hash already present — a duplicate.
                continue
        self._conn.commit()
        return inserted

    def save_prices(self, prices: list[Price]) -> None:
        for p in prices:
            self._conn.execute(
                "INSERT INTO price_cache (ticker, price_date, close) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(ticker, price_date) DO UPDATE SET close = excluded.close",
                (p.ticker, _iso(p.price_date), float(p.close)),
            )
        self._conn.commit()

    def save_positions(self, positions: list[Position]) -> None:
        for pos in positions:
            self._conn.execute(
                "INSERT INTO positions_daily (as_of_date, ticker, shares) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(as_of_date, ticker) DO UPDATE SET shares = excluded.shares",
                (_iso(pos.as_of_date), pos.ticker, float(pos.shares)),
            )
        self._conn.commit()

    def save_snapshots(self, snapshots: list[MonthlySnapshot]) -> None:
        placeholders = ", ".join("?" for _ in _SNAPSHOT_COLUMNS)
        updates = ", ".join(
            f"{c} = excluded.{c}" for c in _SNAPSHOT_COLUMNS if c != "month_end"
        )
        for snap in snapshots:
            values = []
            for col in _SNAPSHOT_COLUMNS:
                value = getattr(snap, col)
                values.append(_iso(value) if col == "month_end" else value)
            self._conn.execute(
                f"INSERT INTO monthly_tracking ({', '.join(_SNAPSHOT_COLUMNS)}) "
                f"VALUES ({placeholders}) "
                f"ON CONFLICT(month_end) DO UPDATE SET {updates}",
                tuple(values),
            )
        self._conn.commit()

    _SNAP_COLS = ("captured_at", "gross_value", "equity", "cash",
                  "margin_borrowed", "outstanding_interest", "buying_power",
                  "excess_maintenance", "withdrawable", "equity_previous_close",
                  "market_value_previous_close", "portfolio_cash",
                  "overnight_buying_power", "overnight_ratio",
                  "ext_gross_value", "ext_equity")

    def save_portfolio_snapshot(self, snap: PortfolioSnapshot) -> None:
        ph = ", ".join("?" for _ in self._SNAP_COLS)
        self._conn.execute(
            f"INSERT OR REPLACE INTO portfolio_snapshot ({', '.join(self._SNAP_COLS)}) "
            f"VALUES ({ph})",
            tuple(getattr(snap, c) for c in self._SNAP_COLS),
        )
        self._conn.commit()

    def latest_portfolio_snapshot(self) -> PortfolioSnapshot | None:
        row = self._conn.execute(
            f"SELECT {', '.join(self._SNAP_COLS)} FROM portfolio_snapshot "
            "ORDER BY captured_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return PortfolioSnapshot(**{c: row[c] for c in self._SNAP_COLS})

    def set_sync_state(
        self, status, last_transaction_date=None, details=None
    ) -> None:
        self._conn.execute(
            "INSERT INTO sync_state "
            "(id, last_sync_at, last_transaction_date, status, details) "
            "VALUES (1, datetime('now'), ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_sync_at = datetime('now'), "
            "last_transaction_date = excluded.last_transaction_date, "
            "status = excluded.status, details = excluded.details",
            (_iso(last_transaction_date), status, json.dumps(details or {})),
        )
        self._conn.commit()

    # -- reads -------------------------------------------------------------

    def all_transactions(self) -> list[Transaction]:
        rows = self._conn.execute(
            "SELECT transaction_hash, transaction_date, transaction_type, asset, "
            "       amount, quantity, price, status, reference_id "
            "FROM transactions ORDER BY transaction_date, transaction_hash"
        ).fetchall()
        return [
            Transaction(
                hash=r["transaction_hash"],
                transaction_date=date.fromisoformat(r["transaction_date"]),
                transaction_type=r["transaction_type"],
                asset=r["asset"],
                amount=r["amount"],
                quantity=r["quantity"],
                price=r["price"],
                status=r["status"],
                reference_id=r["reference_id"],
            )
            for r in rows
        ]

    def held_tickers(self) -> list[str]:
        """Distinct assets that have appeared in a buy/sell trade."""
        rows = self._conn.execute(
            "SELECT DISTINCT asset FROM transactions "
            "WHERE transaction_type IN ('buy', 'sell') AND asset IS NOT NULL "
            "ORDER BY asset"
        ).fetchall()
        return [r["asset"] for r in rows]

    def month_ends(self) -> list[date]:
        rows = self._conn.execute(
            "SELECT month_end FROM monthly_tracking ORDER BY month_end"
        ).fetchall()
        return [date.fromisoformat(r["month_end"]) for r in rows]

    def price_on_or_before(self, ticker, as_of) -> float | None:
        row = self._conn.execute(
            "SELECT close FROM price_cache "
            "WHERE ticker = ? AND price_date <= ? "
            "ORDER BY price_date DESC LIMIT 1",
            (ticker, _iso(as_of)),
        ).fetchone()
        return row["close"] if row else None

    def all_snapshots(self) -> list[MonthlySnapshot]:
        rows = self._conn.execute(
            f"SELECT {', '.join(_SNAPSHOT_COLUMNS)} "
            "FROM monthly_tracking ORDER BY month_end"
        ).fetchall()
        snapshots = []
        for r in rows:
            fields = {col: r[col] for col in _SNAPSHOT_COLUMNS}
            fields["month_end"] = date.fromisoformat(fields["month_end"])
            snapshots.append(MonthlySnapshot(**fields))
        return snapshots

    def transaction_summary(self) -> list[sqlite3.Row]:
        """Per-type counts and signed amount totals, for reporting."""
        return self._conn.execute(
            "SELECT transaction_type, COUNT(*) AS n, "
            "       SUM(amount) AS total_amount "
            "FROM transactions "
            "GROUP BY transaction_type "
            "ORDER BY transaction_type"
        ).fetchall()
