"""Requested balance data, separate from the private historical reconstruction."""

import json
from decimal import Decimal, localcontext

from .balance_reconciliation import (
    BalanceRequest, account_scope_matches, bridge_rows, bridge_totals, columns_for, sap_date,
)
from .workbooks import ReportDataError

CUTOFF_FIELDS = ["party", "partner_code", "partner_name", "currency", "original_balance"]
DOCUMENT_FIELDS = [
    "party", "partner_code", "partner_name", "currency", "client", "company", "account",
    "document", "year", "line", "posting_date", "entry_date", "entry_time", "sign",
    "amount_local", "original_balance", "source_table",
]


def cutoff_projection(evidence, options, currency):
    """Keep only lines that belonged to the requested historical open balance.

    Later clearing metadata is used for membership, but is never a public field.
    Validate full reconstruction first, including dates, signs and duplicate keys.
    """
    request = BalanceRequest.model_validate(options)
    bridge_rows(evidence, request)
    cutoff = request.knowledge_date or request.as_of_date
    documents, groups = [], {}
    with localcontext() as context:
        context.prec = 80
        for row in evidence:
            cleared, clearing_entered = sap_date(row.get("clearing_date")), sap_date(row.get("clearing_entry_date"))
            if not account_scope_matches(row, request) or sap_date(row["entry_date"]) > cutoff:
                continue
            if cleared and cleared <= request.as_of_date and clearing_entered <= cutoff:
                continue
            amount = Decimal(str(row["amount_local"])) * (
                1 if row["sign"] == ("H" if row["party"] == "supplier" else "S") else -1
            )
            document = {field: row.get(field) for field in DOCUMENT_FIELDS}
            document["original_balance"] = str(amount)
            documents.append(document)
            key = (row["party"], row["partner_code"], row["currency"])
            if key not in groups:
                groups[key] = {field: row[field] for field in CUTOFF_FIELDS[:-1]}
                groups[key]["original_balance"] = Decimal(0)
            groups[key]["original_balance"] += amount
        rows = [{**groups[key], "original_balance": str(groups[key]["original_balance"])} for key in sorted(groups)]
        totals = {party + "/" + currency: {"original_balance": "0"} for party in request.parties}
        for row in rows:
            total = totals.setdefault(row["party"] + "/" + row["currency"], {"original_balance": "0"})
            total["original_balance"] = str(Decimal(total["original_balance"]) + Decimal(row["original_balance"]))
    return rows, documents, totals


def prepare_balance_export(result, options):
    """Apply a presentation mode to any company/date/client/account scope."""
    if result.get("truncated"):
        raise ReportDataError("Incomplete balance evidence cannot be exported.")
    request = BalanceRequest.model_validate(options)
    full_rows, changes = bridge_rows(result["evidence"], request)
    if full_rows != result["rows"] or changes != result["changes"]:
        raise ReportDataError("Balance results do not reconcile with their document evidence.")
    meta = {**result["reconciliation"], "request": request.model_dump(by_alias=True, mode="json")}
    if request.include_reconciliation:
        return {**result, "reconciliation": {**meta, "export_mode": "reconciliation"}}, None
    rows, documents, totals = cutoff_projection(result["evidence"], request, meta["currency"])
    # All subsequent narrative/helper/export consumers receive only this view.
    public_meta = {k: v for k, v in meta.items() if k not in ("queries", "totals")}
    public_meta.update(export_mode="cutoff", totals=totals, document_count=len(documents))
    audit = {"evidence": result["evidence"], "rows": full_rows, "changes": changes,
             "totals": bridge_totals(full_rows)}
    return {
        **result, "rows": rows, "columns": columns_for(rows, CUTOFF_FIELDS),
        "changes": [], "evidence": documents, "reconciliation": public_meta,
        "scope": "Requested historical cutoff balances and eligible documents only; account/partner exclusions apply throughout.",
    }, audit


def cutoff_contract(snapshot, provenance):
    """Independently enforce document eligibility and the partner/total tie-out."""
    meta = provenance["reconciliation"]
    request = BalanceRequest.model_validate(meta["request"])
    analyses = provenance.get("analyses", [])
    if request.include_reconciliation or len(analyses) != 1 or analyses[0].get("options", {}).get("name") != "Eligible balance documents":
        raise ReportDataError("Cutoff exports must contain only requested balances and eligible documents.")
    documents = analyses[0]["rows"]
    internal = provenance.get("_internal", {}).get("balance_audit")
    if internal:
        full, changes = bridge_rows(internal["evidence"], request)
        if full != internal["rows"] or changes != internal["changes"] or bridge_totals(full) != internal["totals"]:
            raise ReportDataError("Private balance reconstruction evidence does not reconcile.")
        rows, expected_documents, totals = cutoff_projection(internal["evidence"], request, meta["currency"])
    else:
        # The worker has no access to private clearing history. The signed
        # amounts/membership of the projected source are checked again here.
        rows, expected_documents, totals = cutoff_projection(documents, request, meta["currency"])
    if (
        rows != json.loads(snapshot["rows_json"]) or documents != expected_documents
        or meta["totals"] != totals or meta["document_count"] != len(documents)
        or [c["name"] for c in provenance.get("columns", [])] != CUTOFF_FIELDS
        or [c["name"] for c in analyses[0].get("columns", [])] != DOCUMENT_FIELDS
    ):
        raise ReportDataError("Cutoff balances or documents violate the requested scope or do not reconcile.")
    return meta, rows, []
