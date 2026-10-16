"""Independent source and calculation contracts used by rendering and validation."""

import json
import re
from itertools import chain
from decimal import Decimal, InvalidOperation, localcontext

from .currencies import currency_fields, display_currency
from .workbook_locale import presentation
from .workbooks import NUMERIC_TYPES, ReportDataError, analysis_data, excel_number


def datasets(document, snapshot, source_only=False):
    _, labels, translations = presentation(document)
    reference = json.loads(snapshot["provenance_json"]).get("format_reference", {})
    result = []
    for index, data in enumerate(analysis_data(snapshot)):
        translated = translations.get(index, {})
        name = translated.get("name") or data.get("options", {}).get("name") or labels["report_data"]
        sheet_name = f"{index+1} {re.sub(r'[\[\]:*?/\\]', ' ', name).strip(chr(39) + ' ') or labels['data']}"[:31]
        fields = list(dict.fromkeys(chain((c["name"] for c in data.get("columns", [])), (k for row in data["rows"] for k in row))))
        order = translated.get("column_order")
        if order:
            if len(order) != len(fields) or set(order) != set(fields):
                raise ReportDataError("Workbook column order does not match the source fields.")
            fields = order
        rows = data["rows"]
        if data.get("options", {}).get("kind") == "trend" and data.get("options", {}).get("dimension"):
            dimension = data["options"]["dimension"]
            if all(row.get(dimension) is not None for row in rows):
                rows = sorted(rows, key=lambda row: row[dimension])
        result.append({**data, "rows": rows, "fields": fields, "sheet_name": sheet_name,
                       "column_labels": {c["column"]: c["label"] for c in translated.get("columns", [])},
                       "types": {c["name"]: c.get("type", "").lower() for c in data.get("columns", [])},
                       "currency_columns": currency_fields(data["rows"], data.get("columns", []), data.get("query")),
                       "first_row": int(reference.get("header_row", 4)) + 2,
                       "source_only": source_only,
                       "table_name": f"T_{re.sub(r'[^A-Za-z0-9_]', '', labels['table_name'])[:50]}{index+1}"})
    return result


def select_currency(data, currency=None, currency_column=None):
    fields = currency_fields(data["rows"], data.get("columns", []), data.get("query"))
    if currency_column is not None and currency_column not in fields:
        raise ReportDataError("Currency dimension is not a source currency field.")
    if currency_column is None and len(fields) > 1:
        raise ReportDataError("Choose an explicit currency_column when multiple currency fields exist.")
    field = currency_column or next(iter(fields), None)
    codes = {str(display_currency(row.get(field))) for row in data["rows"]} if field else {"ALL"}
    if currency is None and len(codes) > 1:
        raise ReportDataError("A monetary calculation or chart must select one currency; incompatible currencies cannot be combined.")
    code = str(currency) if currency is not None else next(iter(codes), "ALL")
    if codes and code not in codes:
        raise ReportDataError("Requested currency does not exist in this dataset.")
    rows = [row for row in data["rows"] if str(display_currency(row.get(field))) == code] if field else data["rows"]
    return rows, code, field


def metric(data, column, currency=None, operation="sum", currency_column=None):
    if column not in data["fields"] or operation not in ("sum", "count", "average", "min", "max"):
        raise ReportDataError("Workbook metric requires a source column and sum/count/average/min/max.")
    rows, code, field = select_currency(data, currency, currency_column)
    if operation == "count":
        return Decimal(len(rows)), code, field, len(rows)
    values = []
    with localcontext() as context:
        context.prec = 80
        for row in rows:
            value = row.get(column)
            if isinstance(value, bool) or value is None or not (isinstance(value, (int, float)) or data["types"].get(column) in NUMERIC_TYPES):
                return None, code, field, len(rows)
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                return None, code, field, len(rows)
            if not number.is_finite() or excel_number(value, True) is None:
                return None, code, field, len(rows)
            values.append(number)
        if not values:
            return (Decimal(0) if operation == "sum" else None), code, field, len(rows)
        result = {"sum": lambda: sum(values), "average": lambda: sum(values) / len(values),
                  "min": lambda: min(values), "max": lambda: max(values)}[operation]()
    return result, code, field, len(rows)


def comparison(data, item):
    left, code, _, _ = metric(data[item["left_dataset"]], item["left_column"], item.get("currency"), currency_column=item.get("currency_column"))
    right, right_code, _, _ = metric(data[item["right_dataset"]], item["right_column"], item.get("currency"), currency_column=item.get("currency_column"))
    if code != right_code or item["operation"] not in ("difference", "percent_change", "ratio"):
        raise ReportDataError("Comparisons require matching currencies and difference/percent_change/ratio.")
    if left is None or right is None or right == 0 and item["operation"] != "difference":
        return None, code
    with localcontext() as context:
        context.prec = 80
        return ({"difference": lambda: left-right, "percent_change": lambda: (left-right)/abs(right),
                 "ratio": lambda: left/right}[item["operation"]](), code)
