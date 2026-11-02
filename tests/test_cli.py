"""Unit tests for the CLI dispatcher (task 7.1).

These drive ``cli.main`` programmatically against an in-memory
:class:`SqliteStore` seeded through the services layer with a ``FakeSource`` —
no live Robinhood auth, no network. ``pull`` is intentionally not exercised live
here; it is already covered end to end via ``services`` + ``FakeSource`` in
``test_services.py``.

Validates: Requirements 5.1, 5.2, 6.4
"""

from datetime import date

from tests.fakes import FakeSource

from rhtracker import services
from rhtracker.cli import main as cli
from rhtracker.storage import SqliteStore


def _seeded_store() -> SqliteStore:
    """In-memory store populated with the fake source's canned data."""
    store = SqliteStore(":memory:")
    store.init_schema()
    services.pull(since=date(2025, 1, 1), source=FakeSource(), store=store)
    return store


def test_parser_lists_the_subcommands():
    """The dispatcher registers pull, reconstruct, report, and categories."""
    parser = cli.build_parser()
    # The subparsers action holds the registered command names.
    choices = {}
    for action in parser._actions:
        if hasattr(action, "choices") and action.choices:
            choices = action.choices
            break
    assert set(choices) == {"pull", "reconstruct", "report", "categories", "export"}


def test_reconstruct_command_exits_zero_and_reports_rows(capsys):
    """`reconstruct` runs against the seeded store, prints a count, exits 0."""
    store = _seeded_store()

    exit_code = cli.main(["reconstruct"], store=store)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Reconstructed" in out
    assert "month-end rows." in out


def test_report_command_exits_zero_and_prints_report(capsys):
    """`report` renders the seeded store's data and exits 0."""
    store = _seeded_store()

    exit_code = cli.main(["report"], store=store)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.strip(), "expected the report command to print non-empty text"


def test_report_command_runs_against_empty_store(capsys):
    """`report` on an empty store still succeeds (empty-state is fine)."""
    store = SqliteStore(":memory:")
    store.init_schema()

    exit_code = cli.main(["report"], store=store)

    assert exit_code == 0
