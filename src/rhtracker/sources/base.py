"""The Source contract.

A source fetches portfolio data and returns it already normalized into the
shared :mod:`rhtracker.model` types, so the rest of the system never sees a raw
API shape. ``Source`` is a :class:`typing.Protocol` — structural typing — so any
class exposing the three methods qualifies without inheriting from anything.

It is ``runtime_checkable`` so tests (and callers) can assert conformance with a
plain ``isinstance`` check.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from rhtracker.model import PortfolioSnapshot, Price, Transaction


@runtime_checkable
class Source(Protocol):
    """How portfolio data is fetched. Normalization lives inside each source."""

    def authenticate(self) -> None:
        """Establish an authenticated session with the backing data source."""
        ...

    def fetch_transactions(self, since: date) -> list[Transaction]:
        """Return normalized transactions on or after ``since``."""
        ...

    def fetch_prices(self, tickers: list[str], dates: list[date]) -> list[Price]:
        """Return a close price per ticker per requested date.

        For each requested date, the close selected is the last one on or
        before that date.
        """
        ...

    def fetch_portfolio_snapshot(self) -> PortfolioSnapshot | None:
        """Return the broker's real point-in-time account state, or None if
        the source does not provide one. Optional: sources may omit it.
        """
        ...
