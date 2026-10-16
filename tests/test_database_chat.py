import json
import time

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.connectors import SQLServerConnector
from app.database_tools import DatabaseQuery, compile_select
from app.provider import REPORT_TOOLS
from conftest import HEADERS
from test_application import create_member, sign_in_member


DESCRIPTIONS = {
    "s": {
        "columns": [
            {"name": "Id", "type": "int"},
            {"name": "CustomerId", "type": "int"},
            {"name": "Date", "type": "datetime2"},
            {"name": "Amount", "type": "decimal"},
        ]
    },
    "c": {"columns": [{"name": "Id", "type": "int"}, {"name": "Name", "type": "nvarchar"}]},
}


def query_plan(**changes):
    return {
        "tables": [{"schema": "dbo", "name": "Sales", "alias": "s"}],
        "metrics": [{"function": "sum", "column": "s.Amount", "alias": "revenue"}],
        **changes,
    }


def compile_plan(**changes):
    return compile_select(DatabaseQuery.model_validate(query_plan(**changes)), DESCRIPTIONS)


def test_query_values_are_bound_identifiers_validated_and_no_arbitrary_sql():
    attack = "x'; DROP TABLE Sales; --"
    sql, params, columns = compile_plan(filters=[{"column": "s.CustomerId", "operator": "eq", "value": attack}])
    assert attack not in sql and params == {"f0": attack}
    assert "SUM([s].[Amount])" in sql and "WHERE [s].[CustomerId] = %(f0)s" in sql
    assert columns == [{"name": "revenue", "type": "decimal"}]
    with pytest.raises(ValueError, match="Unknown column"):
        compile_plan(metrics=[{"function": "sum", "column": "s.Amount];DROP", "alias": "x"}])
    with pytest.raises(ValidationError):
        DatabaseQuery.model_validate({**query_plan(), "sql": "SELECT *"})
    with pytest.raises(ValidationError):
        DatabaseQuery.model_validate(query_plan(limit=100000))
    with pytest.raises(ValidationError):
        DatabaseQuery.model_validate(query_plan(metrics=[{"function": "EXEC", "column": "s.Id", "alias": "x"}]))


def test_monthly_grouping_and_verified_join_compile_to_select_only():
    sql, params, columns = compile_plan(
        tables=[{"schema": "dbo", "name": "Sales", "alias": "s"}, {"schema": "dbo", "name": "Customers", "alias": "c"}],
        joins=[{"left": "s.CustomerId", "right": "c.Id", "kind": "left"}],
        select=[{"column": "s.Date", "alias": "month", "bucket": "month"}],
        group_by=["month"],
        order_by=[{"column": "month", "direction": "asc"}],
        filters=[{"column": "s.Date", "operator": "gte", "value": "2026-01-01"}],
    )
    assert "DATEFROMPARTS(YEAR([s].[Date]), MONTH([s].[Date]), 1)" in sql
    assert "LEFT JOIN [dbo].[Customers] AS [c] ON [s].[CustomerId] = [c].[Id]" in sql
    assert "GROUP BY DATEFROMPARTS" in sql and "ORDER BY [month] ASC" in sql
    assert params == {"f0": "2026-01-01"} and columns[0]["type"] == "date"
    with pytest.raises(ValueError, match="group_by"):
        compile_plan(select=[{"column": "s.Date"}])
    with pytest.raises(ValueError, match="numeric column"):
        compile_plan(
            tables=[{"name": "Customers", "alias": "c"}],
            metrics=[{"function": "sum", "column": "c.Name", "alias": "x"}],
        )


def test_in_null_filters_and_exotic_identifier_quoting():
    sql, params, _ = compile_plan(
        filters=[{"column": "s.Id", "operator": "in", "values": [1, 2]}, {"column": "s.Date", "operator": "is_null"}]
    )
    assert "[s].[Id] IN (%(f0_0)s, %(f0_1)s)" in sql and "[s].[Date] IS NULL" in sql
    assert params == {"f0_0": 1, "f0_1": 2}
    plan = DatabaseQuery.model_validate(query_plan(tables=[{"name": "Sales]; DROP TABLE Other;--", "alias": "s"}]))
    sql, _, _ = compile_select(plan, DESCRIPTIONS)
    assert "[Sales]]; DROP TABLE Other;--]" in sql
    with pytest.raises(ValueError):
        compile_plan(filters=[{"column": "s.Id", "operator": "in", "values": []}])


