"""Mandatory, independently checked cutoff or explicitly requested reconciliation views."""

import json
from datetime import datetime, time
from decimal import Decimal

from .balance_reconciliation import BRIDGE_FIELDS, MONEY_FIELDS, bridge_rows, bridge_totals, sap_date
from .workbooks import ReportDataError, excel_number

DETAIL_FIELDS = [
    "party",
    "partner_code",
    "partner_name",
    "currency",
    "category",
    "document",
    "year",
    "line",
    "posting_date",
    "entry_date",
    "clearing_date",
    "clearing_document",
    "clearing_entry_date",
    "reversal_document",
    "original_balance",
    "change",
    "restated_balance",
]


def balance_contract(snapshot):
    provenance = json.loads(snapshot["provenance_json"])
    meta = provenance.get("reconciliation")
    if not meta:
        return None
    if meta.get("method") != "sap_balance_bridge_v1":
        raise ReportDataError("Unknown balance reconciliation method.")
    if meta.get("export_mode") == "cutoff":
        from .balance_exports import cutoff_contract
        return cutoff_contract(snapshot, provenance)
    evidence = next(
        (
            a["rows"]
            for a in provenance.get("analyses", [])
            if a.get("options", {}).get("name") == "SAP balance evidence"
        ),
        None,
    )
    if evidence is None:
        raise ReportDataError("The complete SAP balance evidence is missing.")
    rows, changes = bridge_rows(evidence, meta["request"])
    if rows != json.loads(snapshot["rows_json"]):
        raise ReportDataError("Balance bridge values do not reconcile with their document evidence.")
    if "totals" in meta and meta["totals"] != bridge_totals(rows):
        raise ReportDataError("Balance narrative totals do not reconcile with their complete document evidence.")
    recorded = next(
        (
            a["rows"]
            for a in provenance.get("analyses", [])
            if a.get("options", {}).get("name") == "Balance adjustments"
        ),
        None,
    )
    if changes != recorded:
        raise ReportDataError("Balance adjustments do not reconcile with their document evidence.")
    return meta, rows, changes


def display(value, field, labels):
    if field in ("party", "category"):
        return labels.get("balance_" + str(value), value)
    if field.endswith("_date"):
        parsed = sap_date(value)
        return datetime.combine(parsed, time()) if parsed else None
    return value


def exact_excel(value):
    result = excel_number(value, True)
    if result is None:
        raise ReportDataError("A balance amount exceeds Excel numeric precision; no rounded balance was published.")
    return result


