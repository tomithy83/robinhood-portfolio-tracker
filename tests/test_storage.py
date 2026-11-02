"""Unit test for SqliteStore (task 2.1).

Covers an in-memory save + read-back of a Transaction, the expected
bronze/silver/gold tables existing, a quote-containing value round-tripping
without a SQL error (confirming parameterization), and Property 8 (transaction
storage is idempotent on identity).
"""

from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from rhtracker.model import Transaction
from rhtracker.storage import SqliteStore


def _store() -> SqliteStore:
    store = SqliteStore(":memory:")
    store.init_schema()
    return store


def _txn(hash="h1", ref="ref-1", asset="AAPL", amount=-100.0, quantity=1.0):
    return Transaction(
        hash=hash,
        transaction_date=date(2025, 10, 1),
        transaction_type="buy",
        asset=asset,
        amount=amount,
        quantity=quantity,
        price=100.0,
        status="filled",
        reference_id=ref,
    )


def test_save_and_read_back_transaction():
    store = _store()
    inserted = store.save_transactions([_txn()])
    assert inserted == 1

    rows = store.all_transactions()
    assert len(rows) == 1
    got = rows[0]
    assert got.hash == "h1"
    assert got.transaction_date == date(2025, 10, 1)
    assert got.transaction_type == "buy"
    assert got.asset == "AAPL"
    assert got.amount == -100.0
    assert got.quantity == 1.0
    assert got.reference_id == "ref-1"


def test_bronze_silver_gold_tables_exist():
    store = _store()
    rows = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    # bronze, silver, gold, plus sync bookkeeping
    expected = {
        "raw_events",
        "transactions",
        "positions_daily",
        "price_cache",
        "monthly_tracking",
        "sync_state",
    }
    assert expected <= names


def test_quote_value_round_trips_without_sql_error():
    """A single-quote in a value must survive as data, proving parameterization."""
    store = _store()
    tricky = "O'Reilly'); DROP TABLE transactions;--"
    store.save_transactions([_txn(hash="h-quote", ref="ref'quote", asset=tricky)])

    rows = store.all_transactions()
    assert len(rows) == 1
    assert rows[0].asset == tricky
    assert rows[0].reference_id == "ref'quote"
    # The transactions table must still exist (no injection executed).
    tables = {
        r["name"]
        for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "transactions" in tables


def test_duplicate_reference_id_is_rejected():
    store = _store()
    assert store.save_transactions([_txn(hash="a", ref="dup")]) == 1
    # Same reference_id, different hash -> rejected on reference_id.
    assert store.save_transactions([_txn(hash="b", ref="dup")]) == 0
    assert len(store.all_transactions()) == 1


def test_duplicate_hash_is_rejected():
    store = _store()
    assert store.save_transactions([_txn(hash="same", ref="r1")]) == 1
    # Same hash, different reference_id -> rejected on the primary key.
    assert store.save_transactions([_txn(hash="same", ref="r2")]) == 0
    assert len(store.all_transactions()) == 1


@settings(max_examples=150)
@given(
    identities=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=12),  # hash
            st.text(min_size=1, max_size=12),  # reference_id
        ),
        min_size=1,
        max_size=20,
    )
)
def test_storage_is_idempotent_on_identity(identities):
    """Property 8: Transaction storage is idempotent on identity.

    Feature: rhtracker-refactor, Property 8: For any transaction, saving it a
    second time with the same reference_id (or the same transaction_hash) leaves
    the stored transaction set unchanged, while distinct transactions each store
    exactly once.

    Validates: Requirements 4.1, 4.2, 4.3, 6.4
    """
    store = _store()

    # The set of transactions that *should* persist. Dedup checks reference_id
    # first, then the transaction_hash primary key. A reference_id only counts
    # as "seen" once a row carrying it actually persists — a row rejected on its
    # hash never records its reference_id (mirrors the storage behavior).
    stored_refs: set[str] = set()
    stored_hashes: set[str] = set()
    expected_hashes: set[str] = set()
    for h, ref in identities:
        if ref in stored_refs:
            continue
        if h in stored_hashes:
            continue
        stored_refs.add(ref)
        stored_hashes.add(h)
        expected_hashes.add(h)

    txns = [_txn(hash=h, ref=ref) for h, ref in identities]

    # First save establishes the stored set.
    store.save_transactions(txns)
    after_first = {t.hash for t in store.all_transactions()}
    assert after_first == expected_hashes

    # Saving the exact same batch again must change nothing.
    reinserted = store.save_transactions(txns)
    assert reinserted == 0
    after_second = {t.hash for t in store.all_transactions()}
    assert after_second == after_first
