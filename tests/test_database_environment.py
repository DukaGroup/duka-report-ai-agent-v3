import json

import pytest

from app.config import Settings
from app.connectors import ConnectorRegistry, DatabaseUnavailable, SQLServerConnector
from app.db import Database, now
from conftest import HEADERS
from test_source_credentials import source_input
from test_sqlserver import Driver


def environment_file(path, host="env-host", password="env$literal${PASSWORD}#secret"):
    path.write_text(
        f"SQLSERVER_HOST={host}\nSQLSERVER_PORT=1437\nSQLSERVER_USER=env-user\nSQLSERVER_PASSWORD='{password}'\nSQLSERVER_DATABASE=env-database\n"
    )


def test_backend_reads_dotenv_without_expanding_password_or_exposing_it(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    environment_file(path)
    monkeypatch.setenv("PASSWORD", "should-not-be-interpolated")
    settings = Settings(env_file=path, sqlserver_host="stale-container-host")
    resolved = settings.database_environment()
    assert resolved.sqlserver_host == "env-host"
    assert resolved.sqlserver_port == "1437"
    assert resolved.sqlserver_password == "env$literal${PASSWORD}#secret"
    assert "env-host" not in repr(resolved) and "secret" not in repr(resolved)


def test_dotenv_overrides_legacy_saved_settings_and_blank_edits_preserve_both(client, admin, tmp_path):
    source = client.post("/api/admin/sources", json=source_input(), headers=HEADERS).json()
    state = client.app.state
    state.db.execute("UPDATE data_sources SET credential_profile='legacy' WHERE id=?", (source["id"],))
    path = tmp_path / ".env"
    environment_file(path)
    path.write_text(path.read_text() + state.connectors.secrets.environment.path.read_text())
    state.settings.env_file = path
    registry = ConnectorRegistry(state.settings, state.db)
    state.connectors = registry
    state.manager.connectors = registry
    connector = registry.resolve_connector(source["id"])
    assert connector.settings.sqlserver_host == "env-host"
    assert connector.settings.sqlserver_password == "env$literal${PASSWORD}#secret"
    response = client.get("/api/admin/sources").json()[0]
    assert response["configuration_origin"] == "environment"
    assert all(response["connection_fields"].values())
    assert "secret" not in json.dumps(response)
    client.patch(
        f"/api/admin/sources/{source['id']}", headers=HEADERS, json={"name": "Metadata edit", "kind": "sqlserver"}
    )
    assert registry.source_settings(source["id"]).sqlserver_password == "env$literal${PASSWORD}#secret"
    assert registry.secrets.load(source["id"])["SQLSERVER_PASSWORD"] == "private-password"


def test_changed_dotenv_refreshes_existing_connector_and_missing_fields_do_not_mix(client, admin, tmp_path):
    source = client.post("/api/admin/sources", json=source_input(), headers=HEADERS).json()
    state = client.app.state
    state.db.execute("UPDATE data_sources SET credential_profile='SQLSERVER' WHERE id=?", (source["id"],))
    path = tmp_path / ".env"
    environment_file(path)
    state.settings.env_file = path
    registry = state.connectors
    first = registry.resolve_connector(source["id"])
    environment_file(path, host="updated-env-host")
    second = registry.resolve_connector(source["id"])
    assert second is not first and second.settings.sqlserver_host == "updated-env-host"
    path.write_text(
        "SQLSERVER_HOST=partial-host\nSQLSERVER_PORT=\nSQLSERVER_USER=\nSQLSERVER_PASSWORD=\nSQLSERVER_DATABASE=\n"
    )
    third = registry.resolve_connector(source["id"])
    assert third.settings.sqlserver_password == "" and third.settings.sqlserver_port == "1433"
    assert "SQLSERVER_PASSWORD" in third.missing()


def test_existing_volume_and_dotenv_credentials_survive_registry_restart(client, admin, tmp_path):
    source = client.post("/api/admin/sources", json={"name": "GoTech", "kind": "sqlserver"}, headers=HEADERS).json()
    state = client.app.state
    path = tmp_path / ".env"
    environment_file(path)
    state.settings.env_file = path
    one = ConnectorRegistry(state.settings, state.db)
    two = ConnectorRegistry(state.settings, state.db)
    assert one.source_settings(source["id"]).sqlserver_password == two.source_settings(source["id"]).sqlserver_password
    assert path.read_text().count("SQLSERVER_PASSWORD=") == 1


async def test_query_dependency_error_preserves_connected_status_and_returns_specific_diagnostic(tmp_path):
    settings = Settings(
        data_dir=tmp_path,
        env_file=None,
        sqlserver_host="fixture",
        sqlserver_user="fixture",
        sqlserver_password="fixture",
        sqlserver_database="fixture",
    )
    db = Database(tmp_path / "metadata.sqlite3")
    db.initialize()
    db.execute("INSERT INTO users VALUES('u','admin@example.test','Admin','fixture','devs',1,?)", (now(),))
    db.execute(
        "INSERT INTO data_sources(id,name,kind,description,status,created_at) VALUES('s','Source','sqlserver','','not_checked',?)",
        (now(),),
    )
    registry = ConnectorRegistry(settings, db)

    class UnavailableView(SQLServerConnector):
        async def query(self, query):
            raise DatabaseUnavailable("View dependency is unavailable.", "query", 208)

    registry.register("s", UnavailableView(settings, registry.catalog))
    with pytest.raises(DatabaseUnavailable) as error:
        await registry.database_call("u", "s", "query", query={})
    assert error.value.code == 208
    row = db.one("SELECT * FROM data_sources WHERE id='s'")
    assert row["status"] == "connected" and registry.public_source(row)["error_scope"] == "query"


async def test_driver_object_error_is_redacted_and_classified_as_query_failure(tmp_path):
    class BrokenCursor(Driver):
        def execute(self, sql, parameters):
            raise RuntimeError(208, "Invalid object name 'private-table'; private-password private-host")

    settings = Settings(
        env_file=None,
        sqlserver_host="private-host",
        sqlserver_user="private-user",
        sqlserver_password="private-password",
        sqlserver_database="private-database",
    )
    connector = SQLServerConnector(settings, None, BrokenCursor())
    with pytest.raises(DatabaseUnavailable) as error:
        await connector.check()
    assert error.value.code == 208 and error.value.category == "query"
    assert "references an unavailable object" in str(error.value)
    assert "private-" not in str(error.value)
