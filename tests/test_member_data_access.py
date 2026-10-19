"""Exercise company enforcement against real SQL execution, not filtered mock results."""

import copy
from functools import partial
import json
import re
import sqlite3
from dataclasses import replace

import pytest

from app.connectors import SQLServerConnector, SourceNotConfigured
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_database_chat import call_tool


class CompanyDatabase(SQLServerConnector):
    def __init__(self, settings, catalog, dialect="sqlserver", database="Finance", connections=None):
        super().__init__(replace(settings, sqlserver_database=database, hana_database=database), catalog)
        self.dialect = dialect
        self.connections = connections if connections is not None else {}
        if database not in self.connections:
            c = sqlite3.connect(":memory:", check_same_thread=False)
            c.row_factory = sqlite3.Row
            for schema in ["dbo", "SAP", "B1A", "B1B"]:
                c.execute(f"ATTACH DATABASE ':memory:' AS {schema}")
            c.executescript("""
                CREATE TABLE dbo.Company(Name TEXT); INSERT INTO dbo.Company VALUES('Alpha'),('Beta');
                CREATE TABLE dbo."Alpha$Sales"(Id INTEGER,Amount INTEGER); INSERT INTO dbo."Alpha$Sales" VALUES(1,10),(2,20);
                CREATE TABLE dbo."Beta$Sales"(Id INTEGER,Amount INTEGER); INSERT INTO dbo."Beta$Sales" VALUES(1,9000);
                CREATE VIEW dbo."Alpha$AllCompanies" AS SELECT * FROM "Beta$Sales";
                CREATE TABLE SAP.T001(MANDT TEXT,BUKRS TEXT,BUTXT TEXT,KTOPL TEXT);
                INSERT INTO SAP.T001 VALUES('400','A','Alpha','CHART'),('400','B','Beta','CHART'),('500','A','Alpha copy','CHART'),('500','B','Beta copy','CHART');
                CREATE TABLE SAP.BSEG(MANDT TEXT,BUKRS TEXT,Id INTEGER,Amount INTEGER);
                INSERT INTO SAP.BSEG VALUES('400','A',1,10),('400','B',1,20),('500','A',1,30),('500','B',1,40);
                CREATE TABLE SAP.ClientOnly(MANDT TEXT,Amount INTEGER); INSERT INTO SAP.ClientOnly VALUES('400',99999);
                CREATE TABLE B1A.OADM(CompnyName TEXT); INSERT INTO B1A.OADM VALUES('Business One Alpha');
                CREATE TABLE B1B.OADM(CompnyName TEXT); INSERT INTO B1B.OADM VALUES('Business One Beta');
                CREATE TABLE B1A.Sales(Id INTEGER,Amount INTEGER); INSERT INTO B1A.Sales VALUES(1,50);
                CREATE TABLE B1B.Sales(Id INTEGER,Amount INTEGER); INSERT INTO B1B.Sales VALUES(1,99999);
            """)
            self.connections[database] = c
        self.connection = self.connections[database]
        self.calls = []

    async def databases(self, offset=0, limit=100):
        rows = [{"name": name, "is_default": int(name == "Finance")} for name in ["Archive", "Finance"]]
        return {
            "databases": rows[offset : offset + limit],
            "next_offset": offset + limit if len(rows) > offset + limit else None,
        }

    async def in_database(self, database):
        if database not in ["Archive", "Finance"]:
            raise SourceNotConfigured("Unavailable database")
        if database == self.settings.sqlserver_database:
            return self
        return CompanyDatabase(self.settings, self.catalog, self.dialect, database, self.connections)

    async def tables(self, offset=0, limit=100, kind="all", name_contains="", schema=None):
        rows = []
        for name in [schema] if schema else ["dbo", "SAP", "B1A", "B1B"]:
            for r in self.connection.execute(
                f"SELECT name,type FROM \"{name}\".sqlite_master WHERE type IN ('table','view') ORDER BY name"
            ):
                if name_contains not in r["name"] or (kind != "all" and r["type"] != kind):
                    continue
                rows.append(
                    {"schema_name": name, "name": r["name"], "kind": "BASE TABLE" if r["type"] == "table" else "VIEW"}
                )
        return {
            "tables": rows[offset : offset + limit],
            "next_offset": offset + limit if len(rows) > offset + limit else None,
        }

    async def schemas(self, offset=0, limit=100):
        return {
            "schemas": [
                {"schema_name": name, "table_count": 10, "view_count": 1} for name in ["dbo", "SAP", "B1A", "B1B"]
            ][offset : offset + limit],
            "next_offset": None,
        }

    async def describe(self, schema, table):
        safe_schema = schema.replace('"', '""')
        safe_table = table.replace('"', '""')
        fields = self.connection.execute(f'PRAGMA "{safe_schema}".table_info("{safe_table}")').fetchall()
        if not fields:
            raise ValueError("Missing table")
        return {
            "schema": schema,
            "table": table,
            "columns": [{"name": r["name"], "type": "int" if r["type"] == "INTEGER" else "nvarchar"} for r in fields],
            "relationships": [],
        }

    def _run_full(self, sql, parameters):
        self.calls.append((sql, copy.deepcopy(parameters)))
        if "FROM SYS.TABLES" in sql or "TABLE_NAME IN" in sql:
            names = ["T001", "OADM"] if self.dialect == "hana" else ["Company", "T001", "OADM"]
            return [
                {"schema_name": schema, "name": name}
                for schema, name in [("dbo", "Company"), ("SAP", "T001"), ("B1A", "OADM"), ("B1B", "OADM")]
                if name in names
            ]
        sql = re.sub(r"SELECT TOP \(\d+\)", "SELECT", sql)
        sql = re.sub(r"%\((\w+)\)s", r":\1", sql)
        bound = tuple(parameters.values()) if "?" in sql and isinstance(parameters, dict) else parameters
        return [dict(r) for r in self.connection.execute(sql, bound).fetchall()]

    def _run(self, sql, parameters, limit=501):
        return self._run_full(sql, parameters)[:limit]


