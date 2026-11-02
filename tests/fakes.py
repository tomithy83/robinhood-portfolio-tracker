"""Test-only fakes shared across the suite.

``FakeSource`` is a deterministic in-memory implementation of the
:class:`~rhtracker.sources.base.Source` protocol. It is NOT part of the
``rhtracker`` package — it lives in the test suite so the services layer and the
source seam can be exercised with no live Robinhood authentication and no
network. Keeping it in one module means ``test_sources.py`` and
``test_services.py`` share a single definition.
"""

from datetime import date

from rhtracker.model import PortfolioSnapshot, Price, Transaction


class FakeSource:
    """Deterministic in-memory ``Source`` with canned data for offline tests."""

    _TRANSACTIONS = (
        Transaction(
            hash="h-buy",
            transaction_date=date(2025, 10, 1),
            transaction_type="buy",
            asset="AAPL",
            amount=-200.0,
            quantity=2.0,
            price=100.0,
            status="filled",
            reference_id="ref-buy",
        ),
        Transaction(
            hash="h-sell",
            transaction_date=date(2025, 10, 15),
            transaction_type="sell",
            asset="AAPL",
            amount=110.0,
            quantity=-1.0,
            price=110.0,
            status="filled",
            reference_id="ref-sell",
        ),
        Transaction(
            hash="h-div",
            transaction_date=date(2025, 11, 1),
            transaction_type="dividend",
            asset="AAPL",
            amount=5.0,
            quantity=None,
            price=None,
            status="paid",
            reference_id="ref-div",
        ),
    )

    _PRICES = (
        Price(ticker="AAPL", price_date=date(2025, 10, 31), close=120.0),
        Price(ticker="AAPL", price_date=date(2025, 11, 30), close=130.0),
    )

    def authenticate(self) -> None:
        return None

    def fetch_transactions(self, since: date) -> list[Transaction]:
        return [t for t in self._TRANSACTIONS if t.transaction_date >= since]

    def fetch_prices(self, tickers: list[str], dates: list[date]) -> list[Price]:
        return [
            p for p in self._PRICES if p.ticker in tickers and p.price_date in dates
        ]

    def fetch_portfolio_snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            captured_at='2026-01-01T00:00:00+00:00',
            gross_value=1000.0, equity=600.0, cash=-400.0,
            margin_borrowed=400.0, outstanding_interest=2.5,
            buying_power=150.0, excess_maintenance=500.0, withdrawable=100.0,
            equity_previous_close=580.0, market_value_previous_close=980.0,
            portfolio_cash=-400.0, overnight_buying_power=75.0, overnight_ratio=0.5,
            ext_gross_value=1010.0, ext_equity=610.0,
        )
