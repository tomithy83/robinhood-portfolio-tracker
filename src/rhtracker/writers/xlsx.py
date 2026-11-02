"""XlsxWriter — writes an ExportWorkbook to a .xlsx file via openpyxl."""

from __future__ import annotations

from rhtracker.export import ExportWorkbook


class XlsxWriter:
    """Concrete WorkbookWriter backed by openpyxl."""

    def write(self, workbook: ExportWorkbook, destination: str) -> str:
        from openpyxl import Workbook
        from openpyxl.styles import Font
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        wb.remove(wb.active)  # drop the default empty sheet

        for sheet in workbook.sheets:
            ws = wb.create_sheet(title=sheet.name[:31])  # Excel 31-char limit
            ws.append(sheet.headers)
            for cell in ws[1]:
                cell.font = Font(bold=True)
            ws.freeze_panes = "A2"
            for row in sheet.rows:
                ws.append(list(row))
            # auto-ish column widths from header + sampled rows
            for ci, header in enumerate(sheet.headers, start=1):
                width = len(str(header))
                for row in sheet.rows[:200]:
                    if ci - 1 < len(row) and row[ci - 1] is not None:
                        width = max(width, len(str(row[ci - 1])))
                ws.column_dimensions[get_column_letter(ci)].width = min(width + 2, 60)

        wb.save(destination)
        return destination
