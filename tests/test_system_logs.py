import json
from dataclasses import replace

from app.config import Settings
from app.system_logs import SystemLog
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_source_credentials import source_input
from test_sqlserver import Driver


def test_logs_capture_source_errors_without_credentials(client, admin):
    source = client.post("/api/admin/sources", json=source_input(), headers=HEADERS).json()
    client.app.state.connectors.connectors[source["id"]].driver = Driver(
        error="18456 login failed private-login private-host private-password private-database"
    )
    client.post(f"/api/admin/sources/{source['id']}/check", headers=HEADERS)
    result = client.get("/api/admin/system-logs?component=database&level=error").json()
    checked = next(event for event in result["events"] if event["event"] == "connection.check.failed")
    assert checked["source_name"] == source["name"]
    assert "authentication failed" in checked["message"]
    assert "private-" not in json.dumps(result)
    assert client.cookies.get("duka_session") not in json.dumps(result)


def test_hana_production_tls_requirement_and_transport_warning_are_logged(client, admin):
    source = client.post(
        "/api/admin/sources",
        headers=HEADERS,
        json={
            "name": "HANA fixture",
            "kind": "saphana",
            "HANA_HOST": "private-hana",
            "HANA_PORT": 30015,
            "HANA_USER": "private-login",
            "HANA_PASSWORD": "private-password",
            "HANA_ENCRYPT": False,
            "HANA_VALIDATE_CERTIFICATE": False,
        },
    ).json()
    registry = client.app.state.connectors
    registry.settings = replace(registry.settings, production=True)
    connector = registry.connectors[source["id"]]
    connector.settings = replace(connector.settings, production=True)

    class NoNetwork:
        def connect(self, **kwargs):
            assert kwargs["encrypt"] is False and kwargs["sslValidateCertificate"] is False
            raise RuntimeError(-10709, "TLS is required private-password private-hana")

    connector.driver = NoNetwork()
    response = client.post(f"/api/admin/sources/{source['id']}/check", headers=HEADERS)
    assert response.status_code == 200
    assert "requires TLS encryption" in response.json()["last_error"]
    events = client.get("/api/admin/system-logs?component=database").json()["events"]
    assert any("requires TLS encryption" in e["message"] for e in events)
    assert any(e["level"] == "warning" and e["event"] == "connection.tls.warning" for e in events)
    assert "private-" not in json.dumps(events)


def test_missing_saved_profile_is_logged_as_configuration_failure(client, admin):
    source = client.post("/api/admin/sources", json=source_input(), headers=HEADERS).json()
    (client.app.state.settings.data_dir / ".env").write_text("")
    response = client.post(f"/api/admin/sources/{source['id']}/check", headers=HEADERS)
    assert response.status_code == 422
    events = client.get("/api/admin/system-logs?component=database&level=error").json()["events"]
    event = next(e for e in events if e["source_id"] == source["id"])
    assert event["details"]["category"] == "configuration"
    assert "profile is missing" in event["message"]


def test_logs_are_devs_only_including_president(client, admin):
    assert client.get("/api/admin/system-logs").status_code == 200
    member = create_member(client)
    sign_in_member(client)
    assert client.get("/api/admin/system-logs").status_code == 403
    client.app.state.db.execute("UPDATE users SET role='president' WHERE id=?", (member["id"],))
    assert client.get("/api/admin/system-logs").status_code == 403
    client.post("/api/auth/logout", headers=HEADERS)
    assert client.get("/api/admin/system-logs").status_code == 401


def test_log_pagination_retention_restart_redaction_and_poll_exclusion(client, admin):
    log = client.app.state.system_logs
    client.portal.call(log.flush)
    log.capacity = 3
    log.redactor.protect_settings(Settings(env_file=None, sqlserver_password="fixture-private-password"))
    for i in range(6):
        log.record(
            "error",
            "database",
            "fixture",
            f"Failure {i}: fixture-private-password",
            details={"password": "hidden", "access_token": "hidden-token"},
        )
    first = client.get("/api/admin/system-logs?limit=2").json()
    second = client.get(f"/api/admin/system-logs?limit=2&before={first['next_before']}").json()
    assert len(first["events"]) == 2 and len(second["events"]) == 1
    assert not {e["id"] for e in first["events"]} & {e["id"] for e in second["events"]}
    assert "fixture-private-password" not in json.dumps(first) and "hidden-token" not in json.dumps(first)
    assert len(log.db.all("SELECT * FROM system_logs")) == 3
    fresh = SystemLog(log.db, log.redactor)
    assert fresh.db.one("SELECT count(*) AS n FROM system_logs")["n"] == 3
    traffic = client.get("/api/admin/traffic").json()["events"]
    assert not any("system-logs" in event["action"] for event in traffic)
    for query in ("limit=201", "level=unknown", "component=unknown", "before=-1", "before=18446744073709551616"):
        assert client.get("/api/admin/system-logs?" + query).status_code == 422


def test_started_and_runtime_failure_events_have_no_raw_model_payload(client, admin):
    events = client.get("/api/admin/system-logs").json()["events"]
    assert any(e["event"] == "application.started" for e in events)
    client.app.state.traffic.record(
        "model-backend",
        "rpc/response",
        "error",
        payload={"error": "private prompt and token"},
        detail={"error_code": 42},
    )
    result = client.get("/api/admin/system-logs?component=model").json()
    assert result["events"][0]["details"]["error_code"] == 42
    assert "private prompt" not in json.dumps(result)
