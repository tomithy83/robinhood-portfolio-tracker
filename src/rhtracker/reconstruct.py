"""Flow reconstruction — the pure domain math (task 4).

Ported verbatim (in behavior) from the flat ``reconstruct.py``, retargeted from
the raw ``db`` connection to ``SqliteStore`` reads and returning
``model.MonthlySnapshot`` objects instead of dicts. No network, no ``print``.

Pipeline (preserved):

  1. ``month_ends()``        -> month-end dates from the caller-supplied start
                               date to the latest COMPLETED month.
  2. ``reconstruct_positions`` -> shares held per ticker at each month-end
                               (cumulative signed share deltas from buy/sell).
  3. ``value_positions``     -> gross_value per month-end using the close on or
                               before the month-end. Stocks/funds only; options
                               and crypto excluded. Missing prices are flagged,
                               not zeroed.
  4. ``aggregate_flows``     -> dividends, interest, deposits, expenses per month.
  5. ``reconstruct_margin``  -> running margin debt from net cash flows
                               (documented approximation).
  6. ``build_snapshots``     -> the 17-column MonthlySnapshot rows, persisted via
                               ``store.save_snapshots``.

Everything is deterministic from the stored transactions and the price cache;
the only externally-sourced input is the price cache, populated by the live
pull. This is a library-layer module: it imports only ``model`` (plus stdlib).
"""

from __future__ import annotations

import calendar
import logging
from datetime import date

from rhtracker.model import MonthlySnapshot, Position
from rhtracker.splits import adjustment_factor

log = logging.getLogger("rh_reconstruct")

# --- transaction-type groupings (ported unchanged) ------------------------
DEPOSIT_TYPES = {"deposit", "direct_deposit", "payroll_deposit", "wire_deposit"}
WITHDRAWAL_TYPES = {"withdrawal", "wire_withdrawal"}
# "Monthly expenses" per spec = account spending outflows
EXPENSE_TYPES = {
    "card_purchase", "atm_withdrawal", "bill_payment",
    "auto_loan_payment", "student_loan_payment", "subscription_fee",
    "rhy_transfer",
}
DIVIDEND_TYPES = {"dividend"}
MARGIN_INTEREST_TYPES = {"margin_interest"}
INTEREST_IN_TYPES = {"interest_payment"}
CASH_IN_TYPES = DEPOSIT_TYPES | {"refund", "cashback"} | INTEREST_IN_TYPES
BUY_TYPES = {"buy"}
SELL_TYPES = {"sell"}


def month_ends(start, end=None):
    """Return month-end dates from ``start``'s month through the latest
    COMPLETED month before ``end`` (default today).

    ``start`` is required — the caller must supply the backfill start date;
    there is no built-in default."""
    if end is None:
        end = date.today()
    results = []
    y, m = start.year, start.month
    while True:
        last_day = calendar.monthrange(y, m)[1]
        me = date(y, m, last_day)
        # only include month-ends that have fully passed
        if me > end:
            break
        results.append(me)
        if (y, m) >= (end.year, end.month):
            break
        m += 1
        if m > 12:
            m, y = 1, y + 1
    # drop the current (incomplete) month if its end is in the future
    return [me for me in results if me <= end]


def _fetch_txns(store):
    """Read all transactions as plain dicts in the shape the pipeline expects."""
    out = []
    for t in store.all_transactions():
        out.append({
            "date": t.transaction_date,
            "type": t.transaction_type,
            "asset": t.asset,
            "amount": t.amount or 0.0,
            "quantity": t.quantity,
        })
    return out


def reconstruct_positions(store, months):
    """Compute shares held per ticker at each month-end and persist them.
    Returns ``{month_end: {ticker: shares}}``."""
    txns = _fetch_txns(store)
    trades = [t for t in txns if t["type"] in (BUY_TYPES | SELL_TYPES) and t["quantity"]]

    result = {}
    for me in months:
        holdings = {}
        for t in trades:
            if t["date"] <= me:
                # Scale the trade to the current (post-all-splits) basis so
                # share counts match Robinhood's back-adjusted prices.
                adj = t["quantity"] * adjustment_factor(t["asset"], t["date"])
                holdings[t["asset"]] = holdings.get(t["asset"], 0.0) + adj
        # drop dust / fully-closed positions
        holdings = {k: round(v, 6) for k, v in holdings.items() if round(v, 6) > 0}
        result[me] = holdings
        store.save_positions(
            [Position(as_of_date=me, ticker=ticker, shares=shares)
             for ticker, shares in holdings.items()]
        )
    return result


def value_positions(store, positions_by_month):
    """Return ``{month_end: (gross_value, [missing_tickers])}`` using the price
    cache; the close on or before the month-end values each holding. Missing
    prices are collected, not zeroed."""
    out = {}
    for me, holdings in positions_by_month.items():
        gross = 0.0
        missing = []
        for ticker, shares in holdings.items():
            close = store.price_on_or_before(ticker, me)
            if close is None:
                missing.append(ticker)
                continue
            gross += shares * close
        out[me] = (round(gross, 2), missing)
    return out


