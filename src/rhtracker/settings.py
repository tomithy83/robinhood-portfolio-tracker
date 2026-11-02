"""Per-user configuration loaded from ``settings.json`` at the repo root.

This is the single home for account-specific knobs that used to be hardcoded:

  * ``default_since`` — a default backfill start date (YYYY-MM-DD) used when the
    CLI is given no ``--since``. ``null``/absent means "always ask".
  * ``classifiers`` — keyword rules that label transfers and card transactions
    by payee (e.g. a specific loan servicer). Universal rules (payroll, refund,
    cashback, ATM, ...) stay in the source; these rules *add* to them.
  * ``splits`` — the manual stock-split table consumed during reconstruction.

The file is gitignored; ``settings.example.json`` is the committed template.
Everything is optional: with no ``settings.json`` the defaults are an empty
classifier/split set and no default start date. This is a library-layer module —
it imports only the standard library.

A classifier rule is a dict::

    {"feed": "received"|"card", "direction": "credit"|"debit",
     "keywords": ["honda"], "type": "auto_loan_payment"}

The first rule whose ``feed``/``direction`` match and one of whose lowercased
``keywords`` is a substring of the (lowercased) payee text wins.

A split entry is a dict ``{"ticker": "ABC", "date": "YYYY-MM-DD",
"factor": 0.2}`` (a 1-for-5 reverse split is 0.2; a 2-for-1 forward split 2.0).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("rhtracker.settings")

# Repo root is three parents up from this file: src/rhtracker/settings.py.
_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "settings.json"


@dataclass(frozen=True)
class ClassifierRule:
    """One payee-keyword rule. ``feed`` is 'received' or 'card'."""

    feed: str
    direction: str
    keywords: tuple[str, ...]
    type: str

    def matches(self, feed: str, direction: str, text: str) -> bool:
        if self.feed != feed or self.direction != direction:
            return False
        t = (text or "").lower()
        return any(k in t for k in self.keywords)


@dataclass(frozen=True)
class SplitEntry:
    ticker: str
    effective_date: date
    factor: float


def _load_raw(path: Path | None = None) -> dict:
    """Read and parse ``settings.json``; return ``{}`` if absent or unreadable.

    ``path`` defaults to the module-level ``_SETTINGS_PATH`` read at call time
    (not bound at definition), so tests can repoint it before a ``reload()``.
    """
    if path is None:
        path = _SETTINGS_PATH
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            log.warning("settings.json is not a JSON object — ignoring it")
            return {}
        return data
    except (OSError, ValueError) as e:
        log.warning(f"could not read settings.json ({e}) — using defaults")
        return {}


@lru_cache(maxsize=1)
def _settings() -> dict:
    return _load_raw()


def reload() -> None:
    """Drop the cached settings so the next access re-reads the file (tests)."""
    _settings.cache_clear()


def default_since() -> date | None:
    """The configured default backfill start date, or ``None`` if unset."""
    raw = _settings().get("default_since")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        log.warning(f"settings.default_since {raw!r} is not a valid YYYY-MM-DD date")
        return None


def classifier_rules() -> list[ClassifierRule]:
    """The configured payee-classifier rules (empty if none)."""
    rules: list[ClassifierRule] = []
    for entry in _settings().get("classifiers", []) or []:
        try:
            kws = tuple(str(k).lower() for k in entry["keywords"])
            rules.append(
                ClassifierRule(
                    feed=str(entry["feed"]),
                    direction=str(entry["direction"]),
                    keywords=kws,
                    type=str(entry["type"]),
                )
            )
        except (KeyError, TypeError) as e:
            log.warning(f"skipping malformed classifier rule {entry!r}: {e}")
    return rules


def classify(feed: str, direction: str, text: str) -> str | None:
    """Return the transaction type for the first matching rule, else ``None``."""
    for rule in classifier_rules():
        if rule.matches(feed, direction, text):
            return rule.type
    return None


def splits() -> list[SplitEntry]:
    """The configured manual split table (empty if none)."""
    out: list[SplitEntry] = []
    for entry in _settings().get("splits", []) or []:
        try:
            out.append(
                SplitEntry(
                    ticker=str(entry["ticker"]),
                    effective_date=date.fromisoformat(str(entry["date"])),
                    factor=float(entry["factor"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            log.warning(f"skipping malformed split entry {entry!r}: {e}")
    return out
