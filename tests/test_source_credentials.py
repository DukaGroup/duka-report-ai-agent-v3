import json
import stat

from app.connectors import ConnectorRegistry
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_sqlserver import Driver


def source_input(host="private-host", password="private-password"):
    return {
        "name": "Reporting source",
        "kind": "sqlserver",
        "SQLSERVER_HOST": host,
        "SQLSERVER_PORT": 1444,
        "SQLSERVER_USER": "private-login",
        "SQLSERVER_PASSWORD": password,
        "SQLSERVER_DATABASE": "private-database",
    }


def test_saved_credentials_are_in_private_env_not_returned_and_survive_reload(client, admin):
    values = source_input()
    response = client.post("/api/admin/sources", json=values, headers=HEADERS)
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["status"] == "not_checked" and source["configuration_origin"] == "saved"
    assert all(source["connection_fields"].values())
    db, settings = client.app.state.db, client.app.state.settings
    stored = db.one("SELECT * FROM source_credentials WHERE source_id=?", (source["id"],))
    assert "private-" not in json.dumps(stored)
    assert "private-" not in json.dumps(db.all("SELECT * FROM data_sources"))
    for endpoint in ("/api/admin/sources", "/api/admin/overview", "/api/admin/database", "/api/admin/audit"):
        assert "private-" not in client.get(endpoint).text
    private_env = settings.data_dir / ".env"
    assert stat.S_IMODE(private_env.stat().st_mode) == 0o600
    assert "private-password" in private_env.read_text()
    assert stored["ciphertext"] == "env"
    reloaded = ConnectorRegistry(settings, db)
    conn = reloaded.connectors[source["id"]]
    assert conn.settings.sqlserver_host == values["SQLSERVER_HOST"]
    assert conn.settings.sqlserver_password == values["SQLSERVER_PASSWORD"]
    assert conn.settings.sqlserver_port == "1444"
    assert "private-" not in repr(conn.settings)


def test_sources_use_distinct_connections_and_edit_keeps_blank_password(client, admin):
    first = client.post(
        "/api/admin/sources", json=source_input("first-private", "first-password"), headers=HEADERS
    ).json()
    second = client.post(
        "/api/admin/sources", json=source_input("second-private", "second-password"), headers=HEADERS
    ).json()
    registry = client.app.state.connectors
    assert registry.connectors[first["id"]].settings.sqlserver_host == "first-private"
    assert registry.connectors[second["id"]].settings.sqlserver_password == "second-password"
    response = client.patch(
        f"/api/admin/sources/{first['id']}",
        headers=HEADERS,
        json={"name": "Renamed", "kind": "sqlserver", "SQLSERVER_HOST": "updated-private", "SQLSERVER_PASSWORD": ""},
    )
    assert response.status_code == 200
    assert "first-password" not in response.text
    assert registry.connectors[first["id"]].settings.sqlserver_password == "first-password"
    assert registry.connectors[first["id"]].settings.sqlserver_host == "updated-private"
    assert registry.connectors[first["id"]].settings.sqlserver_port == "1444"
    assert registry.connectors[second["id"]].settings.sqlserver_host == "second-private"


def test_existing_source_can_be_configured_without_restart_or_recreating_datasets(client, admin):
    source = client.post("/api/admin/sources", json={"name": "Existing", "kind": "sqlserver"}, headers=HEADERS).json()
    response = client.patch(f"/api/admin/sources/{source['id']}", headers=HEADERS, json=source_input())
    assert response.status_code == 200 and response.json()["id"] == source["id"]
    assert len(client.get("/api/admin/sources").json()) == 1
    assert client.app.state.connectors.connectors[source["id"]].settings.sqlserver_password == "private-password"


def test_bad_settings_fail_atomically_without_echoing_password(client, admin):
    values = source_input()
    values["SQLSERVER_PORT"] = "invalid"
    response = client.post("/api/admin/sources", json=values, headers=HEADERS)
    assert response.status_code == 422 and "private-" not in response.text
    values = source_input()
    del values["SQLSERVER_HOST"]
    response = client.post("/api/admin/sources", json=values, headers=HEADERS)
    assert response.status_code == 422 and "private-" not in response.text
    assert client.get("/api/admin/sources").json() == []
    values = source_input()
    values["kind"] = "mysql"
    assert client.post("/api/admin/sources", json=values, headers=HEADERS).status_code == 422


def test_missing_managed_env_fails_closed_without_environment_fallback(client, admin):
    source = client.post("/api/admin/sources", json=source_input(), headers=HEADERS).json()
    settings, db = client.app.state.settings, client.app.state.db
    (settings.data_dir / ".env").unlink()
    reloaded = ConnectorRegistry(settings, db)
    assert source["id"] not in reloaded.connectors
    row = db.one("SELECT * FROM data_sources WHERE id=?", (source["id"],))
    assert row["status"] == "error" and "profile is missing" in row["last_error"]
    assert not (settings.data_dir / "source-credentials.key").exists()


def test_members_cannot_save_or_update_source_credentials(client, admin):
    source = client.post("/api/admin/sources", json=source_input(), headers=HEADERS).json()
    create_member(client)
    sign_in_member(client)
    assert client.post("/api/admin/sources", json=source_input(), headers=HEADERS).status_code == 403
    assert client.patch(f"/api/admin/sources/{source['id']}", json=source_input(), headers=HEADERS).status_code == 403


def test_connection_check_uses_saved_settings_and_redacts_driver_errors(client, admin):
    source = client.post("/api/admin/sources", json=source_input(), headers=HEADERS).json()
    driver = Driver(error="18456 login failed private-login private-host private-password private-database")
    client.app.state.connectors.connectors[source["id"]].driver = driver
    response = client.post(f"/api/admin/sources/{source['id']}/check", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["status"] == "error" and "authentication failed" in response.json()["last_error"]
    assert "private-" not in response.text
    assert driver.options["server"].startswith("duka_") and driver.options["password"] == "private-password"
    import configparser, os
    aliases = configparser.ConfigParser()
    aliases.read(os.environ["FREETDSCONF"])
    assert aliases[driver.options["server"]]["host"] == "private-host"


def test_subscription_process_never_receives_database_environment(client, admin, monkeypatch):
    monkeypatch.setenv("SQLSERVER_HOST", "private-environment-host")
    monkeypatch.setenv("SQLSERVER_PASSWORD", "private-environment-password")
    # The protocol fixture asserts SQLSERVER variables are absent in its environment.
    assert client.post("/api/subscription/login", headers=HEADERS).status_code == 200