@pytest.fixture
def database(client, admin):
    source = client.post(
        "/api/admin/sources", headers=HEADERS, json={"name": "Company fixture", "kind": "sqlserver"}
    ).json()
    instance = CompanyDatabase(client.app.state.settings, client.app.state.connectors.catalog)
    client.app.state.connectors.register(source["id"], instance)
    return source, instance


def catalog(client, database):
    source, _ = database
    response = client.get(f"/api/admin/access-catalog/{source['id']}/companies?database=Finance")
    assert response.status_code == 200, response.text
    return response.json()["companies"]


def selection(source, units=(), database="Finance", all_companies=False):
    return {
        "source_id": source["id"],
        "database": database,
        "all_companies": all_companies,
        "company_ids": [u["id"] for u in units],
    }


def create_scoped(client, source, units=(), all_companies=False):
    response = client.post(
        "/api/admin/users",
        headers=HEADERS,
        json={
            "name": "Member",
            "email": "member@example.com",
            "password": "member-long-password",
            "role": "manager",
            "database_access": {"databases": [selection(source, units, all_companies=all_companies)]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def query(schema="dbo", table="Alpha$Sales", **extra):
    return {
        "tables": [{"schema": schema, "name": table, "alias": "s"}],
        "metrics": [{"function": "sum", "column": "s.Amount", "alias": "total"}],
        **extra,
    }


def read(client, user, source, plan=None, database="Finance", operation="query"):
    return client.portal.call(
        partial(
            client.app.state.connectors.database_call,
            user["id"],
            source["id"],
            operation,
            database=database,
            query=plan or query(),
        )
    )


def test_create_member_atomically_with_database_and_company_checkboxes(client, admin, database):
    source, instance = database
    units = catalog(client, database)
    assert len(units) == 8
    alpha = next(u for u in units if u["kind"] == "table_prefix" and u["prefix"] == "Alpha$")
    member = create_scoped(client, source, [alpha])
    saved = client.get(f"/api/admin/users/{member['id']}/access").json()
    assert saved["databases"] == [selection(source, [alpha])]
    assert saved["all_access"] is False
    sign_in_member(client)
    inventory = call_tool(client, member, "discover_databases", {})
    assert [d["name"] for d in inventory["sources"][0]["databases"]] == ["Finance"]
    assert read(client, member, source)["rows"] == [{"total": 30}]
    for plan in [query(table="Beta$Sales"), query(table="Alpha$AllCompanies"), query(schema="B1B", table="Sales")]:
        with pytest.raises(SourceNotConfigured):
            read(client, member, source, plan)
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, database="Archive")
    assert client.get("/api/admin/access-catalog").status_code == 403
    assert (
        client.put(f"/api/admin/users/{member['id']}/access", headers=HEADERS, json={"databases": []}).status_code
        == 403
    )
    tables = client.portal.call(
        partial(client.app.state.connectors.database_call, member["id"], source["id"], "tables", database="Finance")
    )
    assert [t["name"] for t in tables["tables"]] == ["Alpha$Sales"]


@pytest.mark.parametrize("dialect", ["sqlserver", "hana"])
def test_sap_pair_scopes_are_applied_before_aggregation_and_joins(client, admin, database, dialect):
    source, instance = database
    instance.dialect = dialect
    units = catalog(client, database)
    pair = [u for u in units if u["kind"] == "sap_fi" and (u["client"], u["company"]) in [("400", "A"), ("500", "B")]]
    assert len(pair) == 2
    member = create_scoped(client, source, pair)
    result = read(client, member, source, query("SAP", "BSEG"))
    assert result["rows"] == [{"total": 50}]
    assert read(client, member, source, query("SAP", "BSEG"), operation="report_query")["rows"] == [{"total": 50}]
    # An explicit excluded-company filter narrows the authorized rows to none.
    excluded = query(
        "SAP",
        "BSEG",
        filters=[
            {"column": "s.MANDT", "operator": "eq", "value": "400"},
            {"column": "s.BUKRS", "operator": "eq", "value": "B"},
        ],
    )
    assert read(client, member, source, excluded)["rows"] == [{"total": None}]
    joined = query(
        "SAP",
        "BSEG",
        tables=[{"schema": "SAP", "name": "BSEG", "alias": "s"}, {"schema": "SAP", "name": "BSEG", "alias": "other"}],
        joins=[{"left": "s.Id", "right": "other.Id", "kind": "left"}],
        metrics=[{"function": "sum", "column": "other.Amount", "alias": "total"}],
    )
    assert read(client, member, source, joined)["rows"] == [{"total": 100}]
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, query("SAP", "ClientOnly"))
    sql, params = instance.calls[-1]
    assert "99999" not in str(params)


def test_company_schema_access_isolated_and_all_database_access_is_explicit(client, admin, database):
    source, _ = database
    units = catalog(client, database)
    alpha = next(u for u in units if u["kind"] == "schema" and u["schema"] == "B1A")
    member = create_scoped(client, source, [alpha])
    assert read(client, member, source, query("B1A", "Sales"))["rows"] == [{"total": 50}]
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, query("B1B", "Sales"))
    assert (
        client.put(
            f"/api/admin/users/{member['id']}/access",
            headers=HEADERS,
            json={"databases": [selection(source, all_companies=True)]},
        ).status_code
        == 200
    )
    assert read(client, member, source, query("B1B", "Sales"))["rows"] == [{"total": 99999}]
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, database="Archive")


