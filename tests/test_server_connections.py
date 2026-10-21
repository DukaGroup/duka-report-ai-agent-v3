import asyncio

import pytest

from app.connectors import ConnectorRegistry, SourceNotConfigured
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_database_chat import call_tool, fixture_source, query_plan
from test_excel_reports import subscribe, wait_report
from test_sqlserver import Driver, connector


def connection(name="Finance server", **changes):
    return {"name": name, "kind": "sqlserver", "SQLSERVER_HOST": name + ".internal", "SQLSERVER_PORT": 1433,
            "SQLSERVER_USER": "report-reader", "SQLSERVER_PASSWORD": "private#test-password", **changes}


def test_independent_server_credentials_without_database_even_when_generic_env_exists(client, admin):
    state = client.app.state
    state.settings.sqlserver_host = "global-host"
    state.settings.sqlserver_user = "global-user"
    state.settings.sqlserver_password = "global-secret"
    state.settings.sqlserver_database = "GlobalDatabase"
    for name in ("Finance", "Retail", "Archive"):
        response = client.post("/api/admin/sources", headers=HEADERS, json=connection(name))
        assert response.status_code == 201, response.text
        source = response.json()
        assert source["configuration_origin"] == "saved" and source["database_scope"] == "all"
        assert source["status"] == "not_checked" and not source["connection_fields"]["SQLSERVER_DATABASE"]
        settings = state.connectors.source_settings(source["id"])
        assert settings.sqlserver_host == name + ".internal" and settings.sqlserver_database == ""
        assert settings.sqlserver_password == "private#test-password"
        assert "private#test-password" not in response.text and name + ".internal" not in response.text
    assert len(state.connectors.accessible_sources(admin["id"])) == 3


def test_database_can_be_added_preserved_and_cleared_without_erasing_other_credentials(client, admin):
    source = client.post("/api/admin/sources", headers=HEADERS, json=connection(SQLSERVER_DATABASE="Finance")).json()
    path = "/api/admin/sources/" + source["id"]
    assert client.patch(path, headers=HEADERS, json={"name": source["name"], "kind": "sqlserver"}).status_code == 200
    assert client.app.state.connectors.source_settings(source["id"]).sqlserver_database == "Finance"
    for value in ("", None, "   "):
        response = client.patch(path, headers=HEADERS, json={"name": source["name"], "kind": "sqlserver", "SQLSERVER_DATABASE": value})
        assert response.status_code == 200, response.text
        assert response.json()["database_scope"] == "default"
        settings = client.app.state.connectors.source_settings(source["id"])
        assert settings.sqlserver_database == "Finance" and settings.sqlserver_password == "private#test-password"
    response = client.patch(path, headers=HEADERS, json={"discover_databases": True})
    assert response.status_code == 200 and response.json()["database_scope"] == "all"
    settings = client.app.state.connectors.source_settings(source["id"])
    assert settings.sqlserver_database == "" and settings.sqlserver_password == "private#test-password"
    response = client.patch(path, headers=HEADERS, json={"name": source["name"], "kind": "sqlserver", "SQLSERVER_DATABASE": "Other"})
    assert response.status_code == 200 and response.json()["database_scope"] == "default"


def test_legacy_first_saved_connection_without_env_keeps_credentials_on_upgrade(client, admin):
    source = client.post("/api/admin/sources", headers=HEADERS, json=connection()).json()
    state = client.app.state
    state.db.execute("UPDATE data_sources SET credential_profile='legacy' WHERE id=?", (source["id"],))
    restarted = ConnectorRegistry(state.settings, state.db)
    effective = restarted.source_settings(source["id"])
    assert effective.sqlserver_host == "Finance server.internal" and effective.sqlserver_password == "private#test-password"
    assert state.db.one("SELECT credential_profile FROM data_sources WHERE id=?", (source["id"],))["credential_profile"] == "saved"


