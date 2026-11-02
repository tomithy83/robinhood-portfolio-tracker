"""The ``categories`` CLI command.

Scripts layer: parse args, delegate to services.category_report, print.
"""

from __future__ import annotations

from rhtracker import services


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "categories",
        help="render category tables: dividends, expenses, fees, stock trades",
    )
    parser.set_defaults(func=run)
    return parser


def run(args):
    text = services.category_report(store=getattr(args, "store", None))
    print(text)
    return 0