@pytest.mark.parametrize("role", ["president", "devs"])
def test_president_and_devs_have_all_database_company_access_without_grants(client, admin, database, role):
    source, _ = database
    member = client.post(
        "/api/admin/users",
        headers=HEADERS,
        json={"name": "Member", "email": "member@example.com", "password": "member-long-password", "role": role},
    ).json()
    assert not client.app.state.db.all("SELECT * FROM source_grants WHERE user_id=?", (member["id"],))
    assert [s["id"] for s in client.app.state.connectors.accessible_sources(member["id"])] == [source["id"]]
    assert read(client, member, source, query(table="Beta$Sales"), database="Archive")["rows"] == [{"total": 9000}]
    sign_in_member(client)
    assert client.get("/api/admin/users").status_code == (200 if role == "devs" else 403)


def test_grant_validation_rejects_unknown_choices_and_does_not_create_partial_user(client, admin, database):
    source, _ = database
    invalid = [
        selection(source, [{"id": "invented-company"}]),
        selection(source, database="Unknown", all_companies=True),
        selection(source),
    ]
    for entry in invalid:
        response = client.post(
            "/api/admin/users",
            headers=HEADERS,
            json={
                "name": "Rejected",
                "email": "reject@example.com",
                "password": "member-long-password",
                "database_access": {"databases": [entry]},
            },
        )
        assert response.status_code == 422, response.text
        assert not client.app.state.db.one("SELECT id FROM users WHERE email='reject@example.com'")
    member = create_member(client)
    response = client.put(
        f"/api/admin/users/{member['id']}/access",
        headers=HEADERS,
        json={"databases": [], "preserve_legacy_source_ids": [source["id"]]},
    )
    assert response.status_code == 422


