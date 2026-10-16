"""Company identity discovery must not equate matching names with production scope."""

import copy
from dataclasses import replace

import pytest

from app.connectors import DatabaseUnavailable, SourceNotConfigured
from app.sap_context import inspect_context
from test_application import create_member
from test_database_chat import FixtureDatabase, call_tool, fixture_source


class ContextDatabase(FixtureDatabase):
    dialect = "hana"

    def __init__(self, settings, catalog):
        super().__init__(replace(settings, hana_database="Fixture"), catalog)
        # Deliberately reverse the local installation's numbering convention.
        self.clients = [
            {"MANDT": "400", "MTEXT": "Test copy", "CCCATEGORY": "T"},
            {"MANDT": "500", "MTEXT": "Production", "CCCATEGORY": "P"},
        ]
        self.companies = [
            {"MANDT": client, "BUKRS": "ECO", "BUTXT": "Same business", "WAERS": "ALL", "KTOPL": "CHART"}
            for client in ("400", "500")
        ]
        self.client_error = None

    async def in_database(self, database):
        if database != "Fixture":
            raise SourceNotConfigured("Database not granted")
        return self

    async def describe(self, schema, table):
        if table == "T000" and self.client_error:
            raise self.client_error
        rows = self.clients if table == "T000" else self.companies
        return {"columns": [{"name": key} for key in rows[0]]}

    def _run_full(self, sql, parameters):
        self.calls.append((sql, parameters))
        assert parameters == [] and sql.startswith("SELECT ")
        assert "SELECT TOP " not in sql and " LIMIT " not in sql
        return copy.deepcopy(self.clients if '."T000"' in sql else self.companies)


def registered(client):
    source, _ = fixture_source(client)
    state = client.app.state
    database = ContextDatabase(state.settings, state.connectors.catalog)
    state.connectors.register(source["id"], database)
    return source, database


def test_model_context_preserves_client_roles_and_all_companies_without_creating_report(client, admin):
    source, database = registered(client)
    database.companies += [dict(database.companies[0], BUKRS=str(i)) for i in range(600)]
    result = call_tool(client, admin, "inspect_sap_context", {
        "source_id": source["id"], "database": "Fixture", "schema": "SAPHANADB",
    })
    assert "error" not in result, result
    assert result["company_count"] == 602 and not result["truncated"]
    assert result["companies"][0]["client_category"] == "T"
    assert result["companies"][1]["client_category"] == "P"
    assert result["companies"][0]["company_name"] == result["companies"][1]["company_name"]
    assert result["companies"][1]["local_currency"] == "ALL" and result["warnings"] == []
    assert client.app.state.db.all("SELECT * FROM reports") == []
    assert client.app.state.db.all("SELECT * FROM dataset_snapshots") == []


@pytest.mark.parametrize("failure", [ValueError("missing table"), DatabaseUnavailable("metadata denied", code=258)])
async def test_unreadable_client_metadata_is_a_scope_warning_not_guessed_production(client, admin, failure):
    _, database = registered(client)
    database.client_error = failure
    result = await inspect_context(database, "SAPHANADB")
    assert result["warnings"] and "unverified" in result["warnings"][0]
    assert all(not c["client_metadata_available"] and c["client_category"] is None for c in result["companies"])
    assert result["company_count"] == 2


async def test_context_handles_unmatched_and_duplicate_identity_records_and_quotes_schema(client, admin):
    _, database = registered(client)
    database.companies.append(dict(database.companies[0], MANDT="123"))
    result = await inspect_context(database, 'schema"with quote')
    assert result["companies"][-1]["client_name"] is None
    assert result["warnings"]
    assert all('FROM "schema""with quote".' in sql for sql, _ in database.calls)
    database.companies.append(database.companies[0])
    with pytest.raises(SourceNotConfigured, match="Duplicate SAP company"):
        await inspect_context(database, "SAPHANADB")


def test_context_tool_enforces_source_grants_database_selection_and_dialect(client, admin):
    source, database = registered(client)
    member = create_member(client)
    args = {"source_id": source["id"], "database": "Fixture", "schema": "SAPHANADB"}
    assert "error" in call_tool(client, member, "inspect_sap_context", args)
    assert database.calls == []
    assert "error" in call_tool(client, admin, "inspect_sap_context", {**args, "database": "Forbidden"})
    assert "error" in call_tool(client, admin, "inspect_sap_context", {k: v for k, v in args.items() if k != "database"})
    database.dialect = "sqlserver"
    assert "error" in call_tool(client, admin, "inspect_sap_context", args)
    assert database.calls == []