def render_balance(book, snapshot, labels):
    contract = balance_contract(snapshot)
    if contract is None:
        return
    meta, rows, changes = contract
    if meta.get("export_mode") == "cutoff":
        render_cutoff(book, meta, rows, labels)
        return
    heading = book.add_format({"bold": True, "font_size": 16, "font_color": "#163D60"})
    header = book.add_format(
        {
            "bold": True,
            "font_size": 11,
            "font_color": "#FFFFFF",
            "bg_color": "#163D60",
            "text_wrap": True,
            "valign": "vcenter",
        }
    )
    text = book.add_format({"text_wrap": True, "valign": "top", "font_size": 11})
    money = book.add_format({"num_format": "#,##0.00;[Red](#,##0.00)", "font_size": 11})
    dates = book.add_format(
        {
            "num_format": "dd.mm.yyyy" if labels["balance_party"] == "Pala" else "yyyy-mm-dd",
            "font_size": 11,
            "align": "left",
        }
    )

    def sheet(key, fields, data, table_name):
        header_row = 13 if key == "sheet" else 8
        sheet = book.add_worksheet(labels["balance_" + key])
        sheet.write(0, 0, labels["balance_" + key], heading)
        request = meta["request"]
        sheet.write(
            2,
            0,
            labels["balance_dates"].format(
                asof=request["as_of_date"], knowledge=request.get("knowledge_date") or request["as_of_date"]
            ),
            text,
        )
        sheet.merge_range(
            2,
            0,
            3,
            9,
            labels["balance_dates"].format(
                asof=request["as_of_date"], knowledge=request.get("knowledge_date") or request["as_of_date"]
            ),
            text,
        )
        sheet.merge_range(4, 0, 6, 9, labels["balance_warning"], text)
        sheet.set_row(4, 24)
        sheet.set_column(0, len(fields) - 1, 23)
        sheet.set_column(1, 1, 18)
        sheet.set_column(2, 2, 38)
        sheet.set_column(3, 3, 11)
        if key == "adjustments":
            sheet.set_column(4, 4, 34)
        sheet.freeze_panes(header_row + 1, 3)
        sheet.set_landscape()
        sheet.set_paper(8)
        sheet.fit_to_pages(1, 0)
        sheet.repeat_rows(header_row)
        sheet.print_area(0, 0, header_row + 1 + len(data) + (20 if key == "sheet" else 0), len(fields) - 1)
        for j, field in enumerate(fields):
            sheet.write(header_row, j, labels["balance_" + field], header)
        sheet.set_row(header_row, 48)
        for i, row in enumerate(data, header_row + 1):
            wrapped = False
            for j, field in enumerate(fields):
                value = display(row.get(field), field, labels)
                if key == "sheet" and field == "residual":
                    sheet.write_formula(i, j, f"=I{i + 1}-SUM(E{i + 1}:H{i + 1})", money, exact_excel(value))
                elif field in MONEY_FIELDS or field == "change":
                    sheet.write_number(i, j, exact_excel(value), money)
                elif isinstance(value, datetime):
                    sheet.write_datetime(i, j, value, dates)
                else:
                    sheet.write(i, j, value, text)
                    width = 38 if j == 2 else 34 if key == "adjustments" and j == 4 else 23
                    wrapped = wrapped or len(str(value or "")) > width
            if wrapped:
                sheet.set_row(i, 32)
        if data:
            sheet.add_table(
                header_row,
                0,
                header_row + len(data),
                len(fields) - 1,
                {
                    "name": table_name,
                    "style": "Table Style Medium 2",
                    "columns": [
                        {
                            "header": labels["balance_" + field],
                            "header_format": header,
                            "format": money if field in MONEY_FIELDS or field == "change" else None,
                        }
                        for field in fields
                    ],
                },
            )
        return sheet

    bridge = sheet("sheet", BRIDGE_FIELDS, rows, "BalanceBridge")
    bridge.set_row(8, 48)
    for j, field in enumerate(BRIDGE_FIELDS):
        if j == 0 or j >= 3:
            bridge.write(8, j, labels["balance_" + field], header)
    # Totals stay separated by supplier/customer; their sign conventions differ.
    parties = meta["request"].get("parties", ["supplier", "customer"])
    for i, party in enumerate(parties, 9):
        selected = [r for r in rows if r["party"] == party]
        bridge.write(i, 0, labels["balance_" + party], heading)
        bridge.write(i, 3, meta["currency"])
        for j, field in enumerate(MONEY_FIELDS, 4):
            total = exact_excel(str(sum((Decimal(r[field]) for r in selected), Decimal(0))))
            if rows:
                from xlsxwriter.utility import xl_col_to_name

                letter = xl_col_to_name(j)
                party_label = labels["balance_" + party].replace('"', '""')
                bridge.write_formula(
                    i,
                    j,
                    f'=SUMIF(A15:A{14 + len(rows)},"{party_label}",{letter}15:{letter}{14 + len(rows)})',
                    money,
                    total,
                )
            else:
                bridge.write_number(i, j, total, money)
    chart = book.add_chart({"type": "column"})
    for column, field in ((4, "original_balance"), (8, "restated_balance")):
        chart.add_series(
            {
                "name": labels["balance_" + field],
                "categories": [bridge.name, 9, 0, 8 + len(parties), 0],
                "values": [bridge.name, 9, column, 8 + len(parties), column],
            }
        )
    chart.set_title({"name": labels["balance_chart"]})
    chart.set_y_axis({"name": meta["currency"], "num_format": "#,##0"})
    chart.set_x_axis({"label_position": "low"})
    bridge.insert_chart(17 + len(rows), 0, chart, {"x_scale": 1.1, "y_scale": 0.75})
    sheet("adjustments", DETAIL_FIELDS, changes, "BalanceChanges")


def validate_balance(workbook, snapshot, labels, equivalent):
    contract = balance_contract(snapshot)
    if contract is None:
        return
    meta, rows, changes = contract
    if meta.get("export_mode") == "cutoff":
        validate_cutoff(workbook, meta, rows, labels, equivalent)
        return
    for key, fields, data in (("sheet", BRIDGE_FIELDS, rows), ("adjustments", DETAIL_FIELDS, changes)):
        name = labels["balance_" + key]
        if name not in workbook.sheetnames or workbook[name].sheet_state != "visible":
            raise ReportDataError("Mandatory balance reconciliation sheets are missing or hidden.")
        sheet = workbook[name]
        first = 15 if key == "sheet" else 10
        actual = (
            sheet.iter_rows(min_row=first, max_row=first + len(data) - 1, max_col=len(fields), values_only=True)
            if data
            else []
        )
        for source, cells in zip(data, actual, strict=True):
            for field, value in zip(fields, cells, strict=True):
                expected = (
                    float(Decimal(source[field]))
                    if field in MONEY_FIELDS or field == "change"
                    else display(source.get(field), field, labels)
                )
                if not equivalent(value, expected):
                    raise ReportDataError(
                        "The Excel balance reconciliation does not match its complete document evidence."
                    )
        if key == "sheet":
            for row, party in enumerate(meta["request"].get("parties", ["supplier", "customer"]), 10):
                values = next(sheet.iter_rows(min_row=row, max_row=row, min_col=5, max_col=10, values_only=True))
                for field, value in zip(MONEY_FIELDS, values, strict=True):
                    expected = float(sum((Decimal(r[field]) for r in data if r["party"] == party), Decimal(0)))
                    if not equivalent(value, expected):
                        raise ReportDataError("The Excel balance totals do not reconcile.")


