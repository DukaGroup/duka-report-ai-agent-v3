import json
import time

from conftest import HEADERS

from app.provider import BASE_INSTRUCTIONS, BASE_CURRENCY
from test_excel_reports import wait_report


def connect(client):
    client.post("/api/subscription/login", headers=HEADERS)
    for _ in range(100):
        if client.get("/api/subscription").json()["connected"]:
            return
        time.sleep(0.01)
    raise AssertionError("Fixture account did not connect")


def last_input(client, user_id):
    path = client.app.state.settings.data_dir / "codex" / user_id / "last-turn-input.json"
    return json.loads(path.read_text())


def test_no_extra_style_message_is_attached_and_visible_history_is_unchanged(client, admin):
    connect(client)
    chat = client.post("/api/conversations", json={}, headers=HEADERS).json()
    messages = ["pershendetje", "Give me June sales.", "Më jep raportin e gushtit.", "Please reply in English."]
    for message in messages:
        response = client.post(f"/api/conversations/{chat['id']}/messages", json={"content": message}, headers=HEADERS)
        assert response.status_code == 200 and '"status": "completed"' in response.text
        assert last_input(client, admin["id"]) == [
            {"type": "text", "text": message},
        ]
    history = client.get(f"/api/conversations/{chat['id']}").json()["messages"]
    assert [m["content"] for m in history if m["role"] == "user"] == messages
    thread = json.loads(
        (client.app.state.settings.data_dir / "codex" / admin["id"] / "last-thread-input.json").read_text()
    )
    assert "Albanian lek (ALL)" in thread["baseInstructions"]
    assert "Preserve explicit EUR, USD" in thread["developerInstructions"]


def test_recovered_conversation_sends_only_original_history_and_request(client, admin):
    connect(client)
    chat = client.post("/api/conversations", json={}, headers=HEADERS).json()
    client.post(f"/api/conversations/{chat['id']}/messages", json={"content": "Use euros."}, headers=HEADERS)
    client.app.state.db.execute(
        "UPDATE conversations SET provider_thread_id='missing-rollout' WHERE id=?", (chat["id"],)
    )
    response = client.post(f"/api/conversations/{chat['id']}/messages", json={"content": "Continue."}, headers=HEADERS)
    assert response.status_code == 200
    inputs = last_input(client, admin["id"])
    payload = json.loads(inputs[-1]["text"])
    assert payload["new_message"] == "Continue."
    assert payload["previous_messages"][0]["content"] == "Use euros."
    assert len(inputs) == 1
    assert "Standing report and analysis guidance" not in inputs[0]["text"]


def test_background_report_receives_base_currency_without_extra_style_message(client, admin):
    connect(client)
    created = client.post(
        "/api/reports",
        json={"title": "Compact report", "instructions": "Summarize", "rows": [{"revenue": 42}]},
        headers=HEADERS,
    )
    assert created.status_code == 201
    report_id = created.json()["id"]
    for _ in range(100):
        report = client.get(f"/api/reports/{report_id}").json()
        if report["status"] not in ("queued", "running"):
            break
        time.sleep(0.01)
    assert report["status"] == "completed"
    inputs = last_input(client, admin["id"])
    assert json.loads(inputs[-1]["text"])["data"] == [{"revenue": 42}]
    assert len(inputs) == 1
    assert json.loads(inputs[0]["text"])["base_currency"] == BASE_CURRENCY
    assert "Albanian lek (ALL)" in BASE_INSTRUCTIONS
    assert "Preserve explicit EUR, USD" in BASE_INSTRUCTIONS


def test_background_report_preserves_original_albanian_request_when_tool_instructions_are_english(client, admin):
    connect(client)
    chat = client.post("/api/conversations", json={}, headers=HEADERS).json()
    original = "Më përgatit raportin e shitjeve për gushtin."
    client.post(f"/api/conversations/{chat['id']}/messages", json={"content": original}, headers=HEADERS)
    other = client.post("/api/conversations", json={}, headers=HEADERS).json()
    client.post(f"/api/conversations/{other['id']}/messages", json={"content": "Reply in English."}, headers=HEADERS)
    created = client.post(
        "/api/reports",
        json={
            "title": "Sales report",
            "instructions": "Summarize sales",
            "conversation_id": chat["id"],
            "rows": [{"revenue": 42}],
        },
        headers=HEADERS,
    ).json()
    assert wait_report(client, created["id"])["status"] == "completed"
    payload = json.loads(last_input(client, admin["id"])[-1]["text"])
    assert payload["user_request"] == original
    assert payload["instructions"] == "Summarize sales"


def test_style_removal_migration_refreshes_model_context_only_once(client, admin):
    connect(client)
    chat = client.post("/api/conversations", json={}, headers=HEADERS).json()
    client.post(
        f"/api/conversations/{chat['id']}/messages",
        json={"content": "Use this conversation normally."},
        headers=HEADERS,
    )
    report = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Retained report", "conversation_id": chat["id"], "rows": [{"revenue": 42}]},
    ).json()
    assert wait_report(client, report["id"])["status"] == "completed"
    original = client.get(f"/api/conversations/{chat['id']}").json()["messages"]
    db = client.app.state.db
    db.execute("DELETE FROM schema_migrations WHERE version=8")
    db.initialize()
    assert client.get(f"/api/conversations/{chat['id']}").json()["provider_thread_id"] is None
    assert client.get(f"/api/conversations/{chat['id']}").json()["messages"] == original
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200
    db.execute("UPDATE conversations SET provider_thread_id=? WHERE id=?", ("new-context", chat["id"]))
    db.initialize()
    assert client.get(f"/api/conversations/{chat['id']}").json()["provider_thread_id"] == "new-context"
