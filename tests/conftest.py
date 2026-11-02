"""Pytest configuration.

Puts ``src/`` on ``sys.path`` so the ``rhtracker`` package is importable when
running from source, without any pip install step. This mirrors the
run-from-source convention (``python -m rhtracker`` with ``src`` on the path).
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