def render_cutoff(book, meta, rows, labels):
    """One enforced summary/detail view; no later-movement columns or chart."""
    from .balance_exports import CUTOFF_FIELDS

    sheet = book.add_worksheet(labels["balance_cutoff_sheet"])
    sheet.hide_gridlines(2)
    sheet.freeze_panes(14, 3)
    sheet.set_column(0, 0, 18)
    sheet.set_column(1, 1, 19)
    sheet.set_column(2, 2, 40)
    sheet.set_column(3, 3, 12)
    sheet.set_column(4, 4, 27)
    heading = book.add_format({"bold": True, "font_size": 15, "font_color": "#163D60"})
    header = book.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": "#163D60", "text_wrap": True})
    text = book.add_format({"font_size": 11, "text_wrap": True, "valign": "top"})
    money = book.add_format({"font_size": 11, "num_format": "#,##0.00;[Red](#,##0.00)"})
    sheet.write(0, 0, labels["balance_cutoff_sheet"], heading)
    request = meta["request"]
    sheet.merge_range(2, 0, 3, 4, labels["balance_dates"].format(
        asof=request["as_of_date"], knowledge=request.get("knowledge_date") or request["as_of_date"]
    ), text)
    sheet.merge_range(4, 0, 6, 4, labels["balance_cutoff_warning"], text)
    for row in (2, 4, 5, 6):
        sheet.set_row(row, 23)
    fields = [labels["balance_" + f] if f != "original_balance" else labels["balance_cutoff_balance"] for f in CUTOFF_FIELDS]
    for column in (0, 3, 4):
        sheet.write(8, column, fields[column], header)
    sheet.set_row(8, 32)
    for row, party in enumerate(request.get("parties", ["supplier", "customer"]), 9):
        sheet.write(row, 0, labels["balance_" + party], heading)
        sheet.write(row, 3, meta["currency"], text)
        total = exact_excel(meta["totals"][party + "/" + meta["currency"]]["original_balance"])
        if rows:
            criterion = labels["balance_" + party].replace('"', '""')
            sheet.write_formula(row, 4, f'=SUMIF(A15:A{14+len(rows)},"{criterion}",E15:E{14+len(rows)})', money, total)
        else:
            sheet.write_number(row, 4, total, money)
    for column, field in enumerate(fields):
        sheet.write(13, column, field, header)
    sheet.set_row(13, 32)
    for row_index, row in enumerate(rows, 14):
        for column, field in enumerate(CUTOFF_FIELDS):
            if field == "original_balance":
                sheet.write_number(row_index, column, exact_excel(row[field]), money)
            else:
                sheet.write(row_index, column, display(row[field], field, labels), text)
        sheet.set_row(row_index, 28 if len(row["partner_name"]) > 38 else 22)
    if rows:
        sheet.add_table(13, 0, 13 + len(rows), 4, {
            "name": "CutoffBalances", "style": "Table Style Medium 2",
            "columns": [{"header": field, "header_format": header} for field in fields],
        })
    sheet.set_landscape()
    sheet.fit_to_pages(1, 0)
    sheet.repeat_rows(13)


def validate_cutoff(workbook, meta, rows, labels, equivalent):
    from .balance_exports import CUTOFF_FIELDS
    from .balance_reconciliation import SHEET_NAMES

    name = labels["balance_cutoff_sheet"]
    forbidden = {n.casefold() for names in SHEET_NAMES.values() for n in names}
    forbidden.update((labels["balance_sheet"].casefold(), labels["balance_adjustments"].casefold()))
    if name not in workbook.sheetnames or workbook[name].sheet_state != "visible" or any(
        n.casefold() in forbidden for n in workbook.sheetnames
    ):
        raise ReportDataError("A cutoff export must show cutoff balances without reconciliation sheets.")
    sheet = workbook[name]
    if rows:
        for row, actual in zip(rows, sheet.iter_rows(min_row=15, max_row=14+len(rows), max_col=5, values_only=True), strict=True):
            for field, value in zip(CUTOFF_FIELDS, actual, strict=True):
                expected = float(Decimal(row[field])) if field == "original_balance" else display(row[field], field, labels)
                if not equivalent(value, expected):
                    raise ReportDataError("Cutoff balances do not match their eligible document evidence.")
    for row_index, party in enumerate(meta["request"].get("parties", ["supplier", "customer"]), 10):
        amount = next(sheet.iter_rows(min_row=row_index, max_row=row_index, min_col=5, max_col=5, values_only=True))[0]
        expected = float(Decimal(meta["totals"][party + "/" + meta["currency"]]["original_balance"]))
        if not equivalent(amount, expected):
            raise ReportDataError("The Excel cutoff balance totals do not reconcile.")
