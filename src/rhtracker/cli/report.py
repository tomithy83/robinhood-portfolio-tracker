"""``report`` command — render the stored snapshots as text.

Scripts layer: parse arguments, delegate to ``services.report``, print the
returned string. No business logic lives here — the CLI is only allowed to
print.
"""

from __future__ import annotations

from rhtracker import services


def add_parser(subparsers):
    """Register the ``report`` subparser and wire it to :func:`run`."""
    parser = subparsers.add_parser(
        "report",
        help="render the stored transaction summary and month-end snapshots",
    )
    parser.set_defaults(func=run)
    return parser


def run(args):
    """Render the stored data and print the report."""
    text = services.report(store=getattr(args, "store", None))
    print(text)
    return 0
