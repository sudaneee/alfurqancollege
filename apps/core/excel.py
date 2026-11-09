"""Excel helpers (openpyxl) shared by templates, exports and imports."""
import datetime
import io
from decimal import Decimal

from django.http import HttpResponse
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

BRAND_BLUE = "0054A8"
HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=BRAND_BLUE)
NOTE_FONT = Font(italic=True, color="666666", size=9)


class ExcelError(Exception):
    pass


def normalise_header(text):
    return "".join(ch if ch.isalnum() else "_" for ch in str(text or "").strip().lower()).strip("_")


def build_workbook(headers, rows=(), title="Sheet1", notes=None, choices=None, widths=None, locked_columns=None):
    """Create a styled workbook.

    headers: list of column labels
    rows: iterable of row value lists
    notes: optional list of instruction strings placed on a second sheet
    choices: {column_index: [allowed values]} adds in-cell dropdown validation
    """
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(list(headers))
    for idx, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=idx)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for row in rows:
        ws.append([_cell_value(v) for v in row])
    for idx, header in enumerate(headers, start=1):
        width = (widths or {}).get(idx - 1) or max(12, min(45, len(str(header)) + 6))
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"
    if choices:
        for col_idx, values in choices.items():
            joined = ",".join(str(v) for v in values)
            if len(joined) > 250:
                continue
            dv = DataValidation(type="list", formula1=f'"{joined}"', allow_blank=True)
            ws.add_data_validation(dv)
            letter = get_column_letter(col_idx + 1)
            dv.add(f"{letter}2:{letter}2000")
    if notes:
        ns = wb.create_sheet("Instructions")
        ns.column_dimensions["A"].width = 110
        ns.append(["Instructions"])
        ns["A1"].font = Font(bold=True, size=13, color=BRAND_BLUE)
        for n in notes:
            ns.append([n])
    return wb


def _cell_value(v):
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime.datetime):
        if v.tzinfo is not None:
            from django.utils import timezone
            v = timezone.localtime(v).replace(tzinfo=None)
        return v
    if isinstance(v, datetime.date):
        return v
    return str(v)


def workbook_response(wb, filename):
    buf = io.BytesIO()
    wb.save(buf)
    resp = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def export_response(filename, headers, rows, title="Export"):
    return workbook_response(build_workbook(headers, rows, title=title), filename)


def read_rows(uploaded_file, max_rows=5000):
    """Read the first sheet into a list of dicts keyed by normalised header.

    Returns (headers, rows) where each row is {"_row": excel_row_number, key: value}.
    """
    name = getattr(uploaded_file, "name", "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise ExcelError("Please upload an Excel file in .xlsx format (use the template provided).")
    try:
        wb = load_workbook(uploaded_file, read_only=True, data_only=True)
    except Exception as exc:  # corrupt or not an Excel file
        raise ExcelError("The file could not be read as an Excel workbook.") from exc
    ws = wb.worksheets[0]
    it = ws.iter_rows(values_only=True)
    try:
        header_row = next(it)
    except StopIteration:
        raise ExcelError("The spreadsheet is empty.")
    headers = [normalise_header(h) for h in header_row]
    rows = []
    for idx, values in enumerate(it, start=2):
        if values is None or all(v is None or str(v).strip() == "" for v in values):
            continue
        row = {"_row": idx}
        for key, value in zip(headers, values):
            if not key:
                continue
            if isinstance(value, str):
                value = value.strip()
            elif isinstance(value, float) and value.is_integer():
                value = int(value)
            elif isinstance(value, (datetime.datetime, datetime.date)):
                value = value.isoformat()[:10]
            row[key] = value
        rows.append(row)
        if len(rows) > max_rows:
            raise ExcelError(f"The file has more than {max_rows} rows. Please split it into smaller files.")
    wb.close()
    return headers, rows
