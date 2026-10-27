import json
import time

from conftest import HEADERS
from test_application import create_member, sign_in_member


def test_delete_conversation_is_owned_and_trashes_before_permanent_purge(client, admin):
    create_member(client)
    chat = client.post("/api/conversations", json={}, headers=HEADERS).json()
    db = client.app.state.db
    db.execute("INSERT INTO messages VALUES('m',?,'user','hello','completed','now')", (chat["id"],))
    db.execute(
        "INSERT INTO reports(id,user_id,conversation_id,template_id,title,instructions,status,created_at) VALUES('r',?,?,'executive','Keep me','','blocked','now')",
        (admin["id"], chat["id"]),
    )
    token = client.cookies.get("duka_session")
    sign_in_member(client)
    assert client.delete(f"/api/conversations/{chat['id']}", headers=HEADERS).status_code == 404
    client.cookies.set("duka_session", token)
    assert client.delete(f"/api/conversations/{chat['id']}").status_code == 403
    assert client.delete(f"/api/conversations/{chat['id']}", headers=HEADERS).status_code == 200
    assert client.get(f"/api/conversations/{chat['id']}").status_code == 404
    # Deletion is recoverable; only an explicit purge cascades messages.
    assert db.one("SELECT * FROM messages WHERE id='m'")
    assert db.one("SELECT * FROM reports WHERE id='r'")["conversation_id"] == chat["id"]
    assert client.post('/api/conversations/bulk-delete', headers=HEADERS,
                       json={'conversation_ids': [chat['id']], 'permanent': True}).status_code == 200
    assert not db.one("SELECT * FROM messages WHERE id='m'")
    assert db.one("SELECT * FROM reports WHERE id='r'")["conversation_id"] is None



def test_sqlserver_missing_configuration_status_and_dataset_enable_controls(client, admin):
    source = client.post(
        "/api/admin/sources", json={"name": "SQL reporting", "kind": "sqlserver"}, headers=HEADERS
    ).json()
    assert source["status"] == "not_configured"
    checked = client.post(f"/api/admin/sources/{source['id']}/check", headers=HEADERS).json()
    assert "SQLSERVER_HOST" in checked["last_error"] and checked["checked_at"]
    config = client.get("/api/admin/database").json()
    assert all(isinstance(v, bool) for v in config["environment"].values())
    assert config["environment"]["SQLSERVER_PASSWORD"] is False
    assert {q["query_key"] for q in config["queries"]} == {"connection_check", "database_catalog"}
    dataset = client.post(
        "/api/admin/datasets",
        json={"name": "Schema", "source_id": source["id"], "query_key": "database_catalog"},
        headers=HEADERS,
    ).json()
    assert "schema_name" in json.loads(dataset["parameters_schema_json"])["required"]
    response = client.patch(f"/api/admin/datasets/{dataset['id']}", json={"active": True}, headers=HEADERS)
    assert response.status_code == 200 and response.json()["enabled"] == 1
    unknown = client.post(
        "/api/admin/datasets",
        json={"name": "Unknown", "source_id": source["id"], "query_key": "missing"},
        headers=HEADERS,
    ).json()
    assert (
        client.patch(f"/api/admin/datasets/{unknown['id']}", json={"active": True}, headers=HEADERS).status_code == 422
    )
    create_member(client)
    sign_in_member(client)
    assert client.get("/api/admin/database").status_code == 403
    assert client.post(f"/api/admin/sources/{source['id']}/check", headers=HEADERS).status_code == 403


def test_devs_model_tools_can_read_and_save_datasets_without_explicit_grants(client, admin):
    class FixtureConnector:
        async def fetch(self, key, parameters):
            return [{"revenue": 42}]

    source = client.post("/api/admin/sources", json={"name": "Fixture", "kind": "sqlserver"}, headers=HEADERS).json()
    dataset = client.post(
        "/api/admin/datasets",
        json={"name": "Fixture sales", "source_id": source["id"], "query_key": "connection_check"},
        headers=HEADERS,
    ).json()
    client.patch(f"/api/admin/datasets/{dataset['id']}", json={"active": True}, headers=HEADERS)
    client.app.state.connectors.register(source["id"], FixtureConnector())
    manager = client.app.state.manager
    chat = client.post("/api/conversations", headers=HEADERS, json={}).json()
    thread_id = "fixture-" + chat["id"]
    client.app.state.db.execute("UPDATE conversations SET provider_thread_id=? WHERE id=?", (thread_id, chat["id"]))

    def tool(name, arguments):
        response = client.portal.call(
            manager.tool_call,
            admin["id"],
            {"namespace": "duka_reporting", "threadId": thread_id, "tool": name, "arguments": arguments},
        )
        return json.loads(response["contentItems"][0]["text"])

    args = {
        "dataset_id": dataset["id"],
        "parameters": {},
        "title": "Tool report",
        "instructions": "Summarize",
        "template_id": "sales",
    }
    assert tool("fetch_dataset", {"dataset_id": dataset["id"], "parameters": {}})['rows'] == [{'revenue':42}]
    disconnected = tool("create_report", args)
    for _ in range(200):
        failed = client.get(f"/api/reports/{disconnected['report_id']}").json()
        if failed['status'] == 'failed':
            break
        time.sleep(.01)
    assert failed['status'] == 'failed' and 'No connected subscription' in failed['error']
    assert not client.app.state.db.all('SELECT * FROM dataset_grants WHERE user_id=?',(admin['id'],))
    listing = tool("list_datasets", {})["datasets"][0]
    assert "parameters_schema" in listing and "columns_schema" in listing
    assert "query_key" not in listing and "password" not in json.dumps(listing)
    assert tool("fetch_dataset", {"dataset_id": dataset["id"], "parameters": {}})["rows"] == [{"revenue": 42}]
    client.post("/api/subscription/login", headers=HEADERS)
    for _ in range(100):
        if client.get("/api/subscription").json()["connected"]:
            break
        time.sleep(0.01)
    # Connecting a shared account invalidates old native bindings. Supply a new
    # owner-bound fixture thread before calling its report tool.
    thread_id = "fixture-connected-" + chat["id"]
    client.app.state.db.execute("UPDATE conversations SET provider_thread_id=? WHERE id=?", (thread_id, chat["id"]))
    created = tool("create_report", args)
    assert created["status"] == "queued"
    for _ in range(100):
        report = client.get(f"/api/reports/{created['report_id']}").json()
        if report["status"] in ("completed", "failed"):
            break
        time.sleep(0.01)
    assert report["status"] == "completed"
    snapshot = client.app.state.db.one("SELECT rows_json FROM dataset_snapshots WHERE id=?", (report["snapshot_id"],))
    assert json.loads(snapshot["rows_json"]) == [{"revenue": 42}]
    assert "42" in client.get(f"/api/reports/{created['report_id']}/export/csv").text
