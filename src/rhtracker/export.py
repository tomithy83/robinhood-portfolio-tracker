"""Build a writer-agnostic workbook from the stored data (library layer).

An ExportWorkbook is a plain list of Sheet(name, headers, rows) — pure data with
no dependency on openpyxl or the Google Sheets API. Concrete writers (xlsx now,
Sheets later) consume this shape, so the data definition lives in one place and
both backends stay identical. Imports only model + sibling library modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from rhtracker import categories
from rhtracker.model import MonthlySnapshot, Transaction


@dataclass(frozen=True)
class Sheet:
    name: str
    headers: list[str]
    rows: list[list]  # each row a list of cell values (str/number/None/date)


@dataclass(frozen=True)
class ExportWorkbook:
    sheets: list[Sheet] = field(default_factory=list)


# Column order for the Tracking sheet == MonthlySnapshot fields, human headers.
_TRACKING = [
    ("month_end", "Month"),
    ("gross_value", "Gross Value"),
    ("total_increase", "Total Increase"),
    ("asset_growth", "Asset Growth"),
    ("dividends", "Dividends"),
    ("interest_paid", "Interest Paid"),
    ("cash_after_interest", "Cash After Interest"),
    ("monthly_expenses", "Monthly Expenses"),
    ("margin_used", "Margin Used"),
    ("margin_paid_down", "Margin Paid Down"),
    ("margin_debt", "Margin Debt"),
    ("w2_contribution", "W2 Contribution"),
    ("total_w2_contribution", "Total W2 Contribution"),
    ("net_portfolio_value", "Net Portfolio Value"),
    ("total_interest_paid", "Total Interest Paid"),
    ("value_flags", "Flags"),
]

_DEFINITIONS = [
    ["Month", "Last calendar day of the month (the snapshot date)."],
    ["Gross Value", "Market value of stock/fund holdings (shares x back-adjusted close). Excludes options and crypto."],
    ["Total Increase", "Change in Gross Value vs prior month, including your deposits."],
    ["Asset Growth", "Change in Gross Value minus net deposits (market movement only)."],
    ["Dividends", "Dividends received during the month."],
    ["Interest Paid", "Margin interest charged during the month."],
    ["Cash After Interest", "Dividends minus interest paid."],
    ["Monthly Expenses", "Account outflows: card purchases, ATM, bill/loan payments, fees."],
    ["Margin Used", "Margin drawn during the month. RECONSTRUCTED from cash flows (approximate)."],
    ["Margin Paid Down", "Margin reduction during the month. RECONSTRUCTED (approximate)."],
    ["Margin Debt", "Running margin balance at month-end. RECONSTRUCTED from cash flows, NOT read from Robinhood; close but not exact."],
    ["W2 Contribution", "Net cash deposited during the month (deposits minus withdrawals)."],
    ["Total W2 Contribution", "Running cumulative of W2 Contribution."],
    ["Net Portfolio Value", "Gross Value minus Margin Debt."],
    ["Total Interest Paid", "Running cumulative of Interest Paid."],
    ["Flags", "Notes, e.g. a held ticker with no cached historical price (excluded from Gross Value, not zeroed)."],
    ["", ""],
    ["NOTE: Splits", "Reverse splits are applied from a manual table in settings.json; the API does not expose them reliably. Validated against real current share counts."],
    ["NOTE: Options", "Options are summarized on the Options sheet by premium; they do NOT contribute to Gross Value."],
    ["NOTE: Values", "All cells are computed values (no formulas), so this workbook is identical whether exported to Excel or Google Sheets."],
]


def _snap_row(s: MonthlySnapshot) -> list:
    out = []
    for attr, _ in _TRACKING:
        v = getattr(s, attr)
        out.append(v.isoformat() if isinstance(v, date) else v)
    return out


def _txn_row(t: Transaction) -> list:
    d = t.transaction_date
    return [
        d.isoformat() if isinstance(d, date) else d,
        t.transaction_type, t.asset, t.amount, t.quantity, t.price,
        t.status, t.reference_id,
    ]


def build_workbook(store) -> ExportWorkbook:
    """Assemble all sheets from the store."""
    snapshots = store.all_snapshots()
    txns = store.all_transactions()

    sheets: list[Sheet] = []

    # 0. Overall Summary - REAL broker figures as of the last pull.
    snap = store.latest_portfolio_snapshot()
    if snap is not None:
        gross = snap.gross_value                 # core / regular-hours (headline)
        equity = snap.equity
        buffer = snap.excess_maintenance
        borrowed = abs(snap.portfolio_cash) if snap.portfolio_cash is not None else None
        # Full buying power = overnight BP / overnight ratio (matches RH UI).
        obp = snap.overnight_buying_power
        ratio = snap.overnight_ratio
        full_bp = (obp / ratio) if (obp is not None and ratio) else None
        # Total Margin is derived (no API primitive): borrowed + full buying power.
        total_margin = (borrowed + full_bp) if (borrowed is not None and full_bp is not None) else None
        # excess_maintenance = equity - maintenance_requirement.
        maint_req = (equity - buffer) if (equity is not None and buffer is not None) else None
        blended = (maint_req / gross) if (maint_req is not None and gross) else None
        buf_full = (buffer / gross) if (buffer is not None and gross) else None
        buf_net = (buffer / equity) if (buffer is not None and equity) else None
        invested = _total_cost_basis(store)
        summary_rows = [
            ["Captured At", snap.captured_at],
            ["Portfolio Gross Value", gross],
            ["Portfolio Net Value (Equity)", equity],
            ["Margin Borrowed", borrowed],
            ["Total Margin", total_margin],
            ["Buying Power", full_bp],
            ["Withdrawable", snap.withdrawable],
            ["Cash (margin-incl.)", snap.cash],
            ["Margin Maint Requirement", maint_req],
            ["Blended Maint Rate", blended],
            ["Margin Buffer (excess maint)", buffer],
            ["% Margin Buffer (full folio)", buf_full],
            ["% Margin Buffer (net folio)", buf_net],
            ["Margin Interest Outstanding", snap.outstanding_interest],
            ["Total Invested (cost basis)", invested],
            ["Equity Previous Close", snap.equity_previous_close],
            ["Gross Value Previous Close", snap.market_value_previous_close],
            ["Gross Value (extended hrs)", snap.ext_gross_value],
            ["Equity (extended hrs)", snap.ext_equity],
        ]
        sheets.append(Sheet("Overall Summary", ["Metric", "Value"], summary_rows))


    # 1. Tracking
    sheets.append(Sheet(
        "Tracking",
        [h for _, h in _TRACKING],
        [_snap_row(s) for s in snapshots],
    ))

    # 2. Transactions (full ledger)
    sheets.append(Sheet(
        "Transactions",
        ["Date", "Type", "Asset", "Amount", "Quantity", "Price", "Status", "Reference ID"],
        [_txn_row(t) for t in txns],
    ))

    # 3. Dividends by ticker
    sheets.append(Sheet(
        "Dividends",
        ["Ticker", "Count", "Total"],
        [[r.label, r.count, r.total] for r in categories.dividends_by_ticker(txns)],
    ))

    # Dividend Payments (every individual dividend row).
    div_rows = [[(_d(t.transaction_date)), t.asset, t.amount, t.status, t.reference_id]
                for t in txns if t.transaction_type == "dividend"]
    div_rows.sort(key=lambda r: r[0])
    sheets.append(Sheet(
        "Dividend Payments",
        ["Date", "Ticker", "Amount", "Status", "Reference ID"],
        div_rows,
    ))

    # Expense Summary (expenses + fees folded together) and Expense Details.
    exp_rows = [[r.label, r.count, r.total] for r in categories.expenses_by_payee(txns)]
    exp_rows += [[r.label, r.count, r.total] for r in categories.fees_by_type(txns)]
    exp_rows.sort(key=lambda row: row[2], reverse=True)
    sheets.append(Sheet("Expense Summary", ["Payee / Fee", "Count", "Total"], exp_rows))

    detail_types = categories.EXPENSE_TYPES | categories.FEE_TYPES
    detail = [_txn_row(t) for t in txns if t.transaction_type in detail_types]
    sheets.append(Sheet(
        "Expense Details",
        ["Date", "Type", "Payee/Asset", "Amount", "Quantity", "Price", "Status", "Reference ID"],
        detail,
    ))

    # 6. Stock trades
    sheets.append(Sheet(
        "Stock Trades",
        ["Ticker", "Buy Count", "Buy Amount", "Sell Count", "Sell Amount"],
        [[r.ticker, r.buy_count, r.buy_total, r.sell_count, r.sell_total]
         for r in categories.stock_trades_by_ticker(txns)],
    ))

    # 7. Options
    sheets.append(Sheet(
        "Options",
        ["Underlying", "Bought", "Buy Premium", "Sold", "Sell Premium"],
        [[r.ticker, r.buy_count, r.buy_total, r.sell_count, r.sell_total]
         for r in categories.option_trades_by_underlying(txns)],
    ))

    # 8. Positions (holdings at the latest snapshot month-end)
    pos_rows = []
    if snapshots:
        latest = snapshots[-1].month_end
        for tk in store.held_tickers():
            shares = _shares_at(store, tk, latest)
            if shares and round(shares, 6) > 0:
                close = store.price_on_or_before(tk, latest)
                pos_rows.append([
                    tk, round(shares, 6), close,
                    round(shares * close, 2) if close is not None else None,
                ])
    sheets.append(Sheet(
        "Positions",
        ["Ticker", "Shares", "Close", "Market Value"],
        pos_rows,
    ))

    # 9. Definitions (the cheat sheet)
    sheets.append(Sheet("Definitions", ["Field", "Meaning"], _DEFINITIONS))

    return ExportWorkbook(sheets)


def _shares_at(store, ticker, as_of):
    row = store._conn.execute(
        "SELECT shares FROM positions_daily WHERE ticker = ? AND as_of_date = ?",
        (ticker, as_of.isoformat()),
    ).fetchone()
    return row["shares"] if row else 0.0


def _d(v):
    from datetime import date as _date
    return v.isoformat() if isinstance(v, _date) else v

def _total_cost_basis(store):
    """Sum of net cash spent on current holdings (buys minus sells), positive."""
    total = 0.0
    for t in store.all_transactions():
        if t.transaction_type == 'buy':
            total += -t.amount
        elif t.transaction_type == 'sell':
            total -= t.amount
    return round(total, 2)
