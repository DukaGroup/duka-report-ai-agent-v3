import time
import pytest

from conftest import HEADERS

from app.db import now, uid
from test_excel_reports import subscribe, wait_report


@pytest.mark.parametrize("previous_thread", ["missing-rollout", "sandbox-blocked"])
def test_rejected_first_turn_recovers_and_preserves_local_history(client, admin, previous_thread):
    conversation = client.post("/api/conversations", json={}, headers=HEADERS).json()
    db = client.app.state.db
    db.execute("UPDATE conversations SET provider_thread_id=? WHERE id=?", (previous_thread, conversation["id"]))
    db.execute(
        "INSERT INTO messages VALUES(?,?,?,?,?,?)",
        (uid(), conversation["id"], "user", "Use euros in the report.", "completed", now()),
    )
    client.post("/api/subscription/login", headers=HEADERS)
    for _ in range(20):
        if client.get("/api/subscription").json()["connected"]:
            break
        time.sleep(0.01)
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages", json={"content": "Continue."}, headers=HEADERS
    )
    assert response.status_code == 200
    assert '"status": "completed"' in response.text
    detail = client.get(f"/api/conversations/{conversation['id']}").json()
    assert detail["provider_thread_id"] != previous_thread
    assert detail["messages"][-1]["content"] == "Recovered context: Use euros in the report."
    assert detail["messages"][0]["content"] == "Use euros in the report."


def test_follow_up_report_after_runtime_restart_preserves_chat_and_previous_report(client, admin):
    subscribe(client)
    chat = client.post("/api/conversations", headers=HEADERS, json={}).json()
    client.post(f"/api/conversations/{chat['id']}/messages", json={"content": "Use euros."}, headers=HEADERS)
    first = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "First report", "conversation_id": chat["id"], "rows": [{"revenue": 120}]},
    ).json()
    assert wait_report(client, first["id"])["status"] == "completed"
    client.portal.call(client.app.state.manager.release, admin["id"])
    follow_up = client.post(
        f"/api/conversations/{chat['id']}/messages", json={"content": "Now make an August report."}, headers=HEADERS
    )
    assert follow_up.status_code == 200 and '"status": "completed"' in follow_up.text
    second = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "August report", "conversation_id": chat["id"], "rows": [{"revenue": 150}]},
    ).json()
    assert wait_report(client, second["id"])["status"] == "completed"
    assert client.get(f"/api/reports/{first['id']}/export/xlsx").status_code == 200
    history = client.get(f"/api/conversations/{chat['id']}").json()["messages"]
    assert [m["content"] for m in history if m["role"] == "user"] == ["Use euros.", "Now make an August report."]
