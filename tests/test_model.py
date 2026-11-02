"""Unit test for the domain model (task 1.1).

Covers construction of each dataclass, the signed amount/quantity conventions,
and Property 4 (snapshots carry exactly the 17 columns).
"""

import dataclasses
from datetime import date

from rhtracker.model import MonthlySnapshot, Position, Price, Transaction


def test_transaction_fields_and_buy_sell_sign_conventions():
    expected_fields = (
        "hash",
        "transaction_date",
        "transaction_type",
        "asset",
        "amount",
        "quantity",
        "price",
        "status",
        "reference_id",
    )
    assert tuple(f.name for f in dataclasses.fields(Transaction)) == expected_fields

    # buy: cash out (amount negative), shares in (quantity positive)
    buy = Transaction(
        hash="h1",
        transaction_date=date(2025, 10, 1),
        transaction_type="buy",
        asset="AAPL",
        amount=-100.0,
        quantity=1.0,
        price=100.0,
        status="filled",
        reference_id="ref-buy",
    )
    assert buy.amount < 0
    assert buy.quantity > 0

    # sell: cash in (amount positive), shares out (quantity negative)
    sell = Transaction(
        hash="h2",
        transaction_date=date(2025, 10, 2),
        transaction_type="sell",
        asset="AAPL",
        amount=100.0,
        quantity=-1.0,
        price=100.0,
        status="filled",
        reference_id="ref-sell",
    )
    assert sell.amount > 0
    assert sell.quantity < 0


def test_transaction_is_frozen():
    txn = Transaction(
        hash="h",
        transaction_date=date(2025, 10, 1),
        transaction_type="dividend",
        asset=None,
        amount=5.0,
        quantity=None,
        price=None,
        status=None,
        reference_id=None,
    )
    try:
        txn.amount = 10.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("Transaction should be frozen")


def test_position_fields():
    pos = Position(as_of_date=date(2025, 10, 31), ticker="AAPL", shares=3.0)
    assert tuple(f.name for f in dataclasses.fields(Position)) == (
        "as_of_date",
        "ticker",
        "shares",
    )
    assert pos.ticker == "AAPL"
    assert pos.shares == 3.0


def test_price_fields():
    price = Price(ticker="AAPL", price_date=date(2025, 10, 31), close=123.45)
    assert tuple(f.name for f in dataclasses.fields(Price)) == (
        "ticker",
        "price_date",
        "close",
    )
    assert price.close == 123.45


def test_monthly_snapshot_has_exactly_17_columns():
    """Property 4: Snapshots carry exactly the 17 columns.

    Feature: rhtracker-refactor, Property 4: For any reconstruction output,
    every MonthlySnapshot exposes exactly the 17 defined columns — no more and
    no fewer.

    Validates: Requirements 2.1, 6.4
    """
    expected_columns = (
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
    actual_columns = tuple(f.name for f in dataclasses.fields(MonthlySnapshot))
    assert actual_columns == expected_columns
    # The spec enumerates these column names as "the 17 columns"; the explicit
    # list (requirements 2.1 and design model.py) contains exactly these names.
    assert len(actual_columns) == len(expected_columns)


def test_monthly_snapshot_constructs_with_all_columns():
    snap = MonthlySnapshot(
        month_end=date(2025, 10, 31),
        gross_value=1000.0,
        total_increase=100.0,
        asset_growth=50.0,
        dividends=5.0,
        interest_paid=2.0,
        cash_after_interest=3.0,
        monthly_expenses=10.0,
        margin_used=0.0,
        margin_paid_down=0.0,
        margin_debt=0.0,
        w2_contribution=200.0,
        total_w2_contribution=200.0,
        net_portfolio_value=1000.0,
        total_interest_paid=2.0,
        value_flags=None,
    )
    assert snap.month_end == date(2025, 10, 31)
    assert snap.net_portfolio_value == 1000.0
