"""Orchestration recipes — the services layer (task 6).

Plain functions that wire the library modules together: no ``argparse``, no
``print``, no process exit codes. They *return* values so both the CLI and the
cron script can decide what to do with the result. Both the ``source`` and the
``store`` are injectable; the defaults are :class:`RobinhoodSource` +
:class:`SqliteStore`, while tests inject a ``FakeSource`` and an in-memory store.

Services layer rule (enforced by tests): this module imports from the library
only — ``model``, ``sources``, ``storage``, ``reconstruct``, ``reporting`` — and
never from ``cli`` or ``scripts``.

The reconstruct domain module is imported under the alias ``reconstruct_module``
so it does not clash with the ``reconstruct`` service function defined here.
"""

from __future__ import annotations

from datetime import date

from rhtracker import reconstruct as reconstruct_module
from rhtracker import categories
from rhtracker import export as export_mod
from rhtracker import reporting
from rhtracker.model import MonthlySnapshot
from rhtracker.reconstruct import BACKFILL_START
from rhtracker.sources.base import Source
from rhtracker.sources.robinhood import RobinhoodSource
from rhtracker.storage import SqliteStore


def pull(
    since: date = BACKFILL_START,
    source: Source | None = None,
    store: SqliteStore | None = None,
) -> list[MonthlySnapshot]:
    """Run the full pull chain and return the reconstructed month-end snapshots.

    Steps: authenticate, fetch + store transactions, derive the month-end
    dates, fetch + store the closing prices for held tickers, build and persist
    the snapshots, and record the sync state. Every network interaction goes
    through the :class:`~rhtracker.sources.base.Source` protocol — only
    ``authenticate``, ``fetch_transactions``, and ``fetch_prices`` are called —
    so any conforming source substitutes cleanly.
    """
    source = source or RobinhoodSource()
    store = store or SqliteStore()
    store.init_schema()

    source.authenticate()

    transactions = source.fetch_transactions(since)
    store.save_transactions(transactions)

    months = reconstruct_module.month_ends()
    prices = source.fetch_prices(store.held_tickers(), months)
    store.save_prices(prices)

    snapshots = reconstruct_module.build_snapshots(store)
    # Capture the broker's REAL point-in-time account state (optional).
    snap_fn = getattr(source, 'fetch_portfolio_snapshot', None)
    if callable(snap_fn):
        try:
            ps = snap_fn()
            if ps is not None:
                store.save_portfolio_snapshot(ps)
        except Exception:
            pass

    last_txn_date = max((t.transaction_date for t in transactions), default=None)
    store.set_sync_state(
        "complete",
        last_transaction_date=last_txn_date,
        details={
            "transactions": len(transactions),
            "prices": len(prices),
            "snapshots": len(snapshots),
        },
    )
    return snapshots


def reconstruct(store: SqliteStore | None = None) -> list[MonthlySnapshot]:
    """Rebuild snapshots from already-stored transactions and prices.

    No network: runs only the deterministic tail of the pipeline against the
    data already in the store.
    """
    store = store or SqliteStore()
    store.init_schema()
    return reconstruct_module.build_snapshots(store)


def report(store: SqliteStore | None = None) -> str:
    """Render the stored transaction summary and month-end snapshots as text."""
    store = store or SqliteStore()
    store.init_schema()
    return (
        reporting.render_transaction_summary(store.transaction_summary())
        + "\n"
        + reporting.render_monthly(store.all_snapshots())
    )


def category_report(store: SqliteStore | None = None) -> str:
    """Render category breakdown tables (dividends, expenses, fees, trades)."""
    store = store or SqliteStore()
    store.init_schema()
    txns = store.all_transactions()
    sections = [
        reporting.render_dividends(categories.dividends_by_ticker(txns)),
        reporting.render_expenses(categories.expenses_by_payee(txns)),
        reporting.render_fees(categories.fees_by_type(txns)),
        reporting.render_stock_trades(categories.stock_trades_by_ticker(txns)),
        reporting.render_option_trades(categories.option_trades_by_underlying(txns)),
    ]
    return "\n\n".join(sections)


def export_workbook(fmt: str = "xlsx", destination: str | None = None,
                    store: SqliteStore | None = None) -> str:
    """Build the workbook from stored data and write it via the chosen backend.

    fmt selects the writer: 'xlsx' (openpyxl) now, 'gsheets' later. When
    destination is None for xlsx, a timestamped file is created under output/.
    Returns the concrete location written.
    """
    store = store or SqliteStore()
    store.init_schema()
    wb = export_mod.build_workbook(store)

    if fmt == "xlsx":
        from rhtracker.writers.xlsx import XlsxWriter
        writer = XlsxWriter()
        if destination is None:
            from datetime import datetime
            from pathlib import Path
            outdir = Path(__file__).resolve().parents[2] / "output"
            outdir.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            destination = str(outdir / f"portfolio_{stamp}.xlsx")
    elif fmt == "gsheets":
        from rhtracker.writers.sheets import SheetsWriter
        writer = SheetsWriter()
        if destination is None:
            raise ValueError("gsheets export requires a destination spreadsheet id")
    else:
        raise ValueError(f"unknown export format: {fmt!r}")

    return writer.write(wb, destination)
