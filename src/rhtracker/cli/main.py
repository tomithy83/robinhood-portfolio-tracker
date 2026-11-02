"""Argparse dispatcher for the rhtracker CLI (task 7).

Builds the top-level parser, registers the three subcommands via their own
``add_parser`` functions, parses ``argv``, and dispatches to the selected
command's ``run(args)``. Each ``run`` returns an exit code (0 on success).

Scripts layer: imports from the command modules (siblings in ``cli``) and does
no business logic of its own — it only parses and dispatches.

The optional ``store`` parameter lets tests drive ``reconstruct``/``report``
against an in-memory :class:`~rhtracker.storage.SqliteStore` without touching
the default on-disk database. In normal use it is ``None`` and the services
layer falls back to its default store.
"""

from __future__ import annotations

import argparse

from rhtracker.cli import categories, export, pull, reconstruct, report


def build_parser() -> argparse.ArgumentParser:
    """Construct the top-level parser with the three subcommands registered."""
    parser = argparse.ArgumentParser(
        prog="rhtracker",
        description="Robinhood portfolio tracker — pull, reconstruct, and report.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    pull.add_parser(subparsers)
    reconstruct.add_parser(subparsers)
    report.add_parser(subparsers)
    categories.add_parser(subparsers)
    export.add_parser(subparsers)
    return parser


def main(argv=None, store=None) -> int:
    """Parse ``argv`` and dispatch to the selected command.

    Returns the command's exit code (0 on success). ``store`` is an optional
    injected :class:`SqliteStore`, threaded onto the parsed args for commands
    that read from storage (used by tests).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    args.store = store
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