def test_revoking_company_grants_during_read_discards_result(client, admin, database, monkeypatch):
    source, instance = database
    member = create_scoped(client, source, all_companies=True)
    original = instance.query

    async def revoke(query, **kwargs):
        result = await original(query, **kwargs)
        instance_db = client.app.state.db
        instance_db.execute("DELETE FROM database_grants WHERE user_id=?", (member["id"],))
        return result

    monkeypatch.setattr(instance, "query", revoke)
    with pytest.raises(SourceNotConfigured):
        read(client, member, source)


def test_changing_company_grants_invalidates_calculation_exports(client, admin, database):
    from app.calculations import CalculationService
    from app.db import now, uid

    source, _ = database
    member = create_scoped(client, source, all_companies=True)
    state = client.app.state
    chat = uid()
    stamp = read(client, member, source)["access_stamp"]
    state.db.execute(
        "INSERT INTO conversations VALUES(?,?,?,?,?,?,?)",
        (chat, member["id"], "Scoped calculation", None, None, now(), now()),
    )
    provenance = {
        "plan": {"inputs": [{"kind": "database", "name": "ledger", "source_id": source["id"], "database": "Finance"}]},
        "inputs": [{"name": "ledger", "database": "Finance", "access_stamp": stamp}],
    }
    identifier = uid()
    state.db.execute(
        "INSERT INTO calculation_runs VALUES(?,?,?,?,?,?,?,?)",
        (identifier, member["id"], chat, json.dumps(provenance), "{}", "{}", now(), "complete"),
    )
    service = CalculationService(state.settings, state.db, state.connectors, state.attachments)
    service.owned(member["id"], chat, identifier)
    alpha = next(u for u in catalog(client, database) if u["kind"] == "table_prefix" and u["prefix"] == "Alpha$")
    assert (
        client.put(
            f"/api/admin/users/{member['id']}/access", headers=HEADERS, json={"databases": [selection(source, [alpha])]}
        ).status_code
        == 200
    )
    with pytest.raises(ValueError, match="access changed"):
        service.owned(member["id"], chat, identifier)


@pytest.fixture
def claude(client, monkeypatch):
    from test_claude_subscriptions import claude as fixture

    return fixture.__wrapped__(client, monkeypatch)


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_both_provider_report_tools_export_only_granted_companies(client, admin, database, claude, provider):
    import io
    from openpyxl import load_workbook
    from test_claude_subscriptions import connect_claude, choose
    from test_excel_reports import subscribe, wait_report

    source, _ = database
    alpha = next(u for u in catalog(client, database) if u["kind"] == "table_prefix" and u["prefix"] == "Alpha$")
    member = create_scoped(client, source, [alpha])
    sign_in_member(client)
    subscribe(client)
    if provider == "claude":
        connect_claude(client)
        choose(client, provider)
    result = call_tool(
        client,
        member,
        "create_database_report",
        {
            "source_id": source["id"],
            "database": "Finance",
            "query": query(),
            "title": "Allowed company only",
            "instructions": "Export the requested total.",
        },
    )
    assert "report_id" in result, result
    report = wait_report(client, result["report_id"])
    assert report["status"] == "completed", report
    data = client.get(f"/api/reports/{result['report_id']}/export/json").json()
    assert data["provenance"]["access_scope"]["companies"][0]["prefix"] == "Alpha$"
    binary = client.get(f"/api/reports/{result['report_id']}/export/xlsx")
    assert binary.status_code == 200
    book = load_workbook(io.BytesIO(binary.content), read_only=True, data_only=True)
    values = [cell for sheet in book for row in sheet.values for cell in row]
    assert 30 in values and 9000 not in values
    blocked = call_tool(
        client,
        member,
        "query_database",
        {"source_id": source["id"], "database": "Finance", "query": query(table="Beta$Sales")},
    )
    assert "error" in blocked and "rows" not in blocked


