import time

from conftest import HEADERS

from app.db import now, uid


def test_rejected_first_turn_recovers_and_preserves_local_history(client, admin):
    conversation = client.post("/api/conversations", json={}, headers=HEADERS).json()
    db = client.app.state.db
    db.execute("UPDATE conversations SET provider_thread_id='missing-rollout' WHERE id=?", (conversation["id"],))
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
    assert detail["provider_thread_id"] != "missing-rollout"
    assert detail["messages"][-1]["content"] == "Recovered context: Use euros in the report."
    assert detail["messages"][0]["content"] == "Use euros in the report."
