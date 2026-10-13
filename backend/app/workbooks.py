"""Deterministic Excel reports. Model text is never executed as a formula."""

import io
import json
import math
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

NUMERIC_TYPES = {
    "decimal",
    "numeric",
    "money",
    "smallmoney",
    "number",
    "integer",
    "float",
    "real",
    "int",
    "bigint",
    "smallint",
    "tinyint",
}


class ReportDataError(ValueError):
    """A safe, user-facing error in an analysis plan or its result shape."""


def number(value, numeric=False):
    if value is None or isinstance(value, bool) or (isinstance(value, str) and not numeric):
        return None
    try:
        result = Decimal(str(value))
        return float(result) if result.is_finite() and math.isfinite(float(result)) else None
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        return None


def analysis_data(snapshot):
    provenance = json.loads(snapshot["provenance_json"])
    return [
        {**provenance, "rows": json.loads(snapshot["rows_json"]), "options": provenance.get("analysis", {})},
        *provenance.get("analyses", []),
    ]


def excel_number(value, numeric=False):
    converted = number(value, numeric)
    if converted is None:
        return None
    # Avoid Decimal.normalize(), which can round using the active decimal context.
    digits = "".join(str(d) for d in Decimal(str(value)).as_tuple().digits).rstrip("0")
    return converted if len(digits) <= 15 else None


