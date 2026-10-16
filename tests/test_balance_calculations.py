"""Retired accounting entry points and preserved historical snapshot validation."""

import re
from dataclasses import replace
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.balance_reconciliation import BalanceRequest, bridge_rows
from app.connectors import SourceNotConfigured
from app.workbooks import ReportDataError
from test_balance_reconciliation import OPTIONS, line
from test_database_chat import FixtureDatabase, call_tool, fixture_source


class BalanceDatabase(FixtureDatabase):
    dialect = "hana"

    def __init__(self, settings, catalog):
        super().__init__(replace(settings, hana_database="Fixture"), catalog)
        base = [
            line(document="invoice", entry_date="20261009", account="4011002200"),
            line(document="late", sign="S", amount_local="20", entry_date="20261010", account="4011002200"),
            line(document="cleared", amount_local="75", account="4011002200",
                 clearing_date="20261008", clearing_entry_date="20261010", source_table="BSAK"),
            line(document="loan", partner_code="BANK", amount_local="1000", account="4610041000"),
            line(document="mixed-trade", partner_code="BANK", amount_local="10", account="4011002200"),
            line(document="sale", party="customer", partner_code="C1", sign="S",
                 amount_local="200", account="4110002100"),
            line(document="receipt", party="customer", partner_code="C1", sign="H",
                 amount_local="50", account="4110002100", entry_date="20261010"),
        ]
        self.evidence = []
        for client, multiplier in (("400", 1), ("500", 2)):
            for row in base:
                self.evidence.append({
                    **row, "client": client,
                    "amount_local": str(Decimal(row["amount_local"]) * multiplier),
                    "source_table": row.get("source_table", "BSIK" if row["party"] == "supplier" else "BSID"),
                })

    async def in_database(self, database):
        assert database == "Fixture"
        return self

    async def describe(self, schema, table):
        fields = {
            "MANDT", "BUKRS", "BELNR", "GJAHR", "BUZEI", "BUDAT", "AUGDT", "AUGBL", "AUGGJ",
            "HKONT", "SHKZG", "DMBTR", "CPUDT", "CPUTM", "TCODE", "STBLG", "STJAH", "XREVERSAL",
        }
        return {"columns": [{"name": name} for name in fields]}

    def _run_full(self, sql, parameters):
        self.calls.append((sql, list(parameters)))
        assert sql.startswith("SELECT ") and " LIMIT " not in sql and " TOP " not in sql
        if '."T001"' in sql:
            return [{"currency": "ALL"}]
        table = re.search(r'FROM "SAPHANADB"\."(BSIK|BSAK|BSID|BSAD)"', sql)[1]
        client, company, asof = parameters[:3]
        rows = [dict(r) for r in self.evidence if r["client"] == client and r["company"] == company
                and r["posting_date"] <= asof and r["source_table"] == table]
        offset = 3
        for match in re.finditer(r't\."(HKONT|LIFNR|KUNNR)" (NOT IN|IN) \(([^)]+)\)', sql):
            count = match[3].count("?")
            values = parameters[offset:offset + count]
            offset += count
            field = "account" if match[1] == "HKONT" else "partner_code"
            rows = [r for r in rows if (r[field] not in values if match[2] == "NOT IN" else r[field] in values)]
        assert list(parameters[offset:]) == [asof, "20261009", "20261009"]
        return rows


def registered_database(client):
    source, _ = fixture_source(client)
    state = client.app.state
    connector = BalanceDatabase(state.settings, state.connectors.catalog)
    state.connectors.register(source["id"], connector)
    return source, connector


def calculate(http_client, user, source, **options):
    return call_tool(http_client, user, "calculate_balances", {
        "source_id": source["id"], "database": "Fixture",
        "balance_reconciliation": {**OPTIONS, **options},
    })


def test_retired_calculators_cannot_query_or_create_reports_even_in_older_chats(client, admin, monkeypatch):
    source, connector = registered_database(client)
    async def forbidden_report(*args, **kwargs):
        raise AssertionError("Retired tools must not create reports")
    monkeypatch.setattr(client.app.state.manager, "report_handler", forbidden_report)
    for tool in ("calculate_balances", "create_balance_report"):
        for marker in ("", "CALCULATE_ONLY", "CALCULATE_RECONCILIATION_ONLY", "RECONCILIATION_REQUESTED\nCompare"):
            result = call_tool(client, admin, tool, {
                "source_id": source["id"], "database": "Fixture", "title": "Old calculation",
                "instructions": marker, "balance_reconciliation": OPTIONS,
            })
            assert "retired" in result["error"] and result["replacement"] == "calculate_data"
            assert "CALCULATE_DATA" in result["legacy_recovery"]
    assert connector.calls == []
    assert client.app.state.db.all("SELECT * FROM reports") == []
    assert client.app.state.db.all("SELECT * FROM dataset_snapshots") == []


async def test_retired_connector_dispatch_never_runs_builtin_accounting_rules(client, admin, monkeypatch):
    source, connector = registered_database(client)
    async def forbidden(options):
        raise AssertionError("A registered override must not bypass retirement")
    monkeypatch.setattr(connector, "balance_reconciliation", forbidden)
    with pytest.raises(SourceNotConfigured, match="retired"):
        await client.app.state.connectors.database_call(admin["id"], source["id"], "balance_reconciliation",
                                                        database="Fixture", options=OPTIONS)
    assert connector.calls == []


def test_retired_tools_do_not_validate_or_execute_user_supplied_formulas(client, admin):
    source, connector = registered_database(client)
    result = calculate(client, admin, source, exclude_supplier_accounts=["x'); DROP TABLE BKPF;--"])
    assert "retired" in result["error"] and "totals" not in result
    assert connector.calls == []


def test_retired_tool_returns_no_data_to_ungranted_users(client, admin):
    from test_application import create_member, sign_in_member
    source, connector = registered_database(client)
    member = create_member(client)
    sign_in_member(client)
    result = calculate(client, member, source)
    assert "error" in result and "totals" not in result
    assert connector.calls == []


def test_request_rejects_contradictory_and_unverifiable_account_filters():
    with pytest.raises(ValidationError, match="both included and excluded"):
        BalanceRequest.model_validate({**OPTIONS, "supplier_accounts": ["4011002200"],
                                       "exclude_supplier_accounts": ["4011002200"]})
    with pytest.raises(ReportDataError, match="account identifiers"):
        bridge_rows([line()], {**OPTIONS, "exclude_supplier_accounts": ["4610041000"]})


