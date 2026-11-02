"""Formatting of reconstruction output into human-readable reports.

Ports ``report.py`` from the flat layout, with one deliberate change: these
functions *return* strings instead of printing, so the services / CLI layers
decide where the output goes (stdout, a cron log, a test assertion).

Library layer: imports :mod:`rhtracker.model` only — no printing, no store
access, no network.
"""

from __future__ import annotations

from rhtracker import model


# Column layout ported verbatim from the flat ``report.py`` COLUMNS table:
# (MonthlySnapshot attribute, header label, width, number format).
COLUMNS = [
    ("month_end", "Month", 10, "s"),
    ("gross_value", "GrossVal", 10, ",.2f"),
    ("total_increase", "TotIncr", 9, ",.2f"),
    ("asset_growth", "AssetGrw", 9, ",.2f"),
    ("dividends", "Divid", 8, ",.2f"),
    ("interest_paid", "IntPaid", 8, ",.2f"),
    ("cash_after_interest", "CashAftI", 9, ",.2f"),
    ("monthly_expenses", "Expenses", 10, ",.2f"),
    ("margin_used", "MgnUsed", 9, ",.2f"),
    ("margin_paid_down", "MgnPaid", 9, ",.2f"),
    ("margin_debt", "MgnDebt", 9, ",.2f"),
    ("w2_contribution", "W2Contr", 10, ",.2f"),
    ("total_w2_contribution", "TotW2", 11, ",.2f"),
    ("net_portfolio_value", "NetPV", 10, ",.2f"),
    ("total_interest_paid", "TotInt", 8, ",.2f"),
]


def _fmt(val, fmt: str) -> str:
    """Format a single cell, blanking ``None`` as the flat ``_fmt`` did."""
    if val is None:
        return ""
    if fmt == "s":
        return str(val)
    try:
        return format(val, fmt)
    except (ValueError, TypeError):
        return str(val)


def render_monthly(snapshots: list[model.MonthlySnapshot]) -> str:
    """Render month-end snapshots as an aligned table.

    Produces a header row, a rule, and one line per snapshot. When a snapshot's
    ``value_flags`` is set, a ``! <flags>`` line is emitted directly beneath its
    row (ported from the flat report's missing-price flag line). ``None`` cells
    render blank.
    """
    if not snapshots:
        return "No monthly_tracking rows. Run reconstruct first."

    header = " ".join(f"{label:>{w}}" for _, label, w, _ in COLUMNS)
    lines = [header, "-" * len(header)]
    for snap in snapshots:
        line = " ".join(
            f"{_fmt(getattr(snap, key), fmt):>{w}}"
            for key, _, w, fmt in COLUMNS
        )
        lines.append(line)
        if snap.value_flags:
            lines.append(f"    ! {snap.value_flags}")
    return "\n".join(lines)


def render_transaction_summary(summary) -> str:
    """Render a per-type transaction summary.

    Takes the output of ``SqliteStore.transaction_summary()`` — rows with
    ``transaction_type``, ``n`` (count), and ``total_amount`` (signed sum) —
    and returns an aligned table. The flat report's first/last columns are not
    available from the store's summary, so the column set is adapted to the
    three columns the store actually provides.
    """
    rows = list(summary)
    if not rows:
        return "No transactions in DB."

    header = f"{'type':<22}{'count':>7}{'sum_amount':>14}"
    lines = [header, "-" * len(header)]
    total_count = 0
    for r in rows:
        txn_type = r["transaction_type"]
        n = r["n"]
        total_amount = r["total_amount"] or 0.0
        total_count += n
        lines.append(f"{txn_type:<22}{n:>7}{total_amount:>14,.2f}")
    lines.append(f"\nTotal transactions: {total_count}")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Category tables (dividends / expenses / fees / stock trades)
# ----------------------------------------------------------------------
def _category_table(title, rows, label_header, label_width=24):
    """Render a list of CategoryRow as a titled count/total table."""
    lines = [title, "=" * len(title)]
    header = f"{label_header:<{label_width}}{'count':>8}{'total':>14}"
    lines.append(header)
    lines.append("-" * len(header))
    total = 0.0
    count = 0
    for r in rows:
        total += r.total
        count += r.count
        lines.append(f"{r.label[:label_width]:<{label_width}}{r.count:>8}{r.total:>14,.2f}")
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<{label_width}}{count:>8}{total:>14,.2f}")
    return "\n".join(lines)


def render_dividends(rows):
    """Dividend income by ticker."""
    return _category_table("Dividends by ticker", rows, "ticker", 10)


def render_expenses(rows):
    """Account outflows by payee."""
    return _category_table("Expenses by payee", rows, "payee", 28)


def render_fees(rows):
    """Fees: margin interest and subscription (Gold)."""
    return _category_table("Fees", rows, "type", 20)


def render_stock_trades(rows):
    """Per-ticker buy/sell counts and dollar amounts."""
    title = "Stock purchases / sales by ticker"
    lines = [title, "=" * len(title)]
    header = (f"{'ticker':<8}{'buys':>6}{'buy_amount':>14}"
              f"{'sells':>7}{'sell_amount':>14}")
    lines.append(header)
    lines.append("-" * len(header))
    tb = ts = 0.0
    for r in rows:
        tb += r.buy_total
        ts += r.sell_total
        lines.append(f"{r.ticker[:8]:<8}{r.buy_count:>6}{r.buy_total:>14,.2f}"
                     f"{r.sell_count:>7}{r.sell_total:>14,.2f}")
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<8}{'':>6}{tb:>14,.2f}{'':>7}{ts:>14,.2f}")
    return "\n".join(lines)


def render_option_trades(rows):
    """Per-underlying option premium bought/sold."""
    title = "Options bought / sold by underlying (premium)"
    lines = [title, "=" * len(title)]
    header = (f"{'under':<8}{'bought':>6}{'buy_premium':>14}"
              f"{'sold':>7}{'sell_premium':>14}")
    lines.append(header)
    lines.append("-" * len(header))
    tb = ts = 0.0
    for r in rows:
        tb += r.buy_total
        ts += r.sell_total
        lines.append(f"{r.ticker[:8]:<8}{r.buy_count:>6}{r.buy_total:>14,.2f}"
                     f"{r.sell_count:>7}{r.sell_total:>14,.2f}")
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<8}{'':>6}{tb:>14,.2f}{'':>7}{ts:>14,.2f}")
    return "\n".join(lines)
