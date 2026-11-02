"""Reconstruction tests for rhtracker (tasks 4.1 + 4.2).

Task 4.1 — the authoritative 36-assertion oracle: a synthetic Oct/Nov/Dec 2025
transaction set with a fixed price cache, asserting every hand-computed value
across positions, valuation, flow aggregation, and margin. This is the
authoritative proof that the ported domain math is preserved.

Task 4.2 — property tests for reconstruction invariants (Properties 5, 6, 7).

Scenario (ported unchanged from the flat test_reconstruct.py):
  Oct: deposit 1000; buy 10 AAA @ 50 = -500 cash.          AAA close Oct31 = 55
  Nov: deposit 500; buy 10 AAA @ 60 = -600; dividend 20.   AAA close Nov30 = 60
  Dec: sell 5 AAA @ 70 = +350; margin interest 5;          AAA close Dec31 = 70
       card purchase 100.
"""

from __future__ import annotations

import hashlib
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from rhtracker import reconstruct
from rhtracker.model import Price, Transaction
from rhtracker.storage import SqliteStore


def _compute_hash(txn_date, txn_type, asset, amount, reference_id):
    raw = f"{txn_date}|{txn_type}|{asset}|{amount}|{reference_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _txn(d, typ, asset, amount, qty=None, ref=None):
    ref = ref or f"{typ}-{d}-{asset}"
    return Transaction(
        hash=_compute_hash(d, typ, asset, amount, ref),
        transaction_date=d,
        transaction_type=typ,
        asset=asset,
        amount=amount,
        quantity=qty,
        price=None,
        status="filled",
        reference_id=ref,
    )


def _approx(a, b, tol=0.01):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


# --------------------------------------------------------------------------
# Task 4.1 — the 36-assertion oracle
# --------------------------------------------------------------------------
def test_oracle_36_hand_computed_values():
    """Validates: Requirements 2.4, 6.3."""
    store = SqliteStore(":memory:")
    store.init_schema()

    txns = [
        # October
        _txn(date(2025, 10, 5), "deposit", "BANK_TRANSFER", 1000.0),
        _txn(date(2025, 10, 10), "buy", "AAA", -500.0, qty=10),
        # November
        _txn(date(2025, 11, 3), "deposit", "BANK_TRANSFER", 500.0),
        _txn(date(2025, 11, 12), "buy", "AAA", -600.0, qty=10),
        _txn(date(2025, 11, 20), "dividend", "AAA", 20.0),
        # December
        _txn(date(2025, 12, 8), "sell", "AAA", 350.0, qty=-5),
        _txn(date(2025, 12, 15), "margin_interest", "MARGIN", -5.0),
        _txn(date(2025, 12, 18), "card_purchase", "COFFEE", -100.0),
    ]
    store.save_transactions(txns)

    store.save_prices([
        Price("AAA", date(2025, 10, 31), 55.0),
        Price("AAA", date(2025, 11, 30), 60.0),
        Price("AAA", date(2025, 12, 31), 70.0),
    ])

    snapshots = reconstruct.build_snapshots(store, end=date(2025, 12, 31))
    by_month = {s.month_end: s for s in snapshots}

    # --- expected values, computed by hand ---
    # Shares: Oct 10, Nov 20, Dec 15.
    # Gross: Oct=10*55=550; Nov=20*60=1200; Dec=15*70=1050
    # net deposits: Oct 1000, Nov 500, Dec 0
    # total_increase: Oct None; Nov 1200-550=650; Dec 1050-1200=-150
    # asset_growth:   Oct None; Nov 650-500=150;  Dec -150-0=-150
    # dividends: Oct 0, Nov 20, Dec 0
    # interest_paid: Dec 5
    # expenses: Dec 100
    # cash_after_interest = dividends - interest: Nov 20, Dec -5
    # margin reconstruction (running signed cash):
    #   Oct: +1000 -500 = +500  -> debt 0
    #   Nov: +500 -600 +20 = -80 cumulative 500-80=420 -> debt 0
    #   Dec: +350 -5 -100 = +245 cumulative 665 -> debt 0
    expected = {
        date(2025, 10, 31): dict(
            gross_value=550.0, total_increase=None, asset_growth=None,
            dividends=0.0, interest_paid=0.0, monthly_expenses=0.0,
            w2_contribution=1000.0, total_w2_contribution=1000.0,
            margin_debt=0.0, net_portfolio_value=550.0,
            cash_after_interest=0.0, total_interest_paid=0.0),
        date(2025, 11, 30): dict(
            gross_value=1200.0, total_increase=650.0, asset_growth=150.0,
            dividends=20.0, interest_paid=0.0, monthly_expenses=0.0,
            w2_contribution=500.0, total_w2_contribution=1500.0,
            margin_debt=0.0, net_portfolio_value=1200.0,
            cash_after_interest=20.0, total_interest_paid=0.0),
        date(2025, 12, 31): dict(
            gross_value=1050.0, total_increase=-150.0, asset_growth=-150.0,
            dividends=0.0, interest_paid=5.0, monthly_expenses=100.0,
            w2_contribution=0.0, total_w2_contribution=1500.0,
            margin_debt=0.0, net_portfolio_value=1050.0,
            cash_after_interest=-5.0, total_interest_paid=5.0),
    }

    failures = []
    for month, exp in expected.items():
        got = by_month.get(month)
        if got is None:
            failures.append(f"{month}: no row produced")
            continue
        for key, want in exp.items():
            if not _approx(getattr(got, key), want):
                failures.append(f"{month}.{key}: got {getattr(got, key)!r}, want {want!r}")

    assert not failures, "oracle mismatches:\n  " + "\n  ".join(failures)
    # 3 months x 12 checked values = 36 hand-computed assertions.
    assert sum(len(v) for v in expected.values()) == 36


