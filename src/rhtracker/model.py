"""Shared domain data for rhtracker.

Plain frozen dataclasses with no behavior beyond construction. These replace
the ad-hoc dicts the flat code passed around and are the shared vocabulary at
the bottom of the dependency graph — this module imports nothing from the
package.

Sign conventions (preserved from the flat modules):

* ``Transaction.amount`` is signed: positive means money in, negative means
  money out.
* ``Transaction.quantity`` is a signed share delta for trades: positive for a
  buy (shares in), negative for a sell (shares out).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Transaction:
    hash: str                 # sha256 over date|type|asset|amount|reference_id
    transaction_date: date
    transaction_type: str     # 'buy','sell','dividend','deposit','margin_interest', ...
    asset: str | None         # ticker for trades; label otherwise
    amount: float             # signed: + money in, - money out
    quantity: float | None    # SIGNED share delta for trades (+ buy, - sell)
    price: float | None
    status: str | None
    reference_id: str | None


@dataclass(frozen=True)
class Position:
    as_of_date: date
    ticker: str
    shares: float


@dataclass(frozen=True)
class Price:
    ticker: str
    price_date: date
    close: float


@dataclass(frozen=True)
class MonthlySnapshot:
    """A single month-end row — exactly the 17 columns of ``monthly_tracking``.

    This is the single authoritative definition of the snapshot schema
    (``month_end`` plus the 16 metric fields).
    """

    month_end: date
    gross_value: float | None
    total_increase: float | None
    asset_growth: float | None
    dividends: float | None
    interest_paid: float | None
    cash_after_interest: float | None
    monthly_expenses: float | None
    margin_used: float | None
    margin_paid_down: float | None
    margin_debt: float | None
    w2_contribution: float | None
    total_w2_contribution: float | None
    net_portfolio_value: float | None
    total_interest_paid: float | None
    value_flags: str | None


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Real point-in-time account state from the broker (not reconstructed).

    Captured at pull time from the live account/portfolio profile. All values
    are the broker's actual figures, unlike the reconstructed monthly margin.
    """
    captured_at: str                  # ISO timestamp
    gross_value: float | None         # portfolio.market_value
    equity: float | None              # portfolio.equity (net value)
    cash: float | None                # account.cash (negative => margin)
    margin_borrowed: float | None     # margin_balances.settled_amount_borrowed
    outstanding_interest: float | None  # margin_balances.outstanding_interest
    buying_power: float | None        # account.buying_power
    excess_maintenance: float | None  # portfolio.excess_maintenance (buffer)
    withdrawable: float | None        # portfolio.withdrawable_amount
    equity_previous_close: float | None
    market_value_previous_close: float | None
    portfolio_cash: float | None = None          # UI 'Margin Borrowed' (magnitude)
    overnight_buying_power: float | None = None   # API buying_power (overnight)
    overnight_ratio: float | None = None          # e.g. 0.50; full BP = obp/ratio
    ext_gross_value: float | None = None          # extended_hours_market_value
    ext_equity: float | None = None               # extended_hours_equity
