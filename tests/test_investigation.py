"""Shared investigation context and audit reads under real company/database ACLs."""

import json

import pytest

from app.investigation import INVESTIGATION_INSTRUCTIONS
from app.provider import CodexRuntime
from conftest import HEADERS
from test_chat_controls import prepare, post
from test_claude_subscriptions import claude as claude_fixture, choose, connect_claude
from test_database_chat import call_tool
from test_excel_reports import subscribe
from test_member_data_access import CompanyDatabase, catalog, create_scoped


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_investigation_policy_reaches_new_and_resumed_native_sessions(client, admin, claude, monkeypatch, provider):
    cid = prepare(client, provider)
    contexts = []
    rpc = CodexRuntime.rpc

    async def capture(self, method, params=None):
        if method in ("thread/start", "thread/resume"):
            contexts.append((method, params))
        return await rpc(self, method, params)

    monkeypatch.setattr(CodexRuntime, "rpc", capture)
    for message in ("Kur u krijua regjistrimi i fundit?", "Kontrollo edhe burimet e tjera të lejuara."):
        result = post(client, cid, content=message)
        assert result.status_code == 200 and '"status": "completed"' in result.text
        if provider == "chatgpt":
            assert INVESTIGATION_INSTRUCTIONS in contexts[-1][1]["baseInstructions"]
            assert INVESTIGATION_INSTRUCTIONS in contexts[-1][1]["developerInstructions"]
        else:
            assert INVESTIGATION_INSTRUCTIONS in claude[-1].options.system_prompt
        client.portal.call(client.app.state.manager.release, admin["id"])
    if provider == "chatgpt":
        assert [method for method, _ in contexts] == ["thread/start", "thread/resume"]


@pytest.fixture(params=["sqlserver", "hana"])
def audit_database(client, admin, request):
    dialect = request.param
    source = client.post("/api/admin/sources", headers=HEADERS,
                         json={"name": "Audit fixture", "kind": "saphana" if dialect == "hana" else "sqlserver"}).json()
    connector = CompanyDatabase(client.app.state.settings, client.app.state.connectors.catalog, dialect=dialect)
    client.app.state.connectors.register(source["id"], connector)
    schema, prefix = ("B1A", "") if dialect == "hana" else ("dbo", "Alpha$")
    for name, definition in [
        ("AssetRegistry", "Id INTEGER,Name TEXT"),
        ("EventRules", "Entity TEXT,Enabled INTEGER,Operation TEXT"),
        ("EventHistory", "RecordId INTEGER,EventDate TEXT,Operation TEXT"),
    ]:
        connector.connection.execute(f'CREATE TABLE "{schema}"."{prefix}{name}"({definition})')
    connector.connection.execute(f'INSERT INTO "{schema}"."{prefix}EventRules" VALUES(?,?,?)',
                                 ("AssetRegistry", 0, "insert"))
    connector.connection.execute('CREATE TABLE dbo.GlobalAudit(Company TEXT,Secret TEXT)')
    connector.connection.execute("INSERT INTO dbo.GlobalAudit VALUES('Beta','restricted event')")
    unit = next(u for u in catalog(client, (source, connector))
                if u.get("schema") == schema and (dialect == "hana" or u.get("prefix") == "Alpha$"))
    member = create_scoped(client, source, [unit])
    return source, connector, member, schema, prefix


def plan(schema, table, columns):
    return {"tables": [{"schema": schema, "name": table, "alias": "r"}],
            "select": [{"column": "r." + c} for c in columns]}


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_empty_history_guides_further_investigation_and_config_stays_authorized(client, admin, claude, audit_database, provider):
    source, connector, member, schema, prefix = audit_database
    subscribe(client)
    if provider == "claude":
        connect_claude(client)
        choose(client, provider)
    tables = ["source_grants", "source_access_policies", "database_grants", "data_access_versions"]
    before = {t: client.app.state.db.all("SELECT * FROM " + t) for t in tables}
    args = {"source_id": source["id"], "database": "Finance"}
    history = call_tool(client, member, "query_database", {
        **args, "query": plan(schema, prefix + "EventHistory", ["RecordId", "EventDate"]),
    })
    assert history["rows"] == [] and history["truncated"] is False
    assert history["investigation"]["finding"] == "no_matching_rows"
    assert history["access_scope"]["all_companies"] is False
    config = call_tool(client, member, "query_database", {
        **args, "query": plan(schema, prefix + "EventRules", ["Entity", "Enabled", "Operation"]),
    })
    assert config["rows"] == [{"Entity": "AssetRegistry", "Enabled": 0, "Operation": "insert"}]
    assert "investigation" not in config  # The model interprets the evidence, not the backend.
    blocked = call_tool(client, member, "query_database", {
        **args, "query": plan("dbo", "GlobalAudit", ["Secret"]),
    })
    assert "error" in blocked and "rows" not in blocked and "investigation" not in blocked
    assert "restricted event" not in json.dumps(blocked)
    assert {t: client.app.state.db.all("SELECT * FROM " + t) for t in tables} == before
    assert not client.app.state.db.all("SELECT id FROM reports")


@pytest.mark.parametrize("tool", ["list_tables", "describe_table", "query_database"])
def test_ungranted_database_is_rejected_before_any_database_probe(client, audit_database, monkeypatch, tool):
    source, connector, member, schema, prefix = audit_database
    probes = []

    async def probe(database):
        probes.append(database)
        raise AssertionError("Must authorize before selecting a database")

    monkeypatch.setattr(connector, "in_database", probe)
    result = call_tool(client, member, tool, {
        "source_id": source["id"], "database": "Archive", "schema": schema,
        "table": prefix + "EventRules", "query": plan(schema, prefix + "EventRules", ["Entity"]),
    })
    assert "error" in result and "investigation" not in result
    assert probes == []


def test_restricted_audit_table_is_denied_before_metadata_reads(client, audit_database, monkeypatch):
    source, connector, member, _, _ = audit_database
    probes = []

    async def probe(*args, **kwargs):
        probes.append((args, kwargs))
        raise AssertionError("Must authorize before inspecting another company's table")

    monkeypatch.setattr(connector, "tables", probe)
    monkeypatch.setattr(connector, "describe", probe)
    result = call_tool(client, member, "describe_table", {
        "source_id": source["id"], "database": "Finance", "schema": "dbo", "table": "GlobalAudit",
    })
    assert "error" in result and "columns" not in result
    assert probes == []


def test_empty_catalog_is_not_a_global_absence_claim(client, audit_database):
    source, _, member, _, _ = audit_database
    result = call_tool(client, member, "list_tables", {
        "source_id": source["id"], "database": "Finance", "name_contains": "NoSuchHistory",
    })
    assert result["tables"] == []
    assert result["investigation"]["finding"] == "empty_catalog_page"
    assert result["investigation"]["catalog_has_more"] is False
    assert result["access_scope"]["all_companies"] is False
