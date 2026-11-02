"""Workbook writers: consume an ExportWorkbook and emit it to a backend.

base.WorkbookWriter is the seam (like sources.Source). XlsxWriter writes .xlsx
via openpyxl today; a SheetsWriter can be added later with no change to the
export data-building layer.
"""
