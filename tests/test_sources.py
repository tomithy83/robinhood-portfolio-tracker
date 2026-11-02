"""Unit test for the source seam (task 3.1).

Covers:

* ``FakeSource`` (test-only) satisfies the ``Source`` protocol and returns
  typed ``model.Transaction`` / ``model.Price`` objects.
* The Robinhood normalizers' sign conventions for buy (negative amount /
  positive shares) and sell (positive amount / negative shares) over BOTH the
  flat and nested-dict ``amount`` shapes.
* Property 9: ``FakeSource`` is deterministic — repeated ``fetch_transactions``
  / ``fetch_prices`` return identical results and ``FakeSource`` conforms to the
  contract.

``RobinhoodSource`` conformance is asserted structurally against the
``runtime_checkable`` protocol. No live network calls are made.

Validates: Requirements 3.1, 3.2, 6.1, 6.4
"""

from datetime import date

from rhtracker.model import Price, Transaction
from rhtracker.sources import robinhood
from rhtracker.sources.base import Source
from rhtracker.sources.robinhood import RobinhoodSource
from tests.fakes import FakeSource


# --------------------------------------------------------------------------
# Protocol conformance
# --------------------------------------------------------------------------
def test_fake_source_conforms_to_protocol():
    assert isinstance(FakeSource(), Source)


def test_robinhood_source_conforms_to_protocol():
    assert isinstance(RobinhoodSource(), Source)


def test_fake_source_returns_typed_transactions():
    txns = FakeSource().fetch_transactions(date(2025, 1, 1))
    assert txns, "FakeSource should return canned transactions"
    assert all(isinstance(t, Transaction) for t in txns)


def test_fake_source_returns_typed_prices():
    prices = FakeSource().fetch_prices(["AAPL"], [date(2025, 10, 31), date(2025, 11, 30)])
    assert prices
    assert all(isinstance(p, Price) for p in prices)


def test_fake_source_filters_transactions_by_since():
    txns = FakeSource().fetch_transactions(date(2025, 11, 1))
    assert [t.hash for t in txns] == ["h-div"]


# --------------------------------------------------------------------------
# Normalizer sign conventions — flat and nested-dict amount shapes
# --------------------------------------------------------------------------
def _stock_order(side, qty, price, amount_override=None):
    """Build a minimal filled stock-order raw record.

    The stock-order normalizer computes ``amount`` from ``qty * price``, so the
    "flat vs nested" amount-shape variation is exercised via the dedicated
    ``_amount`` helper rather than through the order payload.
    """
    return {
        "state": "filled",
        "side": side,
        "symbol": "AAPL",
        "cumulative_quantity": str(qty),
        "average_price": str(price),
        "last_transaction_at": "2025-10-01T00:00:00Z",
        "id": f"ord-{side}",
    }


def test_buy_sign_convention():
    txn = robinhood._normalize_stock_order(_stock_order("buy", 2, 100.0))
    assert isinstance(txn, Transaction)
    assert txn.transaction_type == "buy"
    assert txn.amount < 0          # cash out
    assert txn.quantity > 0        # shares in
    assert txn.amount == -200.0
    assert txn.quantity == 2.0


def test_sell_sign_convention():
    txn = robinhood._normalize_stock_order(_stock_order("sell", 1, 110.0))
    assert isinstance(txn, Transaction)
    assert txn.transaction_type == "sell"
    assert txn.amount > 0          # cash in
    assert txn.quantity < 0        # shares out
    assert txn.amount == 110.0
    assert txn.quantity == -1.0


def test_amount_helper_flat_and_nested_shapes():
    # flat numeric / string
    assert robinhood._amount(546.42) == 546.42
    assert robinhood._amount("546.42") == 546.42
    # nested dict {amount, currency_code}
    assert robinhood._amount({"amount": "546.42", "currency_code": "USD"}) == 546.42
    assert robinhood._amount({"amount": 0, "currency_code": "USD"}) == 0.0
    # defensive: missing / None
    assert robinhood._amount(None) == 0.0
    assert robinhood._amount({}) == 0.0


def test_dividend_positive_over_flat_amount():
    txn = robinhood._normalize_dividend(
        {"state": "paid", "amount": "5.25", "symbol": "AAPL",
         "paid_at": "2025-11-01T00:00:00Z", "id": "div-1"}
    )
    assert txn.transaction_type == "dividend"
    assert txn.amount == 5.25      # money in, positive


def test_dividend_positive_over_nested_amount():
    txn = robinhood._normalize_dividend(
        {"state": "paid", "amount": {"amount": "5.25", "currency_code": "USD"},
         "symbol": "AAPL", "paid_at": "2025-11-01T00:00:00Z", "id": "div-2"}
    )
    assert txn.transaction_type == "dividend"
    assert txn.amount == 5.25


