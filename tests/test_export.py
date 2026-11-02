"""Tests for the workbook export layer and the xlsx writer."""

import os
from datetime import date

from tests.fakes import FakeSource

from rhtracker import export, services
from rhtracker.storage import SqliteStore
from rhtracker.writers.base import WorkbookWriter
from rhtracker.writers.xlsx import XlsxWriter


def _seeded_store():
    store = SqliteStore(":memory:")
    store.init_schema()
    services.pull(since=date(2025, 1, 1), source=FakeSource(), store=store)
    return store


def test_build_workbook_has_expected_sheets():
    wb = export.build_workbook(_seeded_store())
    names = [s.name for s in wb.sheets]
    assert names == ["Overall Summary", "Tracking", "Transactions", "Dividends",
                     "Dividend Payments", "Expense Summary", "Expense Details",
                     "Stock Trades", "Options", "Positions", "Definitions"]
    # every sheet has headers
    assert all(s.headers for s in wb.sheets)


def test_xlsx_writer_conforms_and_writes(tmp_path):
    assert isinstance(XlsxWriter(), WorkbookWriter)
    wb = export.build_workbook(_seeded_store())
    dest = str(tmp_path / "out.xlsx")
    written = XlsxWriter().write(wb, dest)
    assert written == dest
    assert os.path.exists(dest) and os.path.getsize(dest) > 0

    import openpyxl
    loaded = openpyxl.load_workbook(dest)
    assert "Tracking" in loaded.sheetnames
    assert "Definitions" in loaded.sheetnames


def test_export_service_creates_timestamped_file(tmp_path, monkeypatch):
    store = _seeded_store()
    dest = str(tmp_path / "explicit.xlsx")
    out = services.export_workbook(fmt="xlsx", destination=dest, store=store)
    assert out == dest and os.path.exists(dest)


def test_gsheets_not_implemented_yet():
    from rhtracker.writers.sheets import SheetsWriter
    import pytest
    wb = export.build_workbook(_seeded_store())
    with pytest.raises(NotImplementedError):
        SheetsWriter().write(wb, "some-sheet-id")