def test_new_saved_connection_is_not_hijacked_by_env_profiles_added_later(client, admin, tmp_path):
    source = client.post("/api/admin/sources", headers=HEADERS, json=connection("Finance")).json()
    state = client.app.state
    env = tmp_path / '.env'
    env.write_text(state.connectors.secrets.environment.path.read_text() + "\nSQLSERVER_HOST=global-host\nSQLSERVER_USER=global-user\nSQLSERVER_PASSWORD=global-secret\nFINANCE_SQLSERVER_HOST=named-host\nFINANCE_SQLSERVER_USER=named-user\nFINANCE_SQLSERVER_PASSWORD=named-secret\n")
    state.settings.env_file = env
    restarted = ConnectorRegistry(state.settings, state.db)
    effective = restarted.source_settings(source["id"])
    assert effective.sqlserver_host == "Finance.internal" and effective.sqlserver_password == "private#test-password"


async def test_server_only_check_uses_master_for_catalog_and_validates_login_without_a_database():
    driver = Driver([{"name": "Finance"}, {"name": "Retail"}])
    database = connector(driver)
    database.settings.sqlserver_database = ""
    assert database.missing() == []
    await database.check()
    assert driver.options["database"] == "master"
    assert "sys.databases" in driver.executed[0] and "HAS_DBACCESS" in driver.executed[0]
    assert driver.closed and driver.rolled_back
    with pytest.raises(SourceNotConfigured, match="Select a database"):
        await database.fetch("connection_check", {})


async def test_server_only_connection_can_select_a_discovered_database_without_mutating_default():
    driver = Driver([{"name": "Finance"}])
    original = connector(driver)
    original.settings.sqlserver_database = ""
    selected = await original.in_database("Finance")
    assert selected.settings.sqlserver_database == "Finance" and original.settings.sqlserver_database == ""
    driver.rows, driver.position = [{"connected": 1}], 0
    await selected.check()
    assert driver.options["database"] == "Finance"


def test_server_inventory_and_business_queries_require_a_discovered_target(client, admin, monkeypatch):
    source = client.post("/api/admin/sources", headers=HEADERS, json=connection()).json()
    state = client.app.state
    database = state.connectors.resolve_connector(source["id"])

    async def inventory(offset=0, limit=100):
        assert offset in (0, 100)
        return {"databases": [{"name": "Finance" if offset == 0 else "Retail", "is_default": 0}], "next_offset": 100 if offset == 0 else None}

    monkeypatch.setattr(database, "databases", inventory)
    rows = call_tool(client, admin, "discover_databases", {})
    assert [d["name"] for d in rows["sources"][0]["databases"]] == ["Finance", "Retail"]
    page = client.get(f"/api/admin/sources/{source['id']}/databases?offset=100", headers=HEADERS)
    assert page.status_code == 200 and page.json()["databases"][0]["name"] == "Retail"
    error = call_tool(client, admin, "list_tables", {"source_id": source["id"]})
    assert "Select a database" in error["error"]
    assert client.get(f"/api/admin/sources/{source['id']}/databases?offset=-1", headers=HEADERS).status_code == 422


def test_disconnect_survives_registry_restart_reconnect_restores_only_that_source(client, admin, monkeypatch):
    first, _ = fixture_source(client)
    second, _ = fixture_source(client)
    state = client.app.state
    result = client.post(f"/api/admin/sources/{first['id']}/disconnect", headers=HEADERS)
    assert result.status_code == 200 and result.json()["status"] == "disconnected"
    assert result.json()["enabled"] == 0
    assert [s["id"] for s in state.connectors.accessible_sources(admin["id"])] == [second["id"]]
    restarted = ConnectorRegistry(state.settings, state.db)
    assert first["id"] not in restarted.connectors
    assert state.db.one("SELECT status FROM data_sources WHERE id=?", (first["id"],))["status"] == "disconnected"
    assert "error" in call_tool(client, admin, "query_database", {"source_id": first["id"], "query": query_plan()})

    async def check(source_id):
        state.connectors.status(source_id, "connected")

    monkeypatch.setattr(state.connectors, "check", check)
    response = client.post(f"/api/admin/sources/{first['id']}/connect", headers=HEADERS)
    assert response.status_code == 200 and response.json()["enabled"] == 1
    assert response.json()["status"] == "connected"
    assert len(state.connectors.accessible_sources(admin["id"])) == 2


