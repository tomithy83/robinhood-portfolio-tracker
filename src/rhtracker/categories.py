"""Category breakdowns over the transaction log (library layer).

Pure functions that turn a list of model.Transaction into grouped category
tables for reporting: dividends, expenses, fees, and stock trades. Imports only
model, so it sits in the library layer alongside the other domain modules.

Each builder returns rows as plain dataclasses the reporting layer formats; no
printing and no storage access happens here.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from rhtracker.model import Transaction

# Transaction-type groupings per category (kept in step with reconstruct.py).
DIVIDEND_TYPES = {"dividend"}
EXPENSE_TYPES = {"bill_payment", "auto_loan_payment", "student_loan_payment",
                 "card_purchase", "atm_withdrawal", "rhy_transfer"}
FEE_TYPES = {"margin_interest", "subscription_fee"}
TRADE_TYPES = {"buy", "sell"}
OPTION_TYPES = {"option_buy", "option_sell"}


@dataclass(frozen=True)
class CategoryRow:
    """One grouped row: a label, a count, and a signed-or-positive total."""
    label: str
    count: int
    total: float


@dataclass(frozen=True)
class TradeRow:
    """A per-ticker trade summary: buy count/amount and sell count/amount."""
    ticker: str
    buy_count: int
    buy_total: float
    sell_count: int
    sell_total: float


def _round(x: float) -> float:
    return round(x, 2)


def dividends_by_ticker(txns: list[Transaction]) -> list[CategoryRow]:
    """Dividend income grouped by ticker, descending by total."""
    agg: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for t in txns:
        if t.transaction_type in DIVIDEND_TYPES:
            agg[t.asset or "UNKNOWN"][0] += 1
            agg[t.asset or "UNKNOWN"][1] += t.amount
    rows = [CategoryRow(k, int(n), _round(s)) for k, (n, s) in agg.items()]
    return sorted(rows, key=lambda r: r.total, reverse=True)


def expenses_by_payee(txns: list[Transaction]) -> list[CategoryRow]:
    """Account outflows grouped by payee (asset label), as positive amounts."""
    agg: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for t in txns:
        if t.transaction_type in EXPENSE_TYPES:
            agg[t.asset or "UNKNOWN"][0] += 1
            agg[t.asset or "UNKNOWN"][1] += -t.amount  # stored negative -> show positive
    rows = [CategoryRow(k, int(n), _round(s)) for k, (n, s) in agg.items()]
    return sorted(rows, key=lambda r: r.total, reverse=True)


def fees_by_type(txns: list[Transaction]) -> list[CategoryRow]:
    """Fees (margin interest, gold membership) grouped by type, as positive."""
    agg: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for t in txns:
        if t.transaction_type in FEE_TYPES:
            agg[t.transaction_type][0] += 1
            agg[t.transaction_type][1] += -t.amount
    rows = [CategoryRow(k, int(n), _round(s)) for k, (n, s) in agg.items()]
    return sorted(rows, key=lambda r: r.total, reverse=True)


def stock_trades_by_ticker(txns: list[Transaction]) -> list[TradeRow]:
    """Per-ticker buy/sell counts and dollar amounts (both shown positive)."""
    buys: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    sells: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for t in txns:
        if t.transaction_type == "buy":
            buys[t.asset or "UNKNOWN"][0] += 1
            buys[t.asset or "UNKNOWN"][1] += -t.amount  # cash out -> positive spend
        elif t.transaction_type == "sell":
            sells[t.asset or "UNKNOWN"][0] += 1
            sells[t.asset or "UNKNOWN"][1] += t.amount   # cash in -> positive proceeds
    tickers = sorted(set(buys) | set(sells),
                     key=lambda k: buys[k][1], reverse=True)
    return [
        TradeRow(k, int(buys[k][0]), _round(buys[k][1]),
                 int(sells[k][0]), _round(sells[k][1]))
        for k in tickers
    ]


def option_trades_by_underlying(txns: list[Transaction]) -> list[TradeRow]:
    """Per-underlying option premium: bought (debit) vs sold (credit).

    option_buy = premium paid (stored negative); option_sell = premium
    received (stored positive). Both shown positive in the table, like the
    stock-trades view.
    """
    buys: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    sells: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for t in txns:
        if t.transaction_type == 'option_buy':
            buys[t.asset or 'UNKNOWN'][0] += 1
            buys[t.asset or 'UNKNOWN'][1] += -t.amount
        elif t.transaction_type == 'option_sell':
            sells[t.asset or 'UNKNOWN'][0] += 1
            sells[t.asset or 'UNKNOWN'][1] += t.amount
    unders = sorted(set(buys) | set(sells), key=lambda k: buys[k][1], reverse=True)
    return [
        TradeRow(k, int(buys[k][0]), _round(buys[k][1]),
                 int(sells[k][0]), _round(sells[k][1]))
        for k in unders
    ]
