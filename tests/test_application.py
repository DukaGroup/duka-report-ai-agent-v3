import json
import time

from conftest import HEADERS


def create_member(client):
    response = client.post(
        "/api/admin/users",
        json={"name": "Member", "email": "member@example.com", "password": "member-long-password"},
        headers=HEADERS,
    )
    assert response.status_code == 201
    return response.json()


def sign_in_member(client):
    response = client.post(
        "/api/auth/login", json={"email": "member@example.com", "password": "member-long-password"}, headers=HEADERS
    )
    assert response.status_code == 200


def test_setup_authentication_and_csrf(client, admin):
    assert client.get("/api/auth/status").json()["needs_setup"] is False
    assert (
        client.post(
            "/api/auth/setup",
            json={"email": "another@example.com", "name": "Other", "password": "a-long-test-password"},
            headers=HEADERS,
        ).status_code
        == 409
    )
    assert client.post("/api/conversations", json={}).status_code == 403
    assert (
        client.post("/api/conversations", json={}, headers={**HEADERS, "Origin": "https://evil.example"}).status_code
        == 403
    )
    cookie = client.cookies.get("duka_session")
    assert cookie
    assert (
        "HttpOnly"
        in client.post(
            "/api/auth/login", json={"email": "admin@example.com", "password": "a-long-test-password"}, headers=HEADERS
        ).headers["set-cookie"]
    )
    client.post("/api/auth/logout", headers=HEADERS)
    assert client.get("/api/conversations").status_code == 401


def test_member_cannot_manage_workspace_or_read_other_users(client, admin):
    member = create_member(client)
    conversation = client.post("/api/conversations", json={}, headers=HEADERS).json()
    sign_in_member(client)
    assert client.get("/api/admin/users").status_code == 403
    assert client.get(f"/api/conversations/{conversation['id']}").status_code == 404
    assert client.get("/api/conversations").json() == []
    assert client.get("/api/auth/status").json()["user"]["id"] == member["id"]


def test_subscription_stream_and_account_isolation(client, admin):
    member = create_member(client)
    conversation = client.post("/api/conversations", json={}, headers=HEADERS).json()
    path = f"/api/conversations/{conversation['id']}/messages"
    assert client.post(path, json={"content": "Hello"}, headers=HEADERS).status_code == 409
    assert client.post("/api/subscription/login", headers=HEADERS).json()["userCode"] == "TEST-CODE"
    for _ in range(20):
        if client.get("/api/subscription").json()["connected"]:
            break
        time.sleep(0.01)
    response = client.post(path, json={"content": "Hello"}, headers=HEADERS)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "completed"
    assert "WRONG" not in response.text
    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assert detail["messages"][1]["content"] == "Protocol fixture reply."
    assert detail["messages"][1]["status"] == "completed"
    # Another user never inherits the logged-in user's ChatGPT runtime.
    sign_in_member(client)
    assert client.get("/api/subscription").json()["connected"] is False
    assert (client.app.state.settings.data_dir / "codex" / admin["id"] / "fixture-account.json").exists()
    assert not (client.app.state.settings.data_dir / "codex" / member["id"] / "fixture-account.json").exists()


def test_sources_dataset_grants_and_blocked_reports(client, admin):
    member = create_member(client)
    source = client.post(
        "/api/admin/sources", headers=HEADERS, json={"name": "Business DB", "kind": "postgresql"}
    ).json()
    dataset = client.post(
        "/api/admin/datasets",
        headers=HEADERS,
        json={"source_id": source["id"], "name": "Sales", "query_key": "sales_summary"},
    ).json()
    assert client.get("/api/datasets").json() == []
    client.put(f"/api/admin/datasets/{dataset['id']}/grants/{member['id']}", headers=HEADERS)
    sign_in_member(client)
    assert client.get("/api/datasets").json()[0]["id"] == dataset["id"]
    report = client.post(
        "/api/reports", headers=HEADERS, json={"title": "Sales report", "dataset_id": dataset["id"]}
    ).json()
    assert report["status"] == "blocked"
    assert "not connected" in report["error"]
    assert client.get(f"/api/reports/{report['id']}/export/json").status_code == 409


def test_report_generation_exports_and_owner_check(client, admin):
    create_member(client)
    client.post("/api/subscription/login", headers=HEADERS)
    for _ in range(20):
        if client.get("/api/subscription").json()["connected"]:
            break
        time.sleep(0.01)
    result = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Monthly report", "rows": [{"product": '=HYPERLINK("bad")', "revenue": 12}]},
    )
    assert result.status_code == 201, result.text
    report_id = result.json()["id"]
    for _ in range(100):
        report = client.get(f"/api/reports/{report_id}").json()
        if report["status"] in ("completed", "failed"):
            break
        time.sleep(0.01)
    assert report["status"] == "completed", report
    assert "Based on provided rows" in client.get(f"/api/reports/{report_id}/export/markdown").text
    exported = client.get(f"/api/reports/{report_id}/export/json").json()
    assert exported["provenance"]["source"] == "User-provided data"
    csv = client.get(f"/api/reports/{report_id}/export/csv").text
    assert "'=HYPERLINK" in csv
    sign_in_member(client)
    assert client.get(f"/api/reports/{report_id}").status_code == 404
    assert client.get(f"/api/reports/{report_id}/export/json").status_code == 404


def test_no_api_key_login_or_provider_override(client, admin):
    assert (
        client.post("/api/subscription/login", json={"apiKey": "not-a-real-key"}, headers=HEADERS).json()["type"]
        == "chatgptDeviceCode"
    )
    assert client.post("/api/conversations", headers=HEADERS, json={"api_key": "not-a-key"}).status_code == 422
    assert client.get("/api/health").json()["provider"] == "chatgpt-subscription"


def test_admin_disable_invalidates_existing_member_session(client, admin):
    member = create_member(client)
    admin_token = client.cookies.get("duka_session")
    sign_in_member(client)
    member_token = client.cookies.get("duka_session")
    client.cookies.set("duka_session", admin_token)
    assert client.patch(f"/api/admin/users/{member['id']}", json={"active": False}, headers=HEADERS).status_code == 200
    client.cookies.set("duka_session", member_token)
    assert client.get("/api/conversations").status_code == 401


def test_voice_limits_without_external_provider(client, admin):
    assert client.get("/api/voice").json()["available"] is False
    assert (
        client.post(
            "/api/voice/transcribe", files={"file": ("bad.txt", b"not audio", "text/plain")}, headers=HEADERS
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/voice/transcribe", files={"file": ("empty.webm", b"", "audio/webm")}, headers=HEADERS
        ).status_code
        == 400
    )
