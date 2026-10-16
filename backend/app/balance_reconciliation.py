"""Legacy SAP snapshot integrity checks for saved reports only.

New analyses use model-authored calculation scripts; no fixed data collector,
chat calculator or automatic query-to-balance conversion remains here.
"""

import re
from datetime import date, datetime
from decimal import Decimal, localcontext
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .workbooks import ReportDataError

LOCAL_TIMEZONE = ZoneInfo("Europe/Tirane")


class BalanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: str = Field(default="SAPHANADB", alias="schema", min_length=1, max_length=128)
    client: str = Field(default="400", pattern=r"^\d{3}$")
    company: str = Field(min_length=1, max_length=4)
    as_of_date: date
    knowledge_date: date | None = None
    include_reconciliation: bool = Field(
        default=False,
        description="Expose later adjustments and revised balances only when the user explicitly requests reconciliation.",
    )
    supplier_accounts: list[str] = Field(default_factory=list, max_length=100)
    customer_accounts: list[str] = Field(default_factory=list, max_length=100)
    exclude_supplier_accounts: list[str] = Field(default_factory=list, max_length=100)
    exclude_customer_accounts: list[str] = Field(default_factory=list, max_length=100)
    exclude_supplier_partners: list[str] = Field(default_factory=list, max_length=100)
    exclude_customer_partners: list[str] = Field(default_factory=list, max_length=100)
    parties: list[Literal["supplier", "customer"]] = Field(
        default_factory=lambda: ["supplier", "customer"], min_length=1, max_length=2
    )

    @model_validator(mode="after")
    def dates(self):
        if (self.knowledge_date or self.as_of_date) > datetime.now(LOCAL_TIMEZONE).date():
            raise ValueError("A historical balance cutoff cannot be in the future.")
        if self.knowledge_date and self.knowledge_date < self.as_of_date:
            raise ValueError("The baseline knowledge date cannot precede the balance date.")
        if len(set(self.parties)) != len(self.parties):
            raise ValueError("Balance parties must be unique.")
        identifiers = (
            self.supplier_accounts + self.customer_accounts
            + self.exclude_supplier_accounts + self.exclude_customer_accounts
            + self.exclude_supplier_partners + self.exclude_customer_partners
        )
        if any(not re.fullmatch(r"[A-Za-z0-9]+", a) for a in identifiers):
            raise ValueError("Account and partner filters must contain identifiers only.")
        for party in ("supplier", "customer"):
            if set(getattr(self, f"{party}_accounts")) & set(getattr(self, f"exclude_{party}_accounts")):
                raise ValueError("An account cannot be both included and excluded.")
        return self


BRIDGE_FIELDS = [
    "party",
    "partner_code",
    "partner_name",
    "currency",
    "original_balance",
    "late_postings",
    "backdated_reversals",
    "backdated_clearing",
    "restated_balance",
    "residual",
]
MONEY_FIELDS = BRIDGE_FIELDS[4:]
SHEET_NAMES = {
    "en": ("Balance reconciliation", "Balance adjustments"),
    "sq": ("Rakordimi i gjendjeve", "Ndryshimet e gjendjeve"),
}
CUTOFF_SHEET_NAMES = {"en": "Cutoff balances", "sq": "Gjendjet në datën kufi"}