def aggregate_flows(store, months):
    """Per-month sums of dividends, margin interest, expenses, net deposits."""
    txns = _fetch_txns(store)
    agg = {me: {"dividends": 0.0, "interest_paid": 0.0, "expenses": 0.0,
                "deposits": 0.0, "withdrawals": 0.0, "net_trade_cash": 0.0}
           for me in months}

    def bucket_for(d):
        for me in months:
            if d.year == me.year and d.month == me.month:
                return me
        return None

    for t in txns:
        me = bucket_for(t["date"])
        if me is None:
            continue
        a = agg[me]
        typ = t["type"]
        amt = t["amount"]
        if typ in DIVIDEND_TYPES:
            a["dividends"] += amt
        elif typ in MARGIN_INTEREST_TYPES:
            a["interest_paid"] += -amt  # stored negative, report positive charge
        elif typ in EXPENSE_TYPES:
            a["expenses"] += -amt       # stored negative, report positive spend
        elif typ in DEPOSIT_TYPES:
            a["deposits"] += amt
        elif typ in WITHDRAWAL_TYPES:
            a["withdrawals"] += -amt
        if typ in BUY_TYPES or typ in SELL_TYPES:
            a["net_trade_cash"] += amt  # buy negative, sell positive

    for me in months:
        a = agg[me]
        for k in a:
            a[k] = round(a[k], 2)
    return agg


def reconstruct_margin(store, months, flows):
    """Reconstruct running margin debt from net cash flows.

    APPROXIMATION (documented in spec): Robinhood does not expose historical
    margin balances. We model a running cash position; when it goes negative,
    the magnitude is treated as margin debt. Cash deltas per month:
        + deposits + dividends + interest_in + sells
        - withdrawals - expenses - margin_interest - buys
    Margin debt at month-end = ``max(0, -running_cash)``.
    Returns ``{month_end: (margin_debt, margin_used, margin_paid_down)}``.
    """
    txns = _fetch_txns(store)

    def bucket_for(d):
        for me in months:
            if d.year == me.year and d.month == me.month:
                return me
        return None

    # net signed cash delta per month (every txn amount is already signed)
    cash_delta = {me: 0.0 for me in months}
    for t in txns:
        me = bucket_for(t["date"])
        if me is None:
            continue
        cash_delta[me] += t["amount"]

    out = {}
    running_cash = 0.0
    prev_debt = 0.0
    for me in months:
        running_cash += cash_delta[me]
        debt = round(max(0.0, -running_cash), 2)
        delta = debt - prev_debt
        margin_used = round(delta, 2) if delta > 0 else 0.0
        margin_paid_down = round(-delta, 2) if delta < 0 else 0.0
        out[me] = (debt, margin_used, margin_paid_down)
        prev_debt = debt
    return out


def build_snapshots(store, start, end=None):
    """Assemble the 17-column ``MonthlySnapshot`` rows and persist them.

    ``start`` is the backfill start date (required). Returns a
    ``list[MonthlySnapshot]`` (empty if no completed month in range).
    """
    months = month_ends(start=start, end=end)
    if not months:
        log.warning("No completed months in range.")
        return []

    positions = reconstruct_positions(store, months)
    values = value_positions(store, positions)
    flows = aggregate_flows(store, months)
    margin = reconstruct_margin(store, months, flows)

    snapshots = []
    prev_gross = None
    cum_w2 = 0.0
    cum_interest = 0.0

    for me in months:
        gross, missing = values[me]
        f = flows[me]
        debt, m_used, m_paid = margin[me]

        net_deposits = round(f["deposits"] - f["withdrawals"], 2)
        total_increase = round(gross - prev_gross, 2) if prev_gross is not None else None
        asset_growth = (round(gross - prev_gross - net_deposits, 2)
                        if prev_gross is not None else None)

        dividends = f["dividends"]
        interest_paid = f["interest_paid"]
        cum_interest = round(cum_interest + interest_paid, 2)
        cum_w2 = round(cum_w2 + net_deposits, 2)

        snap = MonthlySnapshot(
            month_end=me,
            gross_value=gross,
            total_increase=total_increase,
            asset_growth=asset_growth,
            dividends=dividends,
            interest_paid=interest_paid,
            cash_after_interest=round(dividends - interest_paid, 2),
            monthly_expenses=f["expenses"],
            margin_used=m_used,
            margin_paid_down=m_paid,
            margin_debt=debt,
            w2_contribution=net_deposits,
            total_w2_contribution=cum_w2,
            net_portfolio_value=round(gross - debt, 2),
            total_interest_paid=cum_interest,
            value_flags=("missing price: " + ", ".join(missing)) if missing else None,
        )
        snapshots.append(snap)
        prev_gross = gross

    store.save_snapshots(snapshots)
    return snapshots
