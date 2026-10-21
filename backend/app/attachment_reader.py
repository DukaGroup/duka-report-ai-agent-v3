"""Isolated, resource-limited extraction. Uploaded formulas/macros are never run."""

import csv
import io
import json
import math
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

MAX_ROWS, MAX_COLS, MAX_CELLS, MAX_TEXT = 10000, 100, 200000, 200000


def scalar(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 5000:
            raise ValueError("An uploaded cell exceeds the text limit.")
        return value
    return str(value)


def table(identifier, name, matrix):
    if not matrix:
        return None
    if len(matrix) > MAX_ROWS + 1 or max(map(len, matrix)) > MAX_COLS:
        raise ValueError("Uploaded tables support at most 10000 rows and 100 columns.")
    headers, used = [], set()
    for i, cell in enumerate(matrix[0]):
        base = re.sub(r"[\x00-\x1f]", " ", str(cell or f"Column {i + 1}"))[:90].strip() or f"Column {i + 1}"
        label, suffix = base, 1
        while label.casefold() in used:
            suffix += 1
            label = f"{base}_{suffix}"
        used.add(label.casefold())
        headers.append(label)
    rows = [
        {key: scalar(row[i]) if i < len(row) else None for i, key in enumerate(headers)}
        for row in matrix[1:]
        if any(v is not None and v != "" for v in row)
    ]
    columns = []
    for key in headers:
        values = [r[key] for r in rows if r[key] is not None and r[key] != ""]
        kind = (
            "number"
            if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
            else "text"
        )
        if (
            kind == "text"
            and values
            and all(isinstance(v, str) and re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", v.strip()) for v in values)
        ):
            kind = "decimal"
        if values and all(isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", v) for v in values):
            kind = "date"
        columns.append({"name": key, "type": kind})
    return {"id": identifier, "name": name, "columns": columns, "rows": rows, "row_count": len(rows)}


def guard_zip(path):
    with zipfile.ZipFile(path) as z:
        members = z.infolist()
        if len(members) > 3000 or sum(i.file_size for i in members) > 50 * 1024 * 1024:
            raise ValueError("The uploaded document is too large after decompression.")
        if any(i.flag_bits & 1 for i in members):
            raise ValueError("Encrypted uploads are not supported.")


def extract(path, extension):
    tables, parts, warnings, layout = [], [], [], {}
    if extension in (".xlsx", ".docx"):
        guard_zip(path)
    if extension == ".xlsx":
        from openpyxl import load_workbook
        from openpyxl.utils.cell import range_boundaries, get_column_letter

        wb = load_workbook(path, data_only=True, keep_links=False)
        if len(wb.worksheets) > 20:
            raise ValueError("Upload at most 20 worksheets per file.")
        cells = 0
        for si, ws in enumerate(wb.worksheets):
            if ws.max_row > MAX_ROWS + 50 or ws.max_column > MAX_COLS:
                raise ValueError("The uploaded worksheet exceeds the row or column limit.")
            cells += ws.max_row * ws.max_column
            if cells > MAX_CELLS:
                raise ValueError("The upload exceeds the cell limit.")
            parts.append(f"[{ws.title}]")
            for row in ws.iter_rows():
                content = " | ".join(str(scalar(c.value)) for c in row if c.value is not None)
                if content:
                    parts.append(content)
            found = False
            for ti, ref in enumerate(ws.tables.values()):
                a, b, c, d = range_boundaries(ref.ref)
                if ref.totalsRowCount:
                    d -= ref.totalsRowCount
                matrix = [
                    [cell.value for cell in row] for row in ws.iter_rows(min_row=b, max_row=d, min_col=a, max_col=c)
                ]
                item = table(f"s{si + 1}_t{ti + 1}", ws.title, matrix)
                if item:
                    tables.append(item)
                    found = True
                if not layout:
                    header = ws.cell(b, a)
                    color = header.fill.fgColor.rgb if header.fill.fgColor.type == "rgb" else None
                    font_color = (
                        header.font.color.rgb if header.font.color and header.font.color.type == "rgb" else None
                    )
                    chart = ws._charts[0] if ws._charts else next((c for s in wb.worksheets for c in s._charts), None)
                    chart_type = (
                        "line"
                        if chart and chart.__class__.__name__ == "LineChart"
                        else "bar"
                        if chart and getattr(chart, "type", None) == "bar"
                        else "column"
                    )
                    layout = {
                        "sheet_names": wb.sheetnames,
                        "font_name": header.font.name or "Calibri",
                        "header_color": "#" + color[-6:] if isinstance(color, str) else "#205C49",
                        "header_font_color": "#" + font_color[-6:] if isinstance(font_color, str) else "#FFFFFF",
                        "table_style": ref.tableStyleInfo.name if ref.tableStyleInfo else "Table Style Medium 4",
                        "column_widths": [
                            min(60, max(12, ws.column_dimensions[get_column_letter(i)].width or 18))
                            for i in range(a, c + 1)
                        ],
                        "header_row": min(15, max(4, b - 1)),
                        "chart_type": chart_type,
                        "columns": [str(v or "") for v in matrix[0]],
                        "landscape": ws.page_setup.orientation == "landscape",
                    }
            if not found:
                matrix = [[c.value for c in row] for row in ws.iter_rows()]
                first = next(
                    (
                        i
                        for i, row in enumerate(matrix[:30])
                        if sum(isinstance(v, str) and bool(v.strip()) for v in row) >= 2
                    ),
                    None,
                )
                if first is not None:
                    item = table(f"s{si + 1}", ws.title, matrix[first:])
                    if item:
                        tables.append(item)
                        if not layout:
                            header = ws.cell(first + 1, 1)
                            color = header.fill.fgColor.rgb if header.fill.fgColor.type == "rgb" else None
                            layout = {
                                "sheet_names": wb.sheetnames,
                                "font_name": header.font.name or "Calibri",
                                "header_color": "#" + color[-6:]
                                if isinstance(color, str) and color[-6:] != "000000"
                                else "#205C49",
                                "header_font_color": "#FFFFFF",
                                "header_row": min(15, max(4, first)),
                                "columns": [str(v or "") for v in matrix[first]],
                                "column_widths": [
                                    min(
                                        60,
                                        max(
                                            12,
                                            ws.column_dimensions[get_column_letter(i + 1)].width or 18,
                                        ),
                                    )
                                    for i in range(len(matrix[first]))
                                ],
                                "chart_type": "column",
                                "table_style": "Table Style Medium 4",
                            }
        from .reference_layout import workbook_layout
        layout.update(workbook_layout(wb))
        wb.close()
        warnings.append(
            "Only cached Excel formula results are read; formulas and macros are never executed. Missing caches remain missing data."
        )
    elif extension == ".csv":
        content = Path(path).read_text(encoding="utf-8-sig")
        dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t|")
        matrix = list(csv.reader(io.StringIO(content), dialect))
        if len(matrix) > MAX_ROWS + 1:
            raise ValueError("Uploaded tables support at most 10000 rows and 100 columns.")
        for row in matrix[1:]:
            for i, value in enumerate(row):
                if (
                    re.fullmatch(r"-?(?:0|[1-9]\d*)(?:\.\d+)?", value.strip())
                    and len(value.replace(".", "").replace("-", "")) <= 15
                ):
                    row[i] = float(value) if "." in value else int(value)
        item = table("csv", "CSV", matrix)
        if item:
            tables.append(item)
        warnings.append(
            "CSV numeric detection uses a decimal point; ambiguous comma-decimal amounts and leading-zero identifiers stay as text."
        )
    elif extension == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted uploads are not supported.")
        if len(reader.pages) > 100:
            raise ValueError("PDF uploads support at most 100 pages.")
        for i, page in enumerate(reader.pages):
            stream = page.get_contents()
            if stream is not None and len(stream.get_data()) > 5 * 1024 * 1024:
                raise ValueError("A PDF page exceeds the extraction limit.")
            parts.append(f"[Page {i + 1}]\n" + (page.extract_text(extraction_mode="layout") or ""))
        if not any(re.search(r"[A-Za-zÀ-ž]{3}", s.split("\n", 1)[-1]) for s in parts):
            raise ValueError("This PDF has no readable text. Upload a text-based PDF or Excel file.")
    elif extension == ".docx":
        from docx import Document

        doc = Document(path)
        parts = [p.text for p in doc.paragraphs if p.text]
        for i, t in enumerate(doc.tables):
            item = table(f"t{i + 1}", f"Table {i + 1}", [[c.text for c in row.cells] for row in t.rows])
            if item:
                tables.append(item)
    else:
        parts = [Path(path).read_text(encoding="utf-8-sig")]
    text = "\n".join(parts)
    # Excel tables are retained completely; text outside tables is a bounded
    # preview, explicitly marked rather than misrepresented as the full file.
    truncated = len(text) > MAX_TEXT
    if extension not in (".xlsx", ".csv") and truncated:
        raise ValueError("The uploaded document exceeds the text extraction limit.")
    return {
        "tables": tables,
        "text": text[:MAX_TEXT],
        "text_truncated": truncated,
        "warnings": warnings,
        "format": layout,
    }


def main():
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    resource.setrlimit(resource.RLIMIT_FSIZE, (12 * 1024 * 1024, 12 * 1024 * 1024))
    try:
        if len(sys.argv)>4 and sys.argv[4]=='--format-only':
            from openpyxl import load_workbook
            from .reference_layout import workbook_layout
            guard_zip(sys.argv[1])
            book = load_workbook(sys.argv[1],data_only=True,keep_links=False)
            try:
                if len(book.worksheets)>20 or sum(s.max_row*s.max_column for s in book)>MAX_CELLS or any(s.max_row>MAX_ROWS+50 or s.max_column>MAX_COLS for s in book):
                    raise ValueError("The reference exceeds parsing limits.")
                result = {"format":workbook_layout(book)}
            finally:
                book.close()
        else:
            result = extract(sys.argv[1], sys.argv[2])
        content = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(content.encode()) > 10 * 1024 * 1024:
            raise ValueError("The extracted upload exceeds the data limit.")
        Path(sys.argv[3]).write_text(content)
    except ValueError as exc:
        Path(sys.argv[3]).write_text(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception:
        Path(sys.argv[3]).write_text(
            json.dumps({"error": "The uploaded file could not be read. Check its format and contents."})
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
