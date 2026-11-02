"""``pull`` command — fetch Robinhood history and rebuild snapshots.

Scripts layer: parse arguments, delegate to ``services.pull``, print the
result. No business logic lives here — the CLI is only allowed to print.
"""

from __future__ import annotations

from datetime import date

from rhtracker import services
from rhtracker.reconstruct import BACKFILL_START


def add_parser(subparsers):
    """Register the ``pull`` subparser and wire it to :func:`run`."""
    parser = subparsers.add_parser(
        "pull",
        help="fetch Robinhood history, store it, and rebuild month-end snapshots",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=BACKFILL_START,
        help="earliest transaction date to fetch (YYYY-MM-DD); "
        f"defaults to {BACKFILL_START.isoformat()}",
    )
    parser.set_defaults(func=run)
    return parser


def run(args):
    """Run a full pull and print how many month-end rows were produced."""
    snapshots = services.pull(since=args.since)
    print(f"Pull complete: {len(snapshots)} month-end rows.")
    return 0
