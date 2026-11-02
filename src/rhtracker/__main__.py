"""Entry point so ``python -m rhtracker`` works.

The CLI dispatcher is added in a later task; for now this module simply wires
``__main__`` to it when it exists, keeping the package runnable from source.
"""


def main(argv=None):
    from rhtracker.cli.main import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
