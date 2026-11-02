"""Tests for split-adjusted position reconstruction.

A reverse split back-adjusts Robinhood''s price series, so reconstructed share
counts must be scaled to the current (post-split) basis. These tests pin that
behavior using a synthetic MSTY-style 1-for-5 reverse split.
"""

from datetime import date

from rhtracker import reconstruct, settings
from rhtracker import splits as splits_mod
from rhtracker.model import Price, Transaction
from rhtracker.storage import SqliteStore


def _txn(d, typ, asset, amount, qty, ref):
    return Transaction(
        hash=ref, transaction_date=d, transaction_type=typ, asset=asset,
        amount=amount, quantity=qty, price=None, status="filled", reference_id=ref,
    )


def _patch_splits(monkeypatch, entries):
    """Make settings.splits() return the given list of SplitEntry objects."""
    monkeypatch.setattr(settings, "splits", lambda: entries)


def test_adjustment_factor_scales_only_pre_split_trades(monkeypatch):
    _patch_splits(monkeypatch, [settings.SplitEntry("ZZZ", date(2025, 12, 8), 0.2)])
    # pre-split trade is scaled by 0.2; on/after-split trade is unchanged
    assert splits_mod.adjustment_factor("ZZZ", date(2025, 11, 1)) == 0.2
    assert splits_mod.adjustment_factor("ZZZ", date(2025, 12, 8)) == 1.0
    assert splits_mod.adjustment_factor("ZZZ", date(2026, 1, 1)) == 1.0
    assert splits_mod.adjustment_factor("OTHER", date(2025, 11, 1)) == 1.0


def test_reverse_split_values_pre_split_month_on_adjusted_basis(monkeypatch):
    _patch_splits(monkeypatch, [settings.SplitEntry("ZZZ", date(2025, 12, 8), 0.2)])
    store = SqliteStore(":memory:"); store.init_schema()
    # Buy 50 pre-split shares in Oct; back-adjusted close is 10.
    store.save_transactions([_txn(date(2025, 10, 5), "buy", "ZZZ", -100.0, 50.0, "r1")])
    store.save_prices([Price("ZZZ", date(2025, 10, 31), 10.0)])

    snaps = reconstruct.build_snapshots(
        store, start=date(2025, 10, 1), end=date(2025, 10, 31)
    )
    oct_snap = {s.month_end: s for s in snaps}[date(2025, 10, 31)]
    # 50 pre-split shares -> 10 adjusted shares; 10 * 10.0 = 100.0 (not 500).
    assert oct_snap.gross_value == 100.0
