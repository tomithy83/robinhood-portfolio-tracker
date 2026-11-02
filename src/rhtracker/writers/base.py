"""The WorkbookWriter contract."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from rhtracker.export import ExportWorkbook


@runtime_checkable
class WorkbookWriter(Protocol):
    """Writes an ExportWorkbook to a destination (file path, sheet id, ...).

    Implementations return the concrete location written (e.g. the file path or
    spreadsheet URL) so callers can report it.
    """

    def write(self, workbook: ExportWorkbook, destination: str) -> str:
        ...
