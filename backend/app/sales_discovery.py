"""Discover readable Business Central posted-sales tables, never guess company names."""

import asyncio
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .database_tools import quote

ROLES = {
    "Sales Invoice Header": ("invoice_header", {"No_", "Posting Date", "Currency Code"}),
    "Sales Invoice Line": ("invoice_line", {"Document No_", "Amount", "Amount Including VAT"}),
    "Sales Cr_Memo Header": ("credit_header", {"No_", "Posting Date", "Currency Code"}),
    "Sales Cr_Memo Line": ("credit_line", {"Document No_", "Amount", "Amount Including VAT"}),
}


async def discover_sales(connector, company=None):
    from .connectors import DatabaseUnavailable

    candidates, offset = [], 0
    while True:
        page = await asyncio.to_thread(
            connector._run,
            """SELECT TABLE_SCHEMA AS schema_name,TABLE_NAME AS name FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE' AND (TABLE_NAME LIKE %(invoice)s OR TABLE_NAME LIKE %(credit)s)
            ORDER BY TABLE_SCHEMA,TABLE_NAME OFFSET %(offset)s ROWS FETCH NEXT 201 ROWS ONLY""",
            {"invoice": "%$Sales Invoice %", "credit": "%$Sales Cr[_]Memo %", "offset": offset},
        )
        candidates.extend(page[:200])
        if len(page) <= 200:
            break
        offset += 200
    companies, unavailable = {}, []
    for candidate in candidates:
        match = re.fullmatch(r"(.+)\$(Sales Invoice Header|Sales Invoice Line|Sales Cr_Memo Header|Sales Cr_Memo Line)(?:\$[a-fA-F0-9-]{36})?", candidate["name"])
        if not match or company and match[1].casefold() != company.casefold():
            continue
        role, required = ROLES[match[2]]
        try:
            description = await connector.describe(candidate["schema_name"], candidate["name"])
            if not required <= {column["name"] for column in description["columns"]}:
                # BC extension tables share the name but don't contain invoice amounts.
                continue
            await asyncio.to_thread(connector._run, f"SELECT TOP (0) * FROM {quote(candidate['schema_name'])}.{quote(candidate['name'])}", {})
        except DatabaseUnavailable as exc:
            unavailable.append({"table": candidate["name"], "database_error_code": exc.code})
            continue
        group = companies.setdefault(match[1], {})
        if role in group:
            group[role]["ambiguous"] = True
        else:
            group[role] = {"schema": description["schema"], "name": description["table"], "columns": description["columns"]}
    choices = []
    for name, tables in companies.items():
        complete = {"invoice_header", "invoice_line"} <= tables.keys() and not any(t.get("ambiguous") for t in tables.values())
        choices.append({"company": name, "invoice_tables_complete": complete, "tables": tables})
    usable = [choice for choice in choices if choice["invoice_tables_complete"]]
    return {
        "companies": choices,
        "recommended_company": usable[0]["company"] if len(usable) == 1 else None,
        "requires_company_choice": False,
        "multiple_companies": len(usable) > 1,
        "business_date": datetime.now(ZoneInfo("Europe/Tirane")).date().isoformat(),
        "timezone": "Europe/Tirane",
        "base_currency": "ALL",
        "unavailable_tables": unavailable,
        "guidance": "These are verified readable base tables ONLY in this database. Continue discovery in the other accessible databases from discover_databases; recommended_company and requires_company_choice are local compatibility hints, not a limit on report scope. Cover all relevant companies unless the user specifies a scope; keep database/company provenance separate and investigate duplicate/archive data before combining. Stale views are not independent companies. Join invoice/credit lines Document No_ to the corresponding header No_, with Posting Date >= period start and < next period start. Header Currency Code blank means ALL. Keep currencies separate; invoice Amount excludes VAT and Amount Including VAT includes VAT. Subtract matching posted credit memo amounts for net sales; show invoices and credits separately and disclose missing credit tables. Verify join cardinality; extension tables and open orders are not posted invoices.",
    }