def test_curated_scripts_cannot_bypass_database_company_grants(client, admin, database):
    source, _ = database
    member = create_scoped(client, source, all_companies=True)
    dataset = {"source_id": source["id"], "enabled": 1, "parameters_schema_json": "{}", "query_key": "unrestricted"}
    with pytest.raises(SourceNotConfigured, match="no verified access boundary"):
        client.portal.call(partial(client.app.state.connectors.fetch, dataset, {}, user_id=member["id"]))


def test_existing_source_grants_survive_until_explicitly_replaced(client, admin, database):
    source, _ = database
    member = create_member(client)
    assert client.put(f"/api/admin/sources/{source['id']}/grants/{member['id']}", headers=HEADERS).status_code == 422
    client.app.state.db.execute("INSERT INTO source_grants VALUES(?,?)", (source["id"], member["id"]))
    assert client.put(f"/api/admin/sources/{source['id']}/grants/{member['id']}", headers=HEADERS).status_code == 200
    assert read(client, member, source, database="Archive")["rows"] == [{"total": 30}]
    assert (
        client.patch(f"/api/admin/users/{member['id']}", headers=HEADERS, json={"role": "president"}).status_code == 200
    )
    assert (
        client.patch(f"/api/admin/users/{member['id']}", headers=HEADERS, json={"role": "manager"}).status_code == 200
    )
    assert read(client, member, source, database="Archive")["rows"] == [{"total": 30}]
    assert (
        client.put(
            f"/api/admin/users/{member['id']}/access",
            headers=HEADERS,
            json={"databases": [selection(source, all_companies=True)]},
        ).status_code
        == 200
    )
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, database="Archive")
    assert client.delete(f"/api/admin/sources/{source['id']}/grants/{member['id']}", headers=HEADERS).status_code == 200
    saved = client.get(f"/api/admin/users/{member['id']}/access").json()
    assert saved["databases"] == [] and saved["legacy_source_ids"] == []


def test_overlapping_company_prefixes_cannot_read_a_longer_company_name(client, admin, database):
    source, instance = database
    instance.connection.executescript("""INSERT INTO dbo.Company VALUES('Alpha$Subsidiary');
        CREATE TABLE dbo."Alpha$Subsidiary$Sales"(Id INTEGER,Amount INTEGER);
        INSERT INTO dbo."Alpha$Subsidiary$Sales" VALUES(1,99999);""")
    alpha = next(u for u in catalog(client, database) if u["kind"] == "table_prefix" and u["prefix"] == "Alpha$")
    member = create_scoped(client, source, [alpha])
    assert read(client, member, source)["rows"] == [{"total": 30}]
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, query(table="Alpha$Subsidiary$Sales"))


def test_database_only_grant_does_not_allow_cross_database_views(client, admin, database):
    source, _ = database
    member = create_scoped(client, source, all_companies=True)
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, query(table="Alpha$AllCompanies"))


def test_restore_of_old_grants_cannot_hide_an_inflight_access_change(client, admin, database, monkeypatch):
    from app.data_access import DataAccess

    source, instance = database
    member = create_scoped(client, source, all_companies=True)
    old = instance.query

    async def changed_twice(query, **kwargs):
        result = await old(query, **kwargs)
        with client.app.state.db.connect() as c:
            DataAccess.bump(c, member["id"])
            DataAccess.bump(c, member["id"])
        return result

    monkeypatch.setattr(instance, "query", changed_twice)
    with pytest.raises(SourceNotConfigured, match="changed during"):
        read(client, member, source)


def test_a_chart_column_is_not_a_company_boundary_for_financial_tables(client, admin, database):
    source, instance = database
    instance.connection.executescript("""CREATE TABLE SAP.ChartLedger(MANDT TEXT,KTOPL TEXT,Amount INTEGER);
        INSERT INTO SAP.ChartLedger VALUES('400','CHART',99999);""")
    company = next(
        u for u in catalog(client, database) if u["kind"] == "sap_fi" and u["client"] == "400" and u["company"] == "A"
    )
    member = create_scoped(client, source, [company])
    with pytest.raises(SourceNotConfigured):
        read(client, member, source, query("SAP", "ChartLedger"))
