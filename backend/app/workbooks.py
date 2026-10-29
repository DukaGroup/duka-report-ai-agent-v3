"""Deterministic Excel reports. Model text is never executed as a formula."""

import io
import hashlib
import json
from itertools import chain
import math
import re
import zipfile
from xml.etree import ElementTree
from datetime import datetime
from decimal import Decimal, InvalidOperation

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name
from .workbook_locale import presentation
from .currencies import BASE_CURRENCY, currency_fields, display_currency
from .report_exports import public_snapshot

WORKBOOK_VERSION = "3"


def current_workbook(path):
    """Older exports are rebuilt from their saved snapshots, without model calls."""
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("docProps/custom.xml")
            if info.file_size > 65536:
                return False
            properties = ElementTree.fromstring(archive.read(info))
        return any(
            prop.get("name") == "DukaWorkbookVersion" and len(prop) == 1 and prop[0].text == WORKBOOK_VERSION
            for prop in properties
        )
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError):
        return False

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
    snapshot = public_snapshot(snapshot)
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


def excel_report(report, snapshot, layout=None, checks=None):
    """Return a complete workbook in memory, so cancellation cannot publish a partial file."""
    public = public_snapshot(snapshot)
    if public is not snapshot:
        from .balance_workbook import balance_contract
        balance_contract(snapshot)
    snapshot = public
    doc = json.loads(report["content_json"])
    language, labels, sheet_labels = presentation(doc)
    reference = json.loads(snapshot["provenance_json"]).get("format_reference", {})
    font_name = str(reference.get("font_name") or "Calibri")[:80]
    header_color = reference.get("header_color", "#205C49")
    header_font_color = reference.get("header_font_color", "#FFFFFF")
    header_row = int(reference.get("header_row", 4))
    first_data = header_row + 1
    table_style = reference.get("table_style", "Table Style Medium 4")
    table_style = re.sub(r"TableStyle(Medium|Light|Dark)([0-9]+)", r"Table Style \1 \2", table_style)
    if not re.fullmatch(r"Table Style (?:Medium|Light|Dark) [0-9]{1,2}", table_style):
        table_style = "Table Style Medium 4"
    na = labels["not_available"].replace('"', '""')
    output = io.BytesIO()
    book = xlsxwriter.Workbook(output, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False})
    book.set_properties({"title": doc["title"], "author": "Duka", "comments": labels["snapshot_comment"]})
    book.set_custom_property("DukaWorkbookVersion", WORKBOOK_VERSION)
    script = (doc.get("workbook") or {}).get("python_script")
    if script:
        book.set_custom_property("DukaScriptSHA256", hashlib.sha256(script.encode()).hexdigest())
    if json.loads(snapshot["provenance_json"]).get("reconciliation"):
        from .balance_workbook import render_balance
        render_balance(book, snapshot, labels)
    if layout is not None:
        from .layout_renderer import render_layout

        verified = render_layout(book, doc, snapshot, layout, labels)
        if checks is not None:
            checks.extend(verified)
    title = book.add_format(
        {
            "font_size": 16,
            "font_name": font_name,
            "bold": True,
            "font_color": header_color,
            "text_wrap": True,
            "valign": "vcenter",
        }
    )
    heading = book.add_format({"bold": True, "font_color": header_color, "font_size": 12, "font_name": font_name})
    text = book.add_format({"text_wrap": True, "valign": "top", "font_color": "#33483F", "font_name": font_name})
    numeric = book.add_format(
        {
            "font_name": font_name,
            "num_format": '#,##0.00;[Red](#,##0.00);"—"',
            "font_color": "#33483F",
            "align": "right",
            "valign": "vcenter",
        }
    )
    percent = book.add_format(
        {"font_name": font_name, "num_format": '0.0%;[Red](0.0%);"—"', "align": "right", "valign": "vcenter"}
    )
    table_label = book.add_format({"text_wrap": True, "valign": "vcenter", "font_color": "#33483F"})
    table_header = book.add_format(
        {
            "bold": True,
            "font_color": header_font_color,
            "bg_color": header_color,
            "font_name": font_name,
            "text_wrap": True,
            "align": "center",
            "valign": "vcenter",
        }
    )
    date_format = book.add_format({"num_format": "yyyy-mm-dd", "font_name": font_name})
    summary = book.add_worksheet(re.sub(r"[\[\]:*?/\\]", " ", labels["scope"] if layout is not None else labels["overview"]).strip(" '")[:31] or "0")
    summary.hide_gridlines(2)
    summary.set_column("A:A", 3)
    summary.set_column("B:B", 40)
    summary.set_column("C:C", 22)
    summary.set_column("D:H", 13)
    summary.freeze_panes(4, 0)
    summary.merge_range("B2:H3", doc["title"], title)
    summary.set_row(1, 36)
    summary.set_row(2, 36)
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

    if layout is None:
        paragraph(doc["summary"])
    paragraph(labels["snapshot_captured"] + ": " + snapshot["captured_at"])
    paragraph(labels["base_currency"] + ": " + BASE_CURRENCY["code"])
    paragraph(labels["calculated_results"], heading)
    chart_row = 3
    for index, dataset in enumerate(analysis_data(snapshot)):
        rows = dataset["rows"]
        options = dataset.get("options", {})
        if layout is not None:
            dimension = options.get("dimension")
            if options.get("kind") == "trend" and dimension and all(r.get(dimension) is not None for r in rows):
                rows = sorted(rows, key=lambda r: r[dimension])
            options = {**options, "kind": "data", "dimension": None, "revenue_column": None, "cost_column": None}
        translated = sheet_labels.get(index, {})
        display_name = translated.get("name") or options.get("name") or labels["report_data"]
        column_labels = {c["column"]: c["label"] for c in translated.get("columns", [])}

        def display(field):
            return column_labels.get(field, field)

        name = re.sub(r"[\[\]:*?/\\]", " ", display_name).strip(" '") or labels["data"]
        name = f"{index + 1} {name}"[:31]
        quoted_name = name.replace("'", "''")
        sheet = book.add_worksheet(name)
        sheet.hide_gridlines(2)
        sheet.set_tab_color("#205C49" if options.get("kind") != "data" else "#9AB583")
        fields = list(dict.fromkeys(chain((c["name"] for c in dataset.get("columns", [])), (k for row in rows for k in row))))
        types = {c["name"]: c.get("type", "").lower() for c in dataset.get("columns", [])}
        currency_columns = currency_fields(rows, dataset.get("columns", []), dataset.get("query"), column_labels)
        mixed_currencies = bool(currency_columns) and len({tuple(str(display_currency(r.get(f))) for f in sorted(currency_columns)) for r in rows}) > 1
        order = translated.get("column_order", [])
        if order:
            if len(order) != len(fields) or set(order) != set(fields):
                raise ReportDataError("Workbook column order does not match the source fields.")
            fields = order
        if doc.get("workbook") and set(fields) - column_labels.keys():
            raise ReportDataError("Workbook column translations are incomplete. Retry report generation.")
        if language != "en" and (not translated.get("scope") or not translated.get("query_explanation")):
            raise ReportDataError("Workbook scope and filter translations are incomplete. Retry report generation.")
        # Connection, database and table names are private infrastructure.
        # Uploaded files keep their own name; database data gets a business label.
        source_name = dataset.get("source", labels["provided_data"])
        if source_name in ("User-provided data", "Provided data"):
            source_name = labels["provided_data"]
        elif source_name == "Model calculation":
            source_name = labels["calculated_results"]
        elif any(dataset.get(key) for key in ("source_id", "database", "query", "query_key")):
            source_name = labels["system_data"]
        source = labels["source"] + ": " + source_name
        sheet.merge_range(0, 0, 1, max(2, min(len(fields) - 1, 7)), display_name, title)
        sheet.set_row(0, 28)
        sheet.set_row(1, 28)
        sheet.merge_range(2, 0, 2, max(2, min(len(fields) - 1, 7)), source, text)
        sheet.set_row(2, 30)
        sheet.freeze_panes(first_data, 0)
        sheet.set_row(header_row, 44)
        sheet.repeat_rows(header_row)
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
        measures = [] if layout is not None or mixed_currencies else options.get("measures") or inferred
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
                extras += [
                    (f"{display(measure)}: {labels['change']}", "change", measure),
                    (f"{display(measure)}: {labels['growth']}", "growth", measure),
                ]
                if options.get("kind") == "trend":
                    extras += [(f"{display(measure)}: {labels['average3']}", "average", measure)]
        elif options.get("kind") == "breakdown":
            extras += [(f"{display(m)}: {labels['share']}", "share", m) for m in measures]
        revenue, cost = options.get("revenue_column"), options.get("cost_column")
        if revenue or cost:
            if not revenue or not cost or revenue not in numeric_fields or cost not in numeric_fields:
                raise ReportDataError("Profit and margin require matching revenue and cost columns.")
            extras += [(labels["profit_detail"], "profit", revenue), (labels["margin"], "margin", revenue)]
        table_fields = [display(f) for f in fields] + [x[0] for x in extras]
        if len({f.casefold() for f in table_fields}) != len(table_fields):
            raise ReportDataError("Report column labels must be unique.")
        values = {f: [excel_number(r.get(f), True) for r in rows] for f in numeric_fields}
        for col, field in enumerate(fields):
            width = min(46, max(18, len(field) + 2, max((len(str(r.get(field) or "")) for r in rows), default=0) + 2))
            widths = reference.get("column_widths", [])
            if col < len(widths):
                width = widths[col]
            sheet.set_column(col, col, width, numeric if field in numeric_fields else text)
        for col in range(len(fields), len(table_fields)):
            sheet.set_column(col, col, min(42, max(22, len(table_fields[col]) + 2)))
        first, last = first_data + 1, len(rows) + first_data
        # Calculate full-column share denominators once. Repeating SUM/COUNT/MIN
        # over the entire dataset for each row becomes quadratic on large exports.
        share_stats = {}
        share_fields = list(dict.fromkeys(measure for _, operation, measure in extras if operation == "share"))
        helper_start = len(table_fields) + 2
        if share_fields:
            sheet.set_column(helper_start, helper_start + len(share_fields) * 3 - 1, None, None, {"hidden": True})
        for helper_index, measure in enumerate(share_fields):
            available = [v for v in values[measure] if v is not None]
            total, minimum = sum(available), min(available, default=0)
            letter = xl_col_to_name(fields.index(measure))
            interval = f"${letter}${first}:${letter}${last}"
            cells = []
            for offset, (operation, cached) in enumerate((("COUNT", len(available)), ("MIN", minimum), ("SUM", total))):
                column = helper_start + helper_index * 3 + offset
                sheet.write_formula(0, column, f"={operation}({interval})", numeric, cached)
                cells.append(f"${xl_col_to_name(column)}$1")
            share_stats[measure] = (total, len(available) == len(rows) and minimum >= 0, cells)
        for row_index, row in enumerate(rows, first_data):
            sheet.set_row(row_index, 24)
            excel_row = row_index + 1
            for col, field in enumerate(fields):
                value = row.get(field)
                if field in currency_columns:
                    value = display_currency(value)
                if value is None:
                    sheet.write_blank(row_index, col, None)
                elif field in numeric_fields and number(value, True) is not None:
                    converted = number(value, True)
                    # Excel stores at most 15 significant decimal digits. Keep exact high-precision source values as text.
                    if excel_number(value, True) is None:
                        sheet.write_string(row_index, col, str(value), text)
                        values[field][row_index - first_data] = None
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
                current = values[measure][row_index - first_data]
                prior = values[measure][row_index - first_data - 1] if row_index > first_data else None
                fmt, cached = numeric, labels["not_available"]
                if operation in ("change", "growth"):
                    if row_index == first_data:
                        sheet.write_string(row_index, col, labels["not_available"])
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
                    total, valid, (count_cell, min_cell, sum_cell) = share_stats[measure]
                    guard, calculation = (
                        f"AND(ISNUMBER({cell}),{count_cell}={len(rows)},{min_cell}>=0,{sum_cell}>0)",
                        f"{cell}/{sum_cell}",
                    )
                    if current is not None and valid and total > 0:
                        cached = current / total
                    fmt = percent
                else:
                    cost_cell = f"{xl_col_to_name(fields.index(cost))}{excel_row}"
                    expense = values[cost][row_index - first_data]
                    calculation = f"{cell}-{cost_cell}" if operation == "profit" else f"({cell}-{cost_cell})/{cell}"
                    guard = f"AND(ISNUMBER({cell}),ISNUMBER({cost_cell})" + (
                        f",{cell}<>0)" if operation == "margin" else ")"
                    )
                    if current is not None and expense is not None and (operation == "profit" or current != 0):
                        cached = current - expense if operation == "profit" else (current - expense) / current
                    fmt = percent if operation == "margin" else numeric
                sheet.write_formula(row_index, col, f'=IF({guard},{calculation},"{na}")', fmt, cached)
        if rows and fields:
            sheet.add_table(
                header_row,
                0,
                last - 1,
                len(table_fields) - 1,
                {
                    "name": f"T_{re.sub(r'[^A-Za-z0-9_]', '', labels['table_name'])[:50]}{index + 1}",
                    "style": table_style,
                    "columns": [{"header": f, "header_format": table_header} for f in table_fields],
                },
            )
        else:
            sheet.write(header_row, 0, labels["no_rows"], text)
        for measure in measures:
            col = xl_col_to_name(fields.index(measure))
            interval = f"'{quoted_name}'!{col}{first}:{col}{last}"
            summary.write(cursor, 1, (display_name) + " — " + display(measure), table_label)
            summary.set_row(cursor, 30)
            vals = values[measure]
            complete = bool(rows) and all(v is not None for v in vals)
            # Missing or non-Excel-safe inputs remain unavailable instead of becoming understated totals.
            formula = f'=IF(COUNT({interval})={len(rows)},SUM({interval}),"{na}")' if rows else f'="{na}"'
            summary.write_formula(cursor, 2, formula, numeric, sum(vals) if complete else labels["not_available"])
            cursor += 1
        if rows and revenue and cost:
            rev_interval = f"'{quoted_name}'!{xl_col_to_name(fields.index(revenue))}{first}:{xl_col_to_name(fields.index(revenue))}{last}"
            cost_interval = f"'{quoted_name}'!{xl_col_to_name(fields.index(cost))}{first}:{xl_col_to_name(fields.index(cost))}{last}"
            valid = all(v is not None for v in values[revenue] + values[cost])
            rev_total = sum(v or 0 for v in values[revenue])
            profit = rev_total - sum(v or 0 for v in values[cost])
            for metric, calculation, cached, fmt in [
                (labels["profit"], f"SUM({rev_interval})-SUM({cost_interval})", profit, numeric),
                (
                    labels["margin"],
                    f"(SUM({rev_interval})-SUM({cost_interval}))/SUM({rev_interval})",
                    profit / rev_total if rev_total else labels["not_available"],
                    percent,
                ),
            ]:
                guard = f"AND(COUNT({rev_interval})={len(rows)},COUNT({cost_interval})={len(rows)}" + (
                    f",SUM({rev_interval})<>0)" if metric == labels["margin"] else ")"
                )
                summary.write(cursor, 1, (display_name) + " — " + metric, table_label)
                summary.write_formula(
                    cursor, 2, f'=IF({guard},{calculation},"{na}")', fmt, cached if valid else labels["not_available"]
                )
                cursor += 1
        if dimension and measures and len(rows) > 1:
            chart_type = reference.get("chart_type") or ("line" if options.get("kind") == "trend" else "column")
            chart = book.add_chart({"type": chart_type})
            # All rows are retained; charts use the first 40 categories for readability and say so when bounded.
            chart_last = min(last - 1, first_data + 39)
            for series_index, measure in enumerate(measures[:4]):
                chart.add_series(
                    {
                        "name": [name, header_row, fields.index(measure)],
                        "categories": [name, first_data, fields.index(dimension), chart_last, fields.index(dimension)],
                        "values": [name, first_data, fields.index(measure), chart_last, fields.index(measure)],
                        "line": {"color": ["#205C49", "#91AC6B", "#6E8B9D", "#B29B74"][series_index], "width": 2},
                        "fill": {"color": ["#205C49", "#91AC6B", "#6E8B9D", "#B29B74"][series_index]},
                    }
                )
            chart.set_title({"name": (display_name) + (" (" + labels["chart_limit"] + ")" if len(rows) > 40 else "")})
            chart.set_legend({"position": "bottom"})
            chart.set_y_axis(
                {
                    "name": display(dimension) if chart_type == "bar" else ", ".join(display(m) for m in measures[:4]),
                    "num_format": "#,##0.##",
                }
            )
            chart.set_x_axis(
                {"name": ", ".join(display(m) for m in measures[:4]) if chart_type == "bar" else display(dimension)}
            )
            if types.get(dimension) in ("date", "datetime", "datetime2", "smalldatetime", "datetimeoffset"):
                chart.set_x_axis(
                    {
                        "name": display(dimension),
                        "date_axis": True,
                        "num_format": "yyyy-mm-dd",
                        "num_font": {"rotation": -30},
                    }
                )
            chart.set_size({"width": 640, "height": 330})
            summary.insert_chart(chart_row, 9, chart)
            chart_row += 18
        note_row = last + 2
        notes = [
            labels["base_currency"] + ": " + BASE_CURRENCY["code"],
            labels["rows_missing"]
            .replace("{rows}", str(len(rows)))
            .replace("{missing}", str(sum(v is None for r in rows for v in r.values()))),
            labels["numeric_precision"],
            labels["trend_note"] if options.get("kind") == "trend" else labels["totals_note"],
            labels["query_filters"]
            + ": "
            + (
                translated.get("query_explanation") or labels["not_available"]
            ),
            labels["scope"] + ": " + (translated.get("scope") or labels["provided_rows"]),
        ]
        if currency_columns:
            notes.append(labels["blank_currency_note"])
        for note in notes:
            sheet.merge_range(note_row, 0, note_row, max(2, min(len(table_fields) - 1, 7)), note, text)
            sheet.set_row(note_row, min(300, max(32, 16 * (len(note) // 90 + 1))))
            note_row += 1
        cursor += 1
    cursor += 1
    for metric in doc["metrics"] if layout is None else []:
        paragraph(f"{metric['label']}: {metric['value']}\n{metric['explanation']}")
    for section in doc["sections"] if layout is None else []:
        paragraph(section["heading"], heading)
        paragraph(section["body"])
    if doc["limitations"] and layout is None:
        paragraph(labels["data_limitations"], heading)
        for limitation in doc["limitations"]:
            paragraph(limitation)
    summary.set_landscape()
    summary.fit_to_pages(1, 0)
    book.close()
    return output.getvalue()