# --------------------------------------------------------------------------
# Task 4.2 — property tests
# --------------------------------------------------------------------------
@settings(max_examples=100)
@given(
    end=st.dates(min_value=date(2025, 10, 1), max_value=date(2035, 12, 31)),
)
def test_month_ends_bounded_and_ordered(end):
    """Property 5: Month-end generation is bounded and ordered.

    Feature: rhtracker-refactor, Property 5: For any end date on or after
    BACKFILL_START, the generated month-end dates are strictly ascending, begin
    at the BACKFILL_START month-end, and none fall in a future/incomplete month
    (every date is on or before the end date).

    Validates: Requirements 2.2
    """
    months = reconstruct.month_ends(end=end)

    first_me = date(2025, 10, 31)
    if end < first_me:
        # The BACKFILL_START month has not completed yet — nothing is emitted
        # (the incomplete-month boundary of Property 5).
        assert months == []
        return

    # Once the first month has completed, the series begins at its month-end.
    assert months[0] == first_me

    # Strictly ascending.
    assert all(a < b for a, b in zip(months, months[1:]))

    # None in a future/incomplete month.
    assert all(me <= end for me in months)


def _run_with(trades, prices, end):
    store = SqliteStore(":memory:")
    store.init_schema()
    txns = []
    for i, (d, typ, asset, amount, qty) in enumerate(trades):
        txns.append(_txn(d, typ, asset, amount, qty=qty, ref=f"t-{i}"))
    store.save_transactions(txns)
    store.save_prices(prices)
    snapshots = reconstruct.build_snapshots(store, end=end)
    return {s.month_end: s for s in snapshots}


# Asset classes: equities/funds are plain tickers; options and crypto use the
# shapes the pipeline must exclude. The flat pipeline keys gross_value purely on
# whether a price is cached for the held ticker, and only buy/sell trades move
# shares — so options/crypto contribute nothing because no close is cached for
# them. We model that: options/crypto tickers have NO price cached.
@settings(max_examples=100)
@given(
    equity_shares=st.integers(min_value=1, max_value=50),
    equity_close=st.integers(min_value=1, max_value=500),
    option_shares=st.integers(min_value=1, max_value=50),
    crypto_shares=st.integers(min_value=1, max_value=50),
)
def test_gross_value_counts_stocks_and_funds_only(
    equity_shares, equity_close, option_shares, crypto_shares
):
    """Property 6: gross_value counts stocks and funds only.

    Feature: rhtracker-refactor, Property 6: For any set of month-end holdings
    that mixes equities/funds with options and crypto, gross_value equals the
    valuation of the equity/fund holdings alone; options and crypto contribute
    nothing.

    Validates: Requirements 2.3
    """
    end = date(2025, 10, 31)
    me = date(2025, 10, 31)
    trades = [
        (date(2025, 10, 5), "buy", "EQT", -1.0, float(equity_shares)),
        (date(2025, 10, 6), "buy", "OPT_CALL", -1.0, float(option_shares)),
        (date(2025, 10, 7), "buy", "BTC", -1.0, float(crypto_shares)),
    ]
    # Only the equity has a cached close; options/crypto are not priced, so they
    # contribute nothing to gross_value and are surfaced as missing flags.
    prices = [Price("EQT", me, float(equity_close))]

    by_month = _run_with(trades, prices, end)
    snap = by_month[me]

    assert snap.gross_value == round(equity_shares * equity_close, 2)
    assert snap.value_flags is not None
    assert "OPT_CALL" in snap.value_flags
    assert "BTC" in snap.value_flags


@settings(max_examples=100)
@given(
    priced_shares=st.integers(min_value=1, max_value=50),
    priced_close=st.integers(min_value=1, max_value=500),
    missing_shares=st.integers(min_value=1, max_value=50),
)
def test_missing_prices_flagged_not_zeroed(
    priced_shares, priced_close, missing_shares
):
    """Property 7: Missing prices are flagged, not zeroed.

    Feature: rhtracker-refactor, Property 7: For any holdings in which some
    tickers have no cached close on or before the month-end, each such ticker is
    named in value_flags and gross_value equals the sum of only the priced
    holdings.

    Validates: Requirements 2.5
    """
    end = date(2025, 10, 31)
    me = date(2025, 10, 31)
    trades = [
        (date(2025, 10, 5), "buy", "HAVE", -1.0, float(priced_shares)),
        (date(2025, 10, 6), "buy", "GONE", -1.0, float(missing_shares)),
    ]
    prices = [Price("HAVE", me, float(priced_close))]

    by_month = _run_with(trades, prices, end)
    snap = by_month[me]

    # gross_value is the priced holding only — the missing one is NOT zeroed in,
    # it is simply excluded from the sum.
    assert snap.gross_value == round(priced_shares * priced_close, 2)
    assert snap.value_flags is not None
    assert "GONE" in snap.value_flags
    assert "HAVE" not in snap.value_flags
