"""The ``export`` CLI command: write the data to a workbook."""

from __future__ import annotations

from rhtracker import services


def add_parser(subparsers):
    parser = subparsers.add_parser(
        "export",
        help="export all data to a workbook (xlsx now; gsheets later)",
    )
    parser.add_argument("--format", dest="fmt", default="xlsx",
                        choices=["xlsx", "gsheets"],
                        help="output backend (default: xlsx)")
    parser.add_argument("--out", dest="out", default=None,
                        help="destination path/id (default: timestamped file under output/)")
    parser.set_defaults(func=run)
    return parser


def run(args):
    location = services.export_workbook(
        fmt=args.fmt, destination=args.out, store=getattr(args, "store", None)
    )
    print(f"Exported workbook to: {location}")
    return 0
