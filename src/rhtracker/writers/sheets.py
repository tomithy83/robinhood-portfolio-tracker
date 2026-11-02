"""SheetsWriter (future) — write an ExportWorkbook to a Google Sheet.

Not implemented yet. When added, it implements the same WorkbookWriter.write
contract (take an ExportWorkbook + a spreadsheet id/url) using the Google Sheets
API, with no change to rhtracker.export. This stub marks the seam so the CLI can
offer ``--format gsheets`` once credentials/flow are wired.
"""

from __future__ import annotations

from rhtracker.export import ExportWorkbook


class SheetsWriter:
    def write(self, workbook: ExportWorkbook, destination: str) -> str:
        raise NotImplementedError(
            "Google Sheets export is not implemented yet. It will consume the "
            "same ExportWorkbook as XlsxWriter via the Google Sheets API."
        )
