import json

from app.config import Settings
from app.connectors import ConnectorRegistry, DatabaseUnavailable
from app.db import Database
from app.sales_discovery import discover_sales, ROLES
from conftest import HEADERS
from test_database_chat import call_tool, fixture_source, query_plan
from test_excel_reports import subscribe, wait_report

GUID = "437dbf0e-84ff-417a-965d-ed2bb9650972"


class SalesFixture:
    def __init__(self, companies=("Gotech Live",), broken=None):
        self.candidates = [{"schema_name": "dbo", "name": f"{company}${role}${GUID}"} for company in companies for role in ROLES]
        self.candidates.append({"schema_name": "dbo", "name": "Gotech-1$SalesLinesView$" + GUID})
        self.candidates.append({"schema_name": "dbo", "name": "Gotech Live$Sales Invoice Line$ae35fa8c-83f9-4524-a2af-fa688f991674"})
        self.probed = []
        self.broken = broken

    def _run(self, sql, parameters):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            assert "TABLE_TYPE='BASE TABLE'" in sql
            return self.candidates
        assert sql.startswith("SELECT TOP (0)")
        self.probed.append(sql)
        if self.broken and self.broken in sql:
            raise DatabaseUnavailable("Unavailable object", code=208)
        return []

    async def describe(self, schema, table):
        role = table.split("$")[1]
        required = ROLES[role][1] if table.endswith(GUID) or table.count("$") == 1 else {"Document No_"}
        return {"schema": schema, "table": table, "columns": [{"name": n, "type": "nvarchar"} for n in required]}


async def test_sales_discovery_selects_the_actual_readable_company_and_ignores_stale_views_and_extensions():
    fixture = SalesFixture()
    result = await discover_sales(fixture)
    assert result["recommended_company"] == "Gotech Live"
    assert not result["requires_company_choice"]
    assert set(result["companies"][0]["tables"]) == {"invoice_header", "invoice_line", "credit_header", "credit_line"}
    assert len(fixture.probed) == 4
    assert all("Gotech-1" not in probe for probe in fixture.probed)
    assert result["base_currency"] == "ALL" and result["timezone"] == "Europe/Tirane"


async def test_multiple_companies_are_discovered_without_forcing_a_choice_and_explicit_scope_is_not_changed():
    fixture = SalesFixture(("Gotech Live", "Another Company"))
    result = await discover_sales(fixture)
    assert result["multiple_companies"] and not result["requires_company_choice"] and result["recommended_company"] is None
    assert (await discover_sales(fixture, "Another Company"))["recommended_company"] == "Another Company"
    missing = await discover_sales(fixture, "Gotech-1")
    assert missing["companies"] == [] and missing["recommended_company"] is None


async def test_legacy_company_tables_without_app_guid_are_also_discovered():
    fixture = SalesFixture()
    fixture.candidates.extend({"schema_name": "dbo", "name": f"Historical Company${role}"} for role in ROLES)
    result = await discover_sales(fixture)
    assert {company["company"] for company in result["companies"]} == {"Gotech Live", "Historical Company"}
    assert all(company["invoice_tables_complete"] for company in result["companies"])


async def test_unreadable_invoice_table_is_not_recommended():
    result = await discover_sales(SalesFixture(broken="$Sales Invoice Line$"))
    assert result["recommended_company"] is None
    assert result["unavailable_tables"][0]["database_error_code"] == 208


def test_named_gotech_environment_is_authoritative_only_for_gotech_and_never_mixes_profiles(tmp_path):
    env = tmp_path / ".env"
    env.write_text('SQLSERVER_HOST=generic\nSQLSERVER_USER=generic-user\nSQLSERVER_PASSWORD=generic-password\nSQLSERVER_DATABASE=generic-db\nGOTECH_SQLSERVER_HOST=gotech\nGOTECH_SQLSERVER_PORT=1444\nGOTECH_SQLSERVER_USER=gotech-user\nGOTECH_SQLSERVER_PASSWORD="literal#secret"\nGOTECH_SQLSERVER_DATABASE=GoTechBC15MG\n')
    settings = Settings(data_dir=tmp_path / "data", env_file=env)
    settings.prepare()
    db = Database(settings.data_dir / "application.sqlite3")
    db.initialize()
    for identifier, name in [("g", "GoTech"), ("o", "Other")]:
        db.execute("INSERT INTO data_sources(id,name,kind,created_at) VALUES(?,?,'sqlserver','now')", (identifier, name))
    registry = ConnectorRegistry(settings, db)
    selected = registry.source_settings("g")
    assert selected.sqlserver_database == "GoTechBC15MG" and selected.sqlserver_port == "1444"
    assert selected.sqlserver_password == "literal#secret"
    assert registry.source_settings("o").sqlserver_host == "generic"
    assert "literal#secret" not in json.dumps(registry.public_source(db.one("SELECT * FROM data_sources WHERE id='g'")))
    env.write_text('SQLSERVER_USER=generic-user\nGOTECH_SQLSERVER_HOST=gotech\n')
    partial = registry.source_settings("g")
    assert partial.sqlserver_host == "gotech" and partial.sqlserver_user == "" and partial.sqlserver_database == ""


def test_sales_tools_preserve_authorization_and_208_has_actionable_recovery(client, admin, monkeypatch):
    source, connector = fixture_source(client)

    async def catalog(company=None):
        return await discover_sales(SalesFixture(), company)

    monkeypatch.setattr(connector, "sales_catalog", catalog)
    assert call_tool(client, admin, "discover_sales", {"source_id": source["id"]})["recommended_company"] == "Gotech Live"

    async def broken(query):
        raise DatabaseUnavailable("Unavailable view", code=208)

    monkeypatch.setattr(connector, "query", broken)
    result = call_tool(client, admin, "query_database", {"source_id": source["id"], "query": query_plan()})
    assert result["database_error_code"] == 208 and "discover_sales" in result["recovery"]


def test_successful_empty_period_still_creates_an_excel_report(client, admin, monkeypatch):
    source, connector = fixture_source(client)
    original = connector.report_query

    async def empty(query):
        result = await original(query)
        result["rows"], result["row_count"] = [], 0
        return result

    monkeypatch.setattr(connector, "report_query", empty)
    subscribe(client)
    result = client.post("/api/reports", headers=HEADERS,
                         json={"source_id": source["id"], "query": query_plan(), "title": "Empty period"}).json()
    assert wait_report(client, result["id"])["status"] == "completed"
    assert client.get(f"/api/reports/{result['id']}/export/xlsx").status_code == 200