def test_bank_transfer_deposit_positive_withdraw_negative():
    deposit = robinhood._normalize_bank_transfer(
        {"amount": "500", "direction": "deposit",
         "created_at": "2025-10-01T00:00:00Z", "id": "bt-1"}
    )
    withdraw = robinhood._normalize_bank_transfer(
        {"amount": {"amount": "500", "currency_code": "USD"}, "direction": "withdraw",
         "created_at": "2025-10-02T00:00:00Z", "id": "bt-2"}
    )
    assert deposit.amount == 500.0        # money in
    assert withdraw.amount == -500.0      # money out, nested shape


def test_margin_interest_and_subscription_fee_negative():
    mi = robinhood._normalize_margin_interest(
        {"amount": "3.14", "created_at": "2025-10-10T00:00:00Z", "id": "mi-1"}
    )
    sf = robinhood._normalize_subscription_fee(
        {"amount": {"amount": "5.00", "currency_code": "USD"},
         "created_at": "2025-10-11T00:00:00Z", "id": "sf-1"}
    )
    assert mi.amount == -3.14             # charge, negative
    assert sf.amount == -5.0             # fee, negative (nested shape)


# --------------------------------------------------------------------------
# Property 9: FakeSource is deterministic
# --------------------------------------------------------------------------
def test_property_9_fake_source_is_deterministic():
    """Feature: rhtracker-refactor, Property 9: FakeSource is deterministic.

    For any repeated invocation, FakeSource.fetch_transactions and
    FakeSource.fetch_prices return identical results, and FakeSource conforms to
    the Source contract.

    Validates: Requirements 6.1
    """
    src = FakeSource()
    assert isinstance(src, Source)

    since = date(2025, 1, 1)
    tickers = ["AAPL"]
    dates = [date(2025, 10, 31), date(2025, 11, 30)]

    # Repeat many times; every call must return identical results.
    first_txns = src.fetch_transactions(since)
    first_prices = src.fetch_prices(tickers, dates)
    for _ in range(100):
        assert src.fetch_transactions(since) == first_txns
        assert src.fetch_prices(tickers, dates) == first_prices


# --------------------------------------------------------------------------
# Settings-driven payee classification (de-personalized from hardcoded rules)
# --------------------------------------------------------------------------
from rhtracker import settings  # noqa: E402


def _rule(feed, direction, keywords, type):
    return settings.ClassifierRule(feed, direction, tuple(keywords), type)


def test_received_debit_uses_settings_classifier(monkeypatch):
    """A configured 'received/debit' keyword rule overrides the generic
    bill_payment label; with no rule the generic label stands."""
    monkeypatch.setattr(
        settings, "classifier_rules",
        lambda: [_rule("received", "debit", ["honda"], "auto_loan_payment")],
    )
    txn = robinhood._normalize_received_transfer(
        {"amount": {"amount": "546.42"}, "direction": "debit",
         "originator_name": "HONDA PMT", "created_at": "2025-10-05T00:00:00Z",
         "id": "rt-1"}
    )
    assert txn.transaction_type == "auto_loan_payment"
    assert txn.amount == -546.42

    # A payee with no matching rule falls back to the generic debit label.
    other = robinhood._normalize_received_transfer(
        {"amount": "20.00", "direction": "debit", "originator_name": "SOME LLC",
         "created_at": "2025-10-06T00:00:00Z", "id": "rt-2"}
    )
    assert other.transaction_type == "bill_payment"


def test_card_debit_uses_settings_classifier(monkeypatch):
    monkeypatch.setattr(
        settings, "classifier_rules",
        lambda: [_rule("card", "debit", ["honda"], "bill_payment")],
    )
    txn = robinhood._normalize_card_transaction(
        {"amount": "546.42", "direction": "debit", "description": "HONDA FIN",
         "created_at": "2025-10-05T00:00:00Z", "id": "ct-1"}
    )
    assert txn.transaction_type == "bill_payment"
    assert txn.amount == -546.42


def test_no_classifier_rules_leaves_generic_labels(monkeypatch):
    """With an empty rule set, the universal keyword labels still apply."""
    monkeypatch.setattr(settings, "classifier_rules", lambda: [])
    atm = robinhood._normalize_card_transaction(
        {"amount": "40.00", "direction": "debit", "description": "ATM CASH",
         "created_at": "2025-10-05T00:00:00Z", "id": "ct-2"}
    )
    assert atm.transaction_type == "atm_withdrawal"