def test_native_tool_schemas_resolve_nested_query_definitions():
    for tool in REPORT_TOOLS[0]["tools"]:
        Draft202012Validator.check_schema(tool["inputSchema"])
        if tool["name"] in ("query_database", "create_database_report"):
            data = {"source_id": "fixture", "query": query_plan()}
            if tool["name"] == "create_database_report":
                data.update(title="Raport", instructions="Analizo", template_id="sales")
            Draft202012Validator(tool["inputSchema"]).validate(data)


def test_display_aliases_allow_spaces_and_remain_quoted_not_executable():
    label = "Sales incl VAT]; DROP TABLE Sales; --"
    sql, _, columns = compile_plan(metrics=[{"function": "sum", "column": "s.Amount", "alias": label}])
    assert "AS [Sales incl VAT]]; DROP TABLE Sales; --]" in sql
    assert columns[0]["name"] == label
    sql, _, _ = compile_plan(
        select=[{"column": "s.Date", "alias": "Posting Month", "bucket": "month"}],
        group_by=["Posting Month"],
        order_by=[{"column": "Posting Month"}],
    )
    assert "ORDER BY [Posting Month]" in sql
    with pytest.raises(ValidationError):
        compile_plan(metrics=[{"function": "sum", "column": "s.Amount", "alias": "Bad\nlabel"}])
    with pytest.raises(ValueError, match="unique"):
        compile_plan(
            metrics=[
                {"function": "sum", "column": "s.Amount", "alias": "Sales"},
                {"function": "sum", "column": "s.Amount", "alias": "sales"},
            ]
        )


class FixtureDatabase(SQLServerConnector):
    """Schema and query result fixture: no remote database, credentials or inference."""

    def __init__(self, settings, catalog, truncated=False):
        from dataclasses import replace

        settings = replace(settings, sqlserver_database=settings.sqlserver_database or "Fixture")
        super().__init__(settings, catalog)
        self.truncated = truncated
        self.calls = []

    async def tables(self, offset=0, limit=100):
        self.calls.append("tables")
        return {"tables": [{"schema_name": "dbo", "name": "Sales", "kind": "BASE TABLE"}], "next_offset": None}

    async def describe(self, schema, table):
        self.calls.append("describe")
        return {"schema": schema, "table": table, **DESCRIPTIONS["s"], "relationships": []}

    def _run(self, sql, parameters, max_rows=500):
        assert sql.startswith("SELECT TOP")
        self.calls.append((sql, parameters))
        return [{"revenue": "123.45"}] * (2 if self.truncated else 1)

    def _run_full(self, sql, parameters):
        assert sql.startswith("SELECT ") and "SELECT TOP" not in sql
        self.calls.append((sql, parameters))
        return [{"revenue": "123.45"}] * (2 if self.truncated else 1)


def fixture_source(client, truncated=False):
    source = client.post(
        "/api/admin/sources", headers=HEADERS, json={"name": "Automatic reporting", "kind": "sqlserver"}
    ).json()
    state = client.app.state
    connector = FixtureDatabase(state.settings, state.connectors.catalog, truncated)
    state.connectors.register(source["id"], connector)
    return source, connector


def call_tool(client, user, name, arguments):
    params = {"namespace": "duka_reporting", "tool": name, "arguments": arguments}
    if name in ("create_report", "create_database_report"):
        # Real dynamic tool calls always carry the originating chat thread.
        chat = client.post("/api/conversations", headers=HEADERS, json={}).json()
        thread_id = "fixture-" + chat["id"]
        client.app.state.db.execute("UPDATE conversations SET provider_thread_id=? WHERE id=?", (thread_id, chat["id"]))
        params["threadId"] = thread_id
    response = client.portal.call(
        client.app.state.manager.tool_call,
        user["id"],
        params,
    )
    return json.loads(response["contentItems"][0]["text"])


