"""Tests for the per-user settings loader.

Exercises ``settings.json`` parsing, the missing-file defaults, and resilience
to malformed entries. Each test points the loader at a temp file via the
module-level ``_SETTINGS_PATH`` and clears the cache so nothing leaks between
tests (or from the developer's real ``settings.json``).
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from rhtracker import settings


@pytest.fixture
def write_settings(tmp_path, monkeypatch):
    """Return a helper that writes a settings dict and points the loader at it."""

    def _write(data):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(settings, "_SETTINGS_PATH", path)
        settings.reload()
        return path

    return _write


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Default every test to a non-existent settings file, so the developer's
    real settings.json never influences results. Individual tests opt into
    content via ``write_settings``."""
    monkeypatch.setattr(settings, "_SETTINGS_PATH", tmp_path / "nope.json")
    settings.reload()
    yield
    settings.reload()


def test_missing_file_yields_empty_defaults():
    assert settings.default_since() is None
    assert settings.classifier_rules() == []
    assert settings.splits() == []


def test_default_since_parses_iso_date(write_settings):
    write_settings({"default_since": "2024-03-15"})
    assert settings.default_since() == date(2024, 3, 15)


def test_default_since_null_is_none(write_settings):
    write_settings({"default_since": None})
    assert settings.default_since() is None


def test_bad_default_since_is_ignored(write_settings):
    write_settings({"default_since": "not-a-date"})
    assert settings.default_since() is None


def test_classifier_rules_loaded_and_matched(write_settings):
    write_settings({
        "classifiers": [
            {"feed": "received", "direction": "debit",
             "keywords": ["Honda"], "type": "auto_loan_payment"},
        ]
    })
    rules = settings.classifier_rules()
    assert len(rules) == 1
    # keywords are lowercased so matching is case-insensitive
    assert settings.classify("received", "debit", "HONDA PMT") == "auto_loan_payment"
    assert settings.classify("received", "debit", "landlord") is None
    assert settings.classify("card", "debit", "HONDA PMT") is None  # wrong feed


def test_malformed_classifier_is_skipped(write_settings):
    write_settings({
        "classifiers": [
            {"feed": "card", "direction": "debit"},                 # missing keys
            {"feed": "card", "direction": "debit",
             "keywords": ["x"], "type": "card_purchase"},           # valid
        ]
    })
    assert len(settings.classifier_rules()) == 1


def test_splits_loaded(write_settings):
    write_settings({
        "splits": [{"ticker": "ABC", "date": "2025-12-08", "factor": 0.2}]
    })
    entries = settings.splits()
    assert len(entries) == 1
    assert entries[0].ticker == "ABC"
    assert entries[0].effective_date == date(2025, 12, 8)
    assert entries[0].factor == 0.2


def test_malformed_split_is_skipped(write_settings):
    write_settings({
        "splits": [
            {"ticker": "ABC", "date": "bad-date", "factor": 0.2},    # bad date
            {"ticker": "XYZ", "date": "2025-01-01", "factor": 2.0},  # valid
        ]
    })
    entries = settings.splits()
    assert [e.ticker for e in entries] == ["XYZ"]
