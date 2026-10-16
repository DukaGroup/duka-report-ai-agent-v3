"""Trusted XlsxWriter helpers: generated Python chooses layout, never arbitrary formulas."""

import math
import json
import re

from xlsxwriter.utility import xl_col_to_name

from .currencies import currency_fields, display_currency
from .workbooks import NUMERIC_TYPES, ReportDataError, excel_number
from .workbook_contract import datasets, select_currency, metric, comparison


def render_layout(book, document, snapshot, layout, labels):
    data = datasets(document, snapshot, source_only=True)
    reference = json.loads(snapshot["provenance_json"]).get("format_reference", {})
    font = str(reference.get("font_name") or "Calibri")[:80]
    color = reference.get("header_color") or "#205C49"
    header_color = reference.get("header_font_color") or "#FFFFFF"
    table_style = re.sub(r"TableStyle(Medium|Light|Dark)([0-9]+)", r"Table Style \1 \2", reference.get("table_style") or "Table Style Medium 4")
    if not re.fullmatch(r"Table Style (?:Medium|Light|Dark) [0-9]{1,2}", table_style):
        table_style = "Table Style Medium 4"
    reserved = {labels["overview"].casefold(), labels["scope"].casefold(), *(d["sheet_name"].casefold() for d in data)}
    checks = []
    table_id = 0
    title = book.add_format({"bold": True, "font_name": font, "font_size": 20, "font_color": color, "text_wrap": True, "valign": "vcenter"})
    heading = book.add_format({"bold": True, "font_name": font, "font_size": 13, "font_color": color, "text_wrap": True})
    text = book.add_format({"font_name": font, "font_size": 11, "text_wrap": True, "valign": "top", "font_color": "#33483F"})
    amount = book.add_format({"num_format": '#,##0.00;[Red](#,##0.00);"—"', "font_size": 12, "align": "right"})
    percent = book.add_format({"num_format": "0.0%;[Red](0.0%)", "font_size": 12, "align": "right"})
    table_header = book.add_format({"bold": True, "font_name": font, "bg_color": color, "font_color": header_color, "text_wrap": True})

    def quoted(value):
        return '"' + str(value).replace('"', '""') + '"'

    def expression(index, column, code, currency_column, operation):
        source = data[index]
        first, last = source["first_row"], source["first_row"] + len(source["rows"]) - 1
        if not source["rows"]:
            return "0"
        name = source["sheet_name"].replace("'", "''")
        letter = xl_col_to_name(source["fields"].index(column))
        interval = f"'{name}'!{letter}{first}:{letter}{last}"
        if currency_column:
            letter = xl_col_to_name(source["fields"].index(currency_column))
            currencies = f"'{name}'!{letter}{first}:{letter}{last}"
            if operation == "count":
                return f"COUNTIF({currencies},{quoted(code)})"
            if operation in ("sum", "average"):
                function = "SUMIF" if operation == "sum" else "AVERAGEIF"
                return f"{function}({currencies},{quoted(code)},{interval})"
        return f"{'ROWS' if operation == 'count' else 'AVERAGE' if operation == 'average' else 'SUM'}({interval})"

    for plan in layout:
        name = plan["name"]
        if not name.strip() or re.search(r"[\[\]:*?/\\]", name) or name.startswith("'") or name.endswith("'") or name.casefold() in reserved:
            raise ReportDataError("Output sheet names must be unique and cannot replace protected source sheets.")
        reserved.add(name.casefold())
        sheet = book.add_worksheet(name)
        sheet.hide_gridlines(2)
        sheet.set_tab_color("#205C49")
        for index, width in enumerate(plan["widths"]):
            sheet.set_column(index, index, width)
        sheet.set_landscape()
        sheet.fit_to_pages(1, 0)
        row, width, chart_column = 1, max(2, min(7, len(plan["widths"])-1)), 30
        for item in plan["items"]:
            kind = item["kind"]
            if row >= 1048000:
                raise ReportDataError("Generated output exceeds Excel worksheet capacity.")
            if kind == "space":
                row += item["rows"]
            elif kind in ("title", "heading", "paragraph"):
                value = item["text"]
                if len(value) > 20000:
                    raise ReportDataError("Generated layout text exceeds the paragraph limit.")
                # Long text uses several rows; no merge range crosses a later table/chart.
                for start in range(0, max(1, len(value)), 900):
                    chunk = value[start:start+900]
                    sheet.merge_range(row, 0, row, width, chunk, title if kind == "title" else heading if kind == "heading" else text)
                    line_height = 25 if kind == "title" else 20 if kind == "heading" else 17
                    sheet.set_row(row, min(300, max(32, line_height * (math.ceil(len(chunk)/85) + chunk.count("\n")))))
                    row += 2
            elif kind in ("metric", "compare"):
                if kind == "metric":
                    result, code, field, _ = metric(data[item["dataset"]], item["column"], item.get("currency"), item["operation"], item.get("currency_column"))
                    formula = expression(item["dataset"], item["column"], code, field, item["operation"])
                else:
                    result, code = comparison(data, item)
                    left_source, right_source = data[item["left_dataset"]], data[item["right_dataset"]]
                    left_field = select_currency(left_source, code, item.get("currency_column"))[2]
                    right_field = select_currency(right_source, code, item.get("currency_column"))[2]
                    left = expression(item["left_dataset"], item["left_column"], code, left_field, "sum")
                    right = expression(item["right_dataset"], item["right_column"], code, right_field, "sum")
                    formula = f"({left})-({right})" if item["operation"] == "difference" else f"(({left})-({right}))/ABS({right})" if item["operation"] == "percent_change" else f"({left})/({right})"
                caption = item["label"] + " — " + code
                sheet.merge_range(row, 0, row, 1, caption, text)
                sheet.set_row(row, min(300, max(38, 17 * math.ceil(len(caption)/60))))
                fmt = percent if kind == "compare" and item["operation"] in ("ratio", "percent_change") else amount
                expected = labels["not_available"] if result is None else str(result)
                if result is None:
                    sheet.write_string(row, 2, labels["not_available"], text)
                elif excel_number(result, True) is None:
                    sheet.write_string(row, 2, str(result), text)
                elif kind == "metric" and item["operation"] in ("min", "max"):
                    sheet.write_number(row, 2, float(result), fmt)
                else:
                    sheet.write_formula(row, 2, "=" + formula, fmt, float(result))
                checks.append({"kind": kind, "sheet": name, "row": row+1, "column": 3, "request": item, "expected": expected})
                row += 2
            elif kind == "table":
                source = data[item["dataset"]]
                fields = item.get("columns") or source["fields"]
                if not isinstance(fields, list) or not fields or len(set(fields)) != len(fields) or set(fields) - set(source["fields"]):
                    raise ReportDataError("Output tables must use unique source column names.")
                rows = select_currency(source, item["currency"], item.get("currency_column"))[0] if item.get("currency") else source["rows"]
                if row + len(rows) > 1048500:
                    raise ReportDataError("Output table exceeds Excel worksheet capacity.")
                currency_columns = currency_fields(source["rows"], source.get("columns", []), source.get("query"))
                headers = [source["column_labels"].get(field, field) for field in fields]
                widths = []
                for column, field in enumerate(fields):
                    chosen = plan["widths"][column] if column < len(plan["widths"]) else min(46, max(18, len(headers[column])+2))
                    widths.append(chosen)
                    sheet.set_column(column, column, chosen)
                for offset, source_row in enumerate(rows, row+1):
                    values = [display_currency(source_row.get(field)) if field in currency_columns else source_row.get(field) for field in fields]
                    height = min(160, max(24, max((16 * math.ceil(len(str(value or ""))/max(8, widths[column]-2)) for column, value in enumerate(values)), default=24)))
                    sheet.set_row(offset, height)
                    for column, value in enumerate(values):
                        original_field = fields[column]
                        converted = excel_number(value, True) if source["types"].get(original_field) in NUMERIC_TYPES or isinstance(value, (int, float)) and not isinstance(value, bool) else None
                        if converted is None and isinstance(value, (int, float)) and not isinstance(value, bool):
                            value = str(value)
                        sheet.write(offset, column, converted if converted is not None else value, amount if converted is not None else text)
                if rows:
                    table_id += 1
                    sheet.add_table(row, 0, row+len(rows), len(fields)-1, {"name": f"View_{table_id}", "columns": [{"header": h, "header_format": table_header} for h in headers], "style": table_style})
                else:
                    sheet.write(row, 0, labels["no_rows"], text)
                checks.append({"kind": "table", "sheet": name, "row": row+2, "request": item, "row_count": len(rows)})
                sheet.set_row(row, 36)
                row += len(rows) + 4
            elif kind == "chart":
                source = data[item["dataset"]]
                selected, code, _ = select_currency(source, item.get("currency"), item.get("currency_column"))
                measures = item["measures"]
                if item["category"] not in source["fields"] or not isinstance(measures, list) or not 1 <= len(measures) <= 4 or set(measures) - set(source["fields"]) or item["chart_type"] not in ("line", "column", "bar", "area"):
                    raise ReportDataError("Charts require source columns, 1–4 measures and line/column/bar/area.")
                if not selected:
                    continue
                chart = book.add_chart({"type": item["chart_type"]})
                chart_rows = selected[:1000]
                sheet.set_column(chart_column, chart_column+len(measures), None, None, {"hidden": True})
                for offset, source_row in enumerate(chart_rows):
                    sheet.write_string(offset, chart_column, str(source_row.get(item["category"], "")))
                    for measure_index, measure in enumerate(measures):
                        value = excel_number(source_row.get(measure), True)
                        sheet.write(offset, chart_column+measure_index+1, value)
                for index, measure in enumerate(measures):
                    chart.add_series({"name": source["column_labels"].get(measure, measure),
                                      "categories": [name, 0, chart_column, len(chart_rows)-1, chart_column],
                                      "values": [name, 0, chart_column+index+1, len(chart_rows)-1, chart_column+index+1],
                                      "line": {"color": ["#205C49", "#91AC6B", "#6E8B9D", "#B29B74"][index]}})
                chart.set_title({"name": item["title"] + " — " + code})
                category_label = source["column_labels"].get(item["category"], item["category"])
                money = any(re.search(r"revenue|sales|amount|cost|profit|vat|tax", field, re.I) and not re.search(r"margin|percent|rate|count|quantity", field, re.I) for field in measures)
                value_label = code if money else ", ".join(source["column_labels"].get(field, field) for field in measures)
                chart.set_x_axis({"name": value_label if item["chart_type"] == "bar" else category_label})
                chart.set_y_axis({"name": category_label if item["chart_type"] == "bar" else value_label, "num_format": "#,##0.##"})
                chart.set_legend({"position": "bottom"})
                chart.set_size({"width": 760, "height": 340})
                sheet.insert_chart(row, 0, chart)
                chart_column += len(measures)+2
                for offset in range(row, row+19):
                    sheet.set_row(offset, 20)
                row += 20
                if len(selected) > 1000:
                    sheet.merge_range(row, 0, row, width, labels["chart_limit"].replace("40", "1000"), text)
                    row += 2
    return checks
