"""``reconstruct`` command — rebuild snapshots from stored data (no network).

Scripts layer: parse arguments, delegate to ``services.reconstruct``, print the
result. No business logic lives here — the CLI is only allowed to print.
"""

from __future__ import annotations

from datetime import date

from rhtracker import services


def add_parser(subparsers):
    """Register the ``reconstruct`` subparser and wire it to :func:`run`."""
    parser = subparsers.add_parser(
        "reconstruct",
        help="rebuild month-end snapshots from already-stored transactions and "
        "prices (no network)",
    )
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="first month-end to reconstruct (YYYY-MM-DD). Defaults to the "
        "backfill start recorded by the last `pull`.",
    )
    parser.set_defaults(func=run)
    return parser


def run(args):
    """Rebuild snapshots and print how many month-end rows were produced."""
    snapshots = services.reconstruct(
        since=getattr(args, "since", None),
        store=getattr(args, "store", None),
    )
    print(f"Reconstructed {len(snapshots)} month-end rows.")
    return 0
