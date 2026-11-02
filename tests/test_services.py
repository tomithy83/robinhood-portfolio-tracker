"""Cohesion tests for the services orchestration layer (task 6.1).

These exercise ``services.pull`` / ``reconstruct`` / ``report`` end to end with a
``FakeSource`` and an in-memory :class:`SqliteStore`. The whole chain must run
offline, purely through the ``Source`` contract — no live Robinhood auth, no
network — which is exactly what the services seam promises.

Validates: Requirements 3.3, 6.2, 6.4
"""

from datetime import date

from tests.fakes import FakeSource

from rhtracker import services
from rhtracker.model import MonthlySnapshot
from rhtracker.storage import SqliteStore


def _fresh_store() -> SqliteStore:
    store = SqliteStore(":memory:")
    store.init_schema()
    return store


def test_pull_runs_offline_through_source_contract_and_persists():
    """pull() drives the full chain via the injected fake source + store."""
    store = _fresh_store()

    snapshots = services.pull(
        since=date(2025, 1, 1),
        source=FakeSource(),
        store=store,
    )

    # Transactions supplied by the fake made it into the store.
    stored_txns = store.all_transactions()
    assert stored_txns, "expected the fake's canned transactions to be stored"
    assert {t.hash for t in stored_txns} == {"h-buy", "h-sell", "h-div"}

    # Snapshots were produced — both the return value and what the store holds.
    assert isinstance(snapshots, list)
    assert all(isinstance(s, MonthlySnapshot) for s in snapshots)
    assert snapshots, "expected month-end snapshots to be reconstructed"
    assert store.all_snapshots(), "expected snapshots persisted to the store"

    # Sync state recorded as complete (observed directly from the table).
    row = store._conn.execute(
        "SELECT status FROM sync_state WHERE id = 1"
    ).fetchone()
    assert row is not None
    assert row["status"] == "complete"


def test_pull_respects_since_filter():
    """The ``since`` date is threaded through to the source's filter."""
    store = _fresh_store()

    services.pull(since=date(2025, 10, 10), source=FakeSource(), store=store)

    hashes = {t.hash for t in store.all_transactions()}
    # h-buy is dated 2025-10-01, before the cutoff, so it is excluded.
    assert "h-buy" not in hashes
    assert {"h-sell", "h-div"} <= hashes


def test_reconstruct_rebuilds_snapshots_from_stored_data():
    """reconstruct() runs the deterministic tail against an existing store."""
    store = _fresh_store()
    services.pull(since=date(2025, 1, 1), source=FakeSource(), store=store)

    snapshots = services.reconstruct(store=store)

    assert isinstance(snapshots, list)
    assert snapshots, "expected reconstruct to return snapshots"
    assert all(isinstance(s, MonthlySnapshot) for s in snapshots)


def test_report_renders_non_empty_text_for_stored_data():
    """report() renders stored summary + snapshots as a non-empty string."""
    store = _fresh_store()
    services.pull(since=date(2025, 1, 1), source=FakeSource(), store=store)

    text = services.report(store)

    assert isinstance(text, str)
    assert text.strip(), "expected a non-empty report"