def excel_report(report, snapshot):
    """Return a complete workbook in memory, so cancellation cannot publish a partial file."""
    output = io.BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    book.set_properties({"title": report["title"], "author": "Duka", "comments": "Immutable reporting snapshot"})
    title = book.add_format(
        {"font_size": 16, "bold": True, "font_color": "#205C49", "text_wrap": True, "valign": "vcenter"}
    )
    heading = book.add_format({"bold": True, "font_color": "#205C49", "font_size": 12})
    text = book.add_format({"text_wrap": True, "valign": "top", "font_color": "#33483F"})
    numeric = book.add_format(
        {"num_format": '#,##0.00;[Red](#,##0.00);"—"', "font_color": "#33483F", "align": "right", "valign": "vcenter"}
    )
    percent = book.add_format({"num_format": '0.0%;[Red](0.0%);"—"', "align": "right", "valign": "vcenter"})
    table_label = book.add_format({"text_wrap": True, "valign": "vcenter", "font_color": "#33483F"})
    table_header = book.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#205C49",
            "text_wrap": True,
            "align": "center",
            "valign": "vcenter",
        }
    )
    date_format = book.add_format({"num_format": "yyyy-mm-dd"})
    summary = book.add_worksheet("Overview")
    summary.hide_gridlines(2)
    summary.set_column("A:A", 3)
    summary.set_column("B:B", 40)
    summary.set_column("C:C", 22)
    summary.set_column("D:H", 13)
    summary.freeze_panes(4, 0)
    summary.merge_range("B2:H3", report["title"], title)
    summary.set_row(1, 36)
    summary.set_row(2, 36)
    doc = json.loads(report["content_json"])
    cursor = 4

    def paragraph(value, style=text):
        nonlocal cursor
        # Preserve long narratives without exceeding Excel's maximum row height.
        remaining = str(value)
        while remaining:
            cut = min(len(remaining), 1000)
            if cut < len(remaining):
                boundary = remaining.rfind(" ", 0, cut)
                cut = boundary if boundary > 700 else cut
            chunk, remaining = remaining[:cut], remaining[cut:].lstrip()
            summary.merge_range(cursor, 1, cursor, 7, chunk, style)
            summary.set_row(cursor, max(24, min(300, 18 * (len(chunk) // 90 + chunk.count("\n") + 1))))
            cursor += 2

    paragraph(doc["summary"])
    paragraph("Snapshot captured: " + snapshot["captured_at"])
    paragraph("Calculated results", heading)
    chart_row = 3
    for index, dataset in enumerate(analysis_data(snapshot)):
        rows = dataset["rows"]
        options = dataset.get("options", {})
        name = re.sub(r"[\[\]:*?/\\]", " ", options.get("name") or "Report data").strip(" '") or "Data"
        name = f"{index + 1} {name}"[:31]
        quoted_name = name.replace("'", "''")
        sheet = book.add_worksheet(name)
        sheet.hide_gridlines(2)
        sheet.set_tab_color("#205C49" if options.get("kind") != "data" else "#9AB583")
        fields = list(dict.fromkeys([c["name"] for c in dataset.get("columns", [])] + [k for row in rows for k in row]))
        types = {c["name"]: c.get("type", "").lower() for c in dataset.get("columns", [])}
        source = "Source: " + dataset.get("source", "Provided data")
        sheet.merge_range(0, 0, 1, max(2, min(len(fields) - 1, 7)), options.get("name") or "Report data", title)
        sheet.set_row(0, 28)
        sheet.set_row(1, 28)
        sheet.merge_range(2, 0, 2, max(2, min(len(fields) - 1, 7)), source, text)
        sheet.set_row(2, 30)
        sheet.freeze_panes(5, 0)
        sheet.repeat_rows(4)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        numeric_fields = {
            f for f in fields if types.get(f) in NUMERIC_TYPES or any(number(r.get(f)) is not None for r in rows)
        }
        # SQL SUM/COUNT metrics are additive across disjoint grouped result rows. Other columns require an explicit plan.
        inferred = [
            m["alias"] for m in dataset.get("query", {}).get("metrics", []) if m["function"] in ("sum", "count")
        ]
        if not dataset.get("query"):
            inferred = [
                f
                for f in fields
                if f in numeric_fields
                if re.search(r"revenue|sales|amount|cost|profit|quantity|total|vat|tax", f, re.I)
                and not re.search(r"(^id$|(^|_)id($|_)|identifier|price|rate|percent|margin)", f, re.I)
            ]
        measures = options.get("measures") or inferred
        if any(f not in numeric_fields for f in measures):
            raise ReportDataError("Report measures must refer to numeric result columns.")
        dimension = options.get("dimension")
        if dimension and dimension not in fields:
            raise ReportDataError("Report dimension is not a result column.")
        # Trend calculations require unique, chronological period labels; never silently sum duplicate periods.
        if options.get("kind") == "trend":
            if not dimension or types.get(dimension) not in (
                "date",
                "datetime",
                "datetime2",
                "smalldatetime",
                "datetimeoffset",
            ):
                raise ReportDataError("A trend requires a dated result dimension.")
            periods = [r.get(dimension) for r in rows]
            if any(p is None for p in periods) or len(set(periods)) != len(periods):
                raise ReportDataError("Trend periods must be populated and unique. Aggregate by period first.")
            rows = sorted(rows, key=lambda r: r[dimension])
        extras = []
        if options.get("kind") in ("trend", "comparison"):
            for measure in measures:
                extras += [(f"{measure}: change", "change", measure), (f"{measure}: growth %", "growth", measure)]
                if options.get("kind") == "trend":
                    extras += [(f"{measure}: 3-period average", "average", measure)]
        elif options.get("kind") == "breakdown":
            extras += [(f"{m}: share %", "share", m) for m in measures]
        revenue, cost = options.get("revenue_column"), options.get("cost_column")
        if revenue or cost:
            if not revenue or not cost or revenue not in numeric_fields or cost not in numeric_fields:
                raise ReportDataError("Profit and margin require matching revenue and cost columns.")
            extras += [("Profit (revenue minus cost)", "profit", revenue), ("Margin %", "margin", revenue)]
        table_fields = fields + [x[0] for x in extras]
        if len(set(table_fields)) != len(table_fields):
            raise ReportDataError("Report column labels must be unique.")
        values = {f: [excel_number(r.get(f), True) for r in rows] for f in numeric_fields}
        for col, field in enumerate(fields):
            width = min(46, max(18, len(field) + 2, max((len(str(r.get(field) or "")) for r in rows), default=0) + 2))
            sheet.set_column(col, col, width, numeric if field in numeric_fields else text)
        for col in range(len(fields), len(table_fields)):
            sheet.set_column(col, col, min(42, max(22, len(table_fields[col]) + 2)))
        first, last = 6, len(rows) + 5
        for row_index, row in enumerate(rows, 5):
            sheet.set_row(row_index, 24)
            excel_row = row_index + 1
            for col, field in enumerate(fields):
                value = row.get(field)
                if value is None:
                    sheet.write_blank(row_index, col, None)
                elif field in numeric_fields and number(value, True) is not None:
                    converted = number(value, True)
                    # Excel stores at most 15 significant decimal digits. Keep exact high-precision source values as text.
                    if excel_number(value, True) is None:
                        sheet.write_string(row_index, col, str(value), text)
                        values[field][row_index - 5] = None
                    else:
                        sheet.write_number(row_index, col, converted, numeric)
                elif types.get(field) in ("date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"):
                    try:
                        sheet.write_datetime(
                            row_index, col, datetime.fromisoformat(str(value)).replace(tzinfo=None), date_format
                        )
                    except ValueError:
                        sheet.write_string(row_index, col, str(value), text)
                elif isinstance(value, bool):
                    sheet.write_boolean(row_index, col, value)
                else:
                    sheet.write_string(row_index, col, str(value), text)
            for offset, (_, operation, measure) in enumerate(extras):
                col = len(fields) + offset
                letter = xl_col_to_name(fields.index(measure))
                cell, previous = f"{letter}{excel_row}", f"{letter}{excel_row - 1}"
                current = values[measure][row_index - 5]
                prior = values[measure][row_index - 6] if row_index > 5 else None
                fmt, cached = numeric, "n.a."
                if operation in ("change", "growth"):
                    if row_index == 5:
                        sheet.write_string(row_index, col, "n.a.")
                        continue
                    allowed = current is not None and prior is not None and (operation == "change" or prior != 0)
                    calculation = (
                        f"{cell}-{previous}" if operation == "change" else f"({cell}-{previous})/ABS({previous})"
                    )
                    guard = f"AND(ISNUMBER({cell}),ISNUMBER({previous})" + (
                        f",{previous}<>0)" if operation == "growth" else ")"
                    )
                    if allowed:
                        cached = current - prior if operation == "change" else (current - prior) / abs(prior)
                    fmt = percent if operation == "growth" else numeric
                elif operation == "average":
                    start = max(first, excel_row - 2)
                    count = excel_row - start + 1
                    interval = f"{letter}{start}:{cell}"
                    guard, calculation = f"COUNT({interval})={count}", f"AVERAGE({interval})"
                    window = values[measure][start - first : excel_row - first + 1]
                    if all(v is not None for v in window):
                        cached = sum(window) / count
                elif operation == "share":
                    interval = f"${letter}${first}:${letter}${last}"
                    total = sum(v for v in values[measure] if v is not None)
                    guard, calculation = (
                        f"AND(ISNUMBER({cell}),COUNT({interval})={len(rows)},MIN({interval})>=0,SUM({interval})>0)",
                        f"{cell}/SUM({interval})",
                    )
                    if current is not None and all(v is not None and v >= 0 for v in values[measure]) and total > 0:
                        cached = current / total
                    fmt = percent
                else:
                    cost_cell = f"{xl_col_to_name(fields.index(cost))}{excel_row}"
                    expense = values[cost][row_index - 5]
                    calculation = f"{cell}-{cost_cell}" if operation == "profit" else f"({cell}-{cost_cell})/{cell}"
                    guard = f"AND(ISNUMBER({cell}),ISNUMBER({cost_cell})" + (
                        f",{cell}<>0)" if operation == "margin" else ")"
                    )
                    if current is not None and expense is not None and (operation == "profit" or current != 0):
                        cached = current - expense if operation == "profit" else (current - expense) / current
                    fmt = percent if operation == "margin" else numeric
                sheet.write_formula(row_index, col, f'=IF({guard},{calculation},"n.a.")', fmt, cached)
        if rows and fields:
            sheet.add_table(
                4,
                0,
                last - 1,
                len(table_fields) - 1,
                {
                    "name": f"ReportData{index + 1}",
                    "style": "Table Style Medium 4",
                    "columns": [{"header": f, "header_format": table_header} for f in table_fields],
                },
            )
        else:
            sheet.write(4, 0, "No rows match these filters.", text)
        for measure in measures:
            col = xl_col_to_name(fields.index(measure))
            interval = f"'{quoted_name}'!{col}{first}:{col}{last}"
            summary.write(cursor, 1, (options.get("name") or "Report data") + " — " + measure, table_label)
            summary.set_row(cursor, 30)
            vals = values[measure]
            complete = bool(rows) and all(v is not None for v in vals)
            # Missing or non-Excel-safe inputs remain unavailable instead of becoming understated totals.
            formula = f'=IF(COUNT({interval})={len(rows)},SUM({interval}),"n.a.")' if rows else '="n.a."'
            summary.write_formula(cursor, 2, formula, numeric, sum(vals) if complete else "n.a.")
            cursor += 1
        if rows and revenue and cost:
            rev_interval = f"'{quoted_name}'!{xl_col_to_name(fields.index(revenue))}{first}:{xl_col_to_name(fields.index(revenue))}{last}"
            cost_interval = f"'{quoted_name}'!{xl_col_to_name(fields.index(cost))}{first}:{xl_col_to_name(fields.index(cost))}{last}"
            valid = all(v is not None for v in values[revenue] + values[cost])
            rev_total = sum(v or 0 for v in values[revenue])
            profit = rev_total - sum(v or 0 for v in values[cost])
            for metric, calculation, cached, fmt in [
                ("Profit", f"SUM({rev_interval})-SUM({cost_interval})", profit, numeric),
                (
                    "Margin %",
                    f"(SUM({rev_interval})-SUM({cost_interval}))/SUM({rev_interval})",
                    profit / rev_total if rev_total else "n.a.",
                    percent,
                ),
            ]:
                guard = f"AND(COUNT({rev_interval})={len(rows)},COUNT({cost_interval})={len(rows)}" + (
                    f",SUM({rev_interval})<>0)" if metric == "Margin %" else ")"
                )
                summary.write(cursor, 1, (options.get("name") or "Report data") + " — " + metric, table_label)
                summary.write_formula(cursor, 2, f'=IF({guard},{calculation},"n.a.")', fmt, cached if valid else "n.a.")
                cursor += 1
        if dimension and measures and len(rows) > 1:
            chart = book.add_chart({"type": "line" if options.get("kind") == "trend" else "column"})
            # All rows are retained; charts use the first 40 categories for readability and say so when bounded.
            chart_last = min(last - 1, 44)
            for series_index, measure in enumerate(measures[:4]):
                chart.add_series(
                    {
                        "name": [name, 4, fields.index(measure)],
                        "categories": [name, 5, fields.index(dimension), chart_last, fields.index(dimension)],
                        "values": [name, 5, fields.index(measure), chart_last, fields.index(measure)],
                        "line": {"color": ["#205C49", "#91AC6B", "#6E8B9D", "#B29B74"][series_index], "width": 2},
                        "fill": {"color": ["#205C49", "#91AC6B", "#6E8B9D", "#B29B74"][series_index]},
                    }
                )
            chart.set_title(
                {"name": (options.get("name") or "Report data") + (" (first 40 categories)" if len(rows) > 40 else "")}
            )
            chart.set_legend({"position": "bottom"})
            chart.set_y_axis({"num_format": "#,##0.##"})
            if types.get(dimension) in ("date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"):
                chart.set_x_axis({"date_axis": True, "num_format": "yyyy-mm-dd", "num_font": {"rotation": -30}})
            chart.set_size({"width": 640, "height": 330})
            summary.insert_chart(chart_row, 9, chart)
            chart_row += 18
        note_row = last + 2
        notes = [
            f"Rows: {len(rows)}. Missing cells: {sum(v is None for r in rows for v in r.values())}.",
            "Numbers with more than 15 significant digits are kept as exact text; calculations depending on them are unavailable.",
            "Growth compares adjacent observed periods, using absolute previous value as denominator. Missing periods are not assumed to be zero."
            if options.get("kind") == "trend"
            else "Totals apply only to the additive measures selected for this result; ratios and identifiers must not be summed.",
            "Query and filters: " + json.dumps(dataset.get("query", dataset.get("parameters", {})), ensure_ascii=False),
            "Scope: " + dataset.get("scope", "Provided rows only."),
        ]
        for note in notes:
            sheet.merge_range(note_row, 0, note_row, max(2, min(len(table_fields) - 1, 7)), note, text)
            sheet.set_row(note_row, min(300, max(32, 16 * (len(note) // 90 + 1))))
            note_row += 1
        cursor += 1
    cursor += 1
    for metric in doc["metrics"]:
        paragraph(f"{metric['label']}: {metric['value']}\n{metric['explanation']}")
    for section in doc["sections"]:
        paragraph(section["heading"], heading)
        paragraph(section["body"])
    if doc["limitations"]:
        paragraph("Data limitations", heading)
        for limitation in doc["limitations"]:
            paragraph(limitation)
    summary.set_landscape()
    summary.fit_to_pages(1, 0)
    book.close()
    return output.getvalue()
