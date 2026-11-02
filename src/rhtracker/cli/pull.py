"""``pull`` command — fetch Robinhood history and rebuild snapshots.

Scripts layer: parse arguments, delegate to ``services.pull``, print the
result. No business logic lives here — the CLI is only allowed to print.
"""

from __future__ import annotations

from datetime import date

from rhtracker import services, settings


def add_parser(subparsers):
    """Register the ``pull`` subparser and wire it to :func:`run`."""
    parser = subparsers.add_parser(
        "pull",
        help="fetch Robinhood history, store it, and rebuild month-end snapshots",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="earliest transaction date to fetch / first month-end to "
        "reconstruct (YYYY-MM-DD). Falls back to settings.default_since, then "
        "to an interactive prompt.",
    )
    parser.set_defaults(func=run)
    return parser


def _prompt_for_since() -> date:
    """Interactively ask for the backfill start date until a valid ISO date is
    entered. Raises SystemExit if there is no interactive terminal."""
    import sys

    if not sys.stdin or not sys.stdin.isatty():
        raise SystemExit(
            "error: --since YYYY-MM-DD is required (no terminal available to "
            "prompt). Example: pull --since 2025-10-01"
        )
    while True:
        raw = input("Backfill start date (YYYY-MM-DD): ").strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            print(f"  '{raw}' is not a valid YYYY-MM-DD date — try again.")


def run(args):
    """Run a full pull and print how many month-end rows were produced.

    Resolve the backfill start in order: ``--since`` flag, then
    ``settings.default_since``, then an interactive prompt.
    """
    since = args.since or settings.default_since() or _prompt_for_since()
    snapshots = services.pull(since=since)
    print(f"Pull complete: {len(snapshots)} month-end rows from {since.isoformat()}.")
    return 0