def test_disconnect_during_query_discards_its_result(client, admin, monkeypatch):
    source, database = fixture_source(client)
    state = client.app.state

    async def race():
        started, finish = asyncio.Event(), asyncio.Event()

        async def delayed(query):
            started.set()
            await finish.wait()
            return {"rows": [{"secret_value": 1}]}

        monkeypatch.setattr(database, "query", delayed)
        task = asyncio.create_task(state.connectors.database_call(admin["id"], source["id"], "query", query=query_plan()))
        await started.wait()
        state.db.execute("UPDATE data_sources SET enabled=0,status='disconnected' WHERE id=?", (source["id"],))
        finish.set()
        with pytest.raises(SourceNotConfigured):
            await task
        assert state.db.one("SELECT status FROM data_sources WHERE id=?", (source["id"],))["status"] == "disconnected"

    client.portal.call(race)


def test_removing_connection_cascades_secrets_and_grants_but_preserves_report_and_other_connections(client, admin):
    subscribe(client)
    first, _ = fixture_source(client)
    second, _ = fixture_source(client)
    state = client.app.state
    # Use the production encrypted store, while retaining the fixture read connector.
    credentials = state.connectors.secrets.encrypt(first["id"], {k:str(v) for k,v in connection().items() if k.startswith("SQLSERVER_")})
    state.db.execute("INSERT INTO source_credentials VALUES(?,?,'now')", (first["id"], credentials))
    member = create_member(client)
    state.db.execute("INSERT INTO source_grants VALUES(?,?)", (first["id"], member["id"]))
    dataset = client.post("/api/admin/datasets", headers=HEADERS, json={"source_id": first["id"], "name": "Legacy sales", "query_key": "connection_check"}).json()
    result = client.post("/api/reports", headers=HEADERS, json={"source_id": first["id"], "query": query_plan(), "title": "Saved sales"}).json()
    report = wait_report(client, result["id"])
    assert report["status"] == "completed"
    state.db.execute("UPDATE dataset_snapshots SET dataset_id=? WHERE id=?", (dataset["id"], report["snapshot_id"]))
    original = client.get(f"/api/reports/{report['id']}/export/xlsx").content
    response = client.delete(f"/api/admin/sources/{first['id']}", headers=HEADERS)
    assert response.status_code == 200
    assert not state.db.one("SELECT * FROM source_credentials WHERE source_id=?", (first["id"],))
    assert not state.db.one("SELECT * FROM source_grants WHERE source_id=?", (first["id"],))
    retained = state.db.one("SELECT * FROM datasets WHERE id=?", (dataset["id"],))
    assert retained["source_id"] is None and retained["enabled"] == 0
    assert state.db.one("SELECT * FROM dataset_snapshots WHERE id=?", (report["snapshot_id"],))
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").content == original
    assert state.db.one("SELECT id FROM data_sources WHERE id=?", (second["id"],))


def test_removing_default_connection_does_not_rebind_env_to_another_connection(client, admin):
    state = client.app.state
    state.settings.sqlserver_host = "global-host"
    first = client.post("/api/admin/sources", headers=HEADERS, json={"name": "Legacy environment", "kind": "sqlserver"}).json()
    second = client.post("/api/admin/sources", headers=HEADERS, json=connection("Separate")).json()
    assert client.delete(f"/api/admin/sources/{first['id']}", headers=HEADERS).status_code == 200
    restarted = ConnectorRegistry(state.settings, state.db)
    assert restarted.source_settings(second["id"]).sqlserver_host == "Separate.internal"


def test_connection_lifecycle_and_catalog_are_admin_only_and_csrf_protected(client, admin):
    source = client.post("/api/admin/sources", headers=HEADERS, json=connection()).json()
    path = f"/api/admin/sources/{source['id']}"
    assert client.post(path + "/disconnect").status_code == 403
    assert client.delete(path).status_code == 403
    create_member(client)
    sign_in_member(client)
    for suffix in ("/disconnect", "/connect"):
        assert client.post(path + suffix, headers=HEADERS).status_code == 403
    assert client.get(path + "/databases", headers=HEADERS).status_code == 403
    assert client.delete(path, headers=HEADERS).status_code == 403