def test_admin_discovers_reads_and_saves_report_without_any_dataset(client, admin):
    source, connector = fixture_source(client)
    assert client.get("/api/admin/datasets").json() == []
    assert call_tool(client, admin, "list_sources", {})["sources"][0]["id"] == source["id"]
    assert call_tool(client, admin, "list_tables", {"source_id": source["id"]})["tables"][0]["name"] == "Sales"
    assert call_tool(client, admin, "describe_table", {"source_id": source["id"], "schema": "dbo", "table": "Sales"})[
        "columns"
    ]
    rows = call_tool(client, admin, "query_database", {"source_id": source["id"], "query": query_plan()})
    assert rows["rows"] == [{"revenue": "123.45"}] and rows["truncated"] is False
    client.post("/api/subscription/login", headers=HEADERS)
    for _ in range(100):
        if client.get("/api/subscription").json()["connected"]:
            break
        time.sleep(0.01)
    saved = call_tool(
        client,
        admin,
        "create_database_report",
        {
            "source_id": source["id"],
            "query": query_plan(),
            "title": "Shitjet",
            "instructions": "Në shqip",
            "template_id": "sales",
        },
    )
    assert saved["status"] == "queued", saved
    for _ in range(100):
        report = client.get(f"/api/reports/{saved['report_id']}").json()
        if report["status"] in ("completed", "failed"):
            break
        time.sleep(0.01)
    assert report["status"] == "completed", report
    snapshot = client.app.state.db.one("SELECT * FROM dataset_snapshots WHERE id=?", (report["snapshot_id"],))
    assert snapshot["dataset_id"] is None
    provenance = json.loads(snapshot["provenance_json"])
    assert provenance["source_id"] == source["id"] and provenance["query"]["tables"][0]["name"] == "Sales"
    assert provenance["columns"][0]["type"] == "decimal"
    assert client.get(f"/api/reports/{saved['report_id']}/export/csv").status_code == 200


def test_source_grants_are_required_for_members_and_revocation_is_immediate(client, admin):
    member = create_member(client)
    source, connector = fixture_source(client)
    token = client.cookies.get("duka_session")
    sign_in_member(client)
    assert client.get("/api/sources").json() == []
    assert "error" in call_tool(client, member, "query_database", {"source_id": source["id"], "query": query_plan()})
    assert connector.calls == []
    assert client.put(f"/api/admin/sources/{source['id']}/grants/{member['id']}", headers=HEADERS).status_code == 403
    client.cookies.set("duka_session", token)
    assert client.put(f"/api/admin/sources/{source['id']}/grants/{member['id']}", headers=HEADERS).status_code == 200
    assert call_tool(client, member, "query_database", {"source_id": source["id"], "query": query_plan()})["rows"]
    client.delete(f"/api/admin/sources/{source['id']}/grants/{member['id']}", headers=HEADERS)
    assert "error" in call_tool(client, member, "list_tables", {"source_id": source["id"]})


def test_limited_preview_is_replaced_by_complete_report_export(client, admin):
    source, _ = fixture_source(client, truncated=True)
    plan = query_plan(limit=1)
    preview = call_tool(client, admin, "query_database", {"source_id": source["id"], "query": plan})
    assert preview["truncated"] and len(preview["rows"]) == 1
    client.post("/api/subscription/login", headers=HEADERS)
    for _ in range(100):
        if client.get("/api/subscription").json()["connected"]:
            break
        time.sleep(0.01)
    report = call_tool(
        client,
        admin,
        "create_database_report",
        {"source_id": source["id"], "query": plan, "title": "Limited", "instructions": "", "template_id": "sales"},
    )
    assert report["status"] == "queued" and "error" not in report
    snapshot = client.app.state.db.one(
        "SELECT * FROM dataset_snapshots WHERE id=(SELECT snapshot_id FROM reports WHERE id=?)", (report["report_id"],)
    )
    assert len(json.loads(snapshot["rows_json"])) == 2
    assert len(client.get("/api/reports").json()) == 1
