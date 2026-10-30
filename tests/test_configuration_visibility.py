"""Configuration notices are Devs-only in live, retried and saved responses."""

import json
from uuid import uuid4

import pytest

from app.progress import viewer_event
from app.provider import CodexRuntime
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_excel_reports import subscribe


def test_configuration_projection_preserves_snapshot_reset_and_original_event():
    event = {"type": "snapshot", "text": "", "activity": "switching", "provider": "claude",
             "from_provider": "chatgpt", "seq": 7, "step_label": "Kalimi te abonimi tjetër", "step_id": "step"}
    original = dict(event)
    assert viewer_event(event) == {"type": "snapshot", "text": "", "activity": "thinking", "seq": 7}
    assert viewer_event(event, technical=True) == original
    assert event == original
    business = {"type": "tool", "name": "query_database", "step_label": "Lexim i të dhënave"}
    assert viewer_event(business) == {"type": "tool", "name": "query_database"}


@pytest.mark.parametrize("role", ["manager", "president", "devs"])
def test_roles_receive_configuration_only_for_devs_across_live_replay_and_history(client, admin, monkeypatch, role):
    subscribe(client)
    if role != "devs":
        member = create_member(client)
        client.app.state.db.execute("UPDATE users SET role=? WHERE id=?", (role, member["id"]))
        sign_in_member(client)

    async def configured_stream(self, *args, **kwargs):
        for phase in ("switching", "refreshing", "recovering"):
            yield {"type": "snapshot", "text": "", "activity": phase, "provider": "claude"}
        yield {"type": "tool", "name": "read_handoff_context"}
        yield {"type": "tool", "name": "query_database"}
        yield {"type": "delta", "text": "Totali i kontrollit: 42 ALL."}
        yield {"type": "done", "status": "completed", "text": "Totali i kontrollit: 42 ALL."}

    monkeypatch.setattr(CodexRuntime, "stream", configured_stream)
    cid = client.post("/api/conversations", headers=HEADERS, json={}).json()["id"]
    body = {"content": "Check progress visibility", "request_id": str(uuid4())}
    live = client.post(f"/api/conversations/{cid}/messages", headers=HEADERS, json=body)
    assert live.status_code == 200, live.text
    events = [json.loads(line) for line in live.text.splitlines() if line]
    assert events[-1]["type"] == "done" and events[-1]["status"] == "completed", events
    run_id = next(event["id"] for event in events if event["type"] == "message")
    replay = client.get(f"/api/conversations/{cid}/runs/{run_id}/events")
    retried = client.post(f"/api/conversations/{cid}/messages", headers=HEADERS, json=body)
    history = client.get(f"/api/conversations/{cid}").json()
    for response in (live, replay, retried):
        assert response.status_code == 200, response.text
        received = [json.loads(line) for line in response.text.splitlines() if line]
        assert any(event.get("name") == "query_database" for event in received)
        assert any(event.get("text") == "Totali i kontrollit: 42 ALL." for event in received)
        switching = [event for event in received if event.get("activity") == "switching"]
        assert bool(switching) == (role == "devs")
        assert any(event.get("name") == "read_handoff_context" for event in received) == (role == "devs")
        if role != "devs":
            assert not any(event.get("activity") in ("switching", "refreshing", "recovering") for event in received)
            assert not any("step_label" in event or "step_id" in event or "step_kind" in event for event in received)
            assert any(event["type"] == "snapshot" and event.get("text") == "" for event in received)
    steps = history["messages"][-1]["steps"]
    if role == "devs":
        assert any(step["label"] == "Lexim i të dhënave" for step in steps)
        assert any(step["label"] == "Kalimi te abonimi tjetër" for step in steps)
    else:
        assert steps == []
    # Full diagnostic events remain available internally for Devs and audits.
    stored = client.app.state.db.all("SELECT event_json FROM chat_run_events WHERE run_id=?", (run_id,))
    assert any(json.loads(row["event_json"]).get("activity") == "switching" for row in stored)