def sap_date(value):
    value = str(value or "")
    if value in ("", "00000000"):
        return None
    try:
        return date.fromisoformat(value if "-" in value else f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    except ValueError:
        raise ReportDataError("Invalid SAP accounting or entry date in the balance evidence.") from None


def account_scope_matches(row, request):
    party = row["party"]
    accounts = getattr(request, f"{party}_accounts")
    excluded = getattr(request, f"exclude_{party}_accounts")
    if (accounts or excluded) and not row.get("account"):
        raise ReportDataError("SAP account identifiers are required to apply the requested exclusions.")
    return (
        (not accounts or row["account"] in accounts)
        and row.get("account") not in excluded
        and row["partner_code"] not in getattr(request, f"exclude_{party}_partners")
    )


def bridge_rows(evidence, request):
    """Reconstruct membership at the knowledge cutoff, including retroactive clearing.

    A clearing date is an effective date, NOT proof that the clearing existed
    at the cutoff. Its BKPF entry date is essential for a historical baseline.
    """
    request = BalanceRequest.model_validate(request)
    cutoff = request.knowledge_date or request.as_of_date
    groups, changes, seen = {}, [], set()
    with localcontext() as context:
        context.prec = 80
        for row in evidence:
            key = tuple(row.get(k) for k in ("client", "company", "year", "document", "line"))
            if any(value is None or not str(value).strip() for value in key) or not row.get("partner_code"):
                raise ReportDataError("A SAP balance document identifier is missing; adjustments cannot be traced.")
            # Vendor and customer lines are disjoint FI line keys.
            if key in seen:
                raise ReportDataError("Duplicate SAP line key in the balance reconciliation; no report was published.")
            seen.add(key)
            posted, entered = sap_date(row.get("posting_date")), sap_date(row.get("entry_date"))
            cleared, clearing_entered = sap_date(row.get("clearing_date")), sap_date(row.get("clearing_entry_date"))
            if not posted or not entered:
                raise ReportDataError("SAP document entry dates are missing; the baseline cannot be reconstructed.")
            if posted > request.as_of_date or row.get("sign") not in ("S", "H"):
                raise ReportDataError("SAP balance evidence has an invalid posting scope or debit/credit sign.")
            if (
                row.get("party") not in request.parties
                or row.get("company") != request.company
                or row.get("client") != request.client
            ):
                raise ReportDataError(
                    "SAP balance evidence does not match the requested company, client or party scope."
                )
            if not account_scope_matches(row, request):
                continue
            if cleared and cleared <= request.as_of_date and not clearing_entered:
                raise ReportDataError(
                    "SAP clearing entry dates are missing; the original balance cannot be reconstructed safely."
                )
            positive = "H" if row["party"] == "supplier" else "S"
            amount = Decimal(str(row["amount_local"])) * (1 if row["sign"] == positive else -1)
            if not amount.is_finite():
                raise ReportDataError("SAP balance evidence contains an invalid monetary value.")
            current_open = cleared is None or cleared > request.as_of_date
            baseline_open = current_open or clearing_entered > cutoff
            original = amount if entered <= cutoff and baseline_open else Decimal(0)
            restated = amount if current_open else Decimal(0)
            delta = restated - original
            reversing = str(row.get("reversal_indicator") or "") == "2" or row.get("transaction") == "FB08"
            clearing_reversing = (
                str(row.get("clearing_reversal_indicator") or "") == "2" or row.get("clearing_transaction") == "FB08"
            )
            category = (
                "backdated_reversals"
                if reversing or clearing_reversing
                else "late_postings"
                if entered > cutoff
                else "backdated_clearing"
            )
            group_key = (row["party"], row["partner_code"], row["currency"])
            if group_key not in groups:
                groups[group_key] = {
                    "party": row["party"],
                    "partner_code": row["partner_code"],
                    "partner_name": row["partner_name"],
                    "currency": row["currency"],
                    **{field: Decimal(0) for field in MONEY_FIELDS},
                }
            target = groups[group_key]
            target["original_balance"] += original
            target["restated_balance"] += restated
            target[category] += delta
            if delta or entered > cutoff or clearing_entered and clearing_entered > cutoff:
                changes.append(
                    {
                        **row,
                        "category": category,
                        "original_balance": str(original),
                        "change": str(delta),
                        "restated_balance": str(restated),
                    }
                )
        result = []
        for key in sorted(groups):
            row = groups[key]
            row["residual"] = row["restated_balance"] - sum((row[k] for k in MONEY_FIELDS[:4]), Decimal(0))
            if row["residual"]:
                raise ReportDataError("The balance bridge does not reconcile. No partial report was published.")
            result.append({k: str(v) if isinstance(v, Decimal) else v for k, v in row.items()})
    return result, changes


def bridge_totals(rows):
    totals = {}
    with localcontext() as context:
        context.prec = 80
        for row in rows:
            key = row["party"] + "/" + row["currency"]
            total = totals.setdefault(key, {k: Decimal(0) for k in MONEY_FIELDS})
            for field in MONEY_FIELDS:
                total[field] += Decimal(row[field])
    return {key: {field: str(value) for field, value in total.items()} for key, total in totals.items()}


def columns_for(rows, fields=None):
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    monetary = set(MONEY_FIELDS + ["amount_local", "change"])
    return [{"name": k, "type": "decimal" if k in monetary else "text"} for k in fields]
