"""Shared correctness, durable execution and recovery contracts for both providers."""

import asyncio
import json
import time
from contextlib import aclosing

import pytest
from fastapi.testclient import TestClient

from app.db import now, uid
from app.main import create_app
from app.provider import CodexRuntime
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_chat_controls import prepare, post, claude as claude_fixture
from test_excel_reports import wait_report


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


def wait_for(fn):
    for _ in range(200):
        value = fn()
        if value:
            return value
        time.sleep(0.025)
    raise AssertionError("Background work did not finish")


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_rebuild_retains_requirements_before_the_last_40_messages(client, admin, claude, monkeypatch, provider):
    cid = prepare(client, provider)
    db = client.app.state.db
    for index in range(52):
        db.execute(
            "INSERT INTO messages VALUES(?,?,?,?,?,?)",
            (
                uid(),
                cid,
                "user" if index % 2 == 0 else "assistant",
                "Only SAP 400; cutoff includes August 25; exclude loans and late entries."
                if index == 0
                else f"Turn {index}",
                "completed",
                now(),
            ),
        )
    prompts = []
    rpc = CodexRuntime.rpc

    async def record(self, method, params=None):
        if method == "turn/start":
            prompts.append(params["input"][0]["text"])
        return await rpc(self, method, params)

    monkeypatch.setattr(CodexRuntime, "rpc", record)
    response = post(client, cid, content="Continue with the same exclusions.")
    assert response.status_code == 200
    prompt = json.loads(prompts[-1] if provider == "chatgpt" else claude[-1].content)
    assert len(prompt["previous_messages"]) == 52
    assert "exclude loans" in prompt["previous_messages"][0]["content"]


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_startup_recovers_checkpoint_without_another_user_message(client, admin, claude, provider):
    cid = prepare(client, provider)
    db, settings = client.app.state.db, client.app.state.settings
    model = client.app.state.manager.model_for_user(admin["id"], None)
    user_id, assistant = uid(), uid()
    with db.connect() as c:
        c.execute(
            "INSERT INTO messages VALUES(?,?,?,?,?,?)",
            (user_id, cid, "user", "Finish the original investigation.", "completed", now()),
        )
        c.execute(
            "INSERT INTO messages VALUES(?,?,?,?,?,?)",
            (assistant, cid, "assistant", "Partial work before shutdown", "streaming", now()),
        )
        client.app.state.chat_jobs.enqueue(
            c,
            assistant,
            cid,
            admin["id"],
            {"thread": "old-thread", "content": "Finish the original investigation.", "model": model, "effort": "high"},
        )
        c.execute("UPDATE chat_runs SET status='running' WHERE id=?", (assistant,))
    second_app = create_app(settings)
    with TestClient(second_app) as recovered:
        recovered.cookies.set("duka_session", client.cookies.get("duka_session"))
        result = wait_for(
            lambda: (
                r
                if (r := db.one("SELECT * FROM chat_runs WHERE id=?", (assistant,)))["status"] == "completed"
                else None
            )
        )
        assert result["attempts"] == 1
        messages = recovered.get(f"/api/conversations/{cid}").json()["messages"]
        assert len(messages) == 2 and messages[-1]["status"] == "completed"
        events = recovered.get(f"/api/conversations/{cid}/runs/{assistant}/events").text
        assert '"type": "snapshot"' in events and '"status": "completed"' in events
        payload = json.loads(db.one("SELECT payload_json FROM chat_runs WHERE id=?", (assistant,))["payload_json"])
        prompt = json.loads(payload["content"])
        assert prompt["new_message"] == "Finish the original investigation."
        assert prompt["recovery"]["unfinished_draft"] == "Partial work before shutdown"
        assert recovered.get(f"/api/conversations/{cid}").json()["provider_thread_id"] != "old-thread"


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_listener_disconnect_keeps_worker_running_and_partial_reply_persisted(
    client, admin, claude, monkeypatch, provider
):
    from app.claude_provider import ClaudeRuntime

    cid = prepare(client, provider)
    started = None
    gate = None

    async def init():
        nonlocal started, gate
        started, gate = asyncio.Event(), asyncio.Event()

    client.portal.call(init)

    async def held(self, thread, content, model=None, *args, **kwargs):
        yield {"type": "delta", "text": "Checkpointed partial answer"}
        started.set()
        await gate.wait()
        yield {"type": "done", "status": "completed", "text": "Complete answer"}

    monkeypatch.setattr(CodexRuntime if provider == "chatgpt" else ClaudeRuntime, "stream", held)
    # Call the actual endpoint handler, then close its HTTP subscriber after a delta.
    endpoint = next(
        r.endpoint
        for r in client.app.routes
        if getattr(r, "path", "") == "/api/conversations/{conversation_id}/messages"
    )
    from app.schemas import ChatMessage
    from types import SimpleNamespace

    async def disconnect():
        response = await endpoint(
            cid, ChatMessage(content="Investigate slowly"), SimpleNamespace(app=client.app), admin
        )
        async with aclosing(response.body_iterator) as events:
            async for line in events:
                if json.loads(line)["type"] == "delta":
                    break
        job = client.app.state.db.one("SELECT * FROM chat_runs WHERE conversation_id=?", (cid,))
        assert job["status"] == "running"
        assert not client.app.state.chat_jobs.tasks[job["id"]].done()
        assert (
            client.app.state.db.one("SELECT content FROM messages WHERE id=?", (job["id"],))["content"]
            == "Checkpointed partial answer"
        )
        gate.set()
        await client.app.state.chat_jobs.tasks[job["id"]]
        return job["id"]

    identifier = client.portal.call(disconnect)
    events = client.get(f"/api/conversations/{cid}/runs/{identifier}/events").text
    assert "Complete answer" in events
    last_seq = json.loads(events.splitlines()[-1])["seq"]
    assert client.get(f"/api/conversations/{cid}/runs/{identifier}/events?after={last_seq}").text == ""


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_restore_versions_keeps_displaced_chat_and_rebuilds_both_providers(client, admin, claude, provider):
    cid = prepare(client, provider)
    post(client, cid, content="Original request")
    post(client, cid, content="Later instruction")
    before = client.get(f"/api/conversations/{cid}").json()["messages"]
    post(client, cid, content="Edited request", retry_message_id=before[0]["id"])
    edited = client.get(f"/api/conversations/{cid}").json()["messages"]
    version = client.get(f"/api/conversations/{cid}/versions").json()[0]
    assert version["message_count"] == 4
    assert client.post(f"/api/conversations/{cid}/versions/{version['id']}/restore", headers=HEADERS).status_code == 200
    after = client.get(f"/api/conversations/{cid}").json()
    assert [(m["id"], m["content"]) for m in after["messages"]] == [(m["id"], m["content"]) for m in before]
    assert after["provider_thread_id"] is None
    assert client.app.state.db.all("SELECT * FROM conversation_provider_threads WHERE conversation_id=?", (cid,)) == []
    newer = client.get(f"/api/conversations/{cid}/versions").json()[0]
    assert client.post(f"/api/conversations/{cid}/versions/{newer['id']}/restore", headers=HEADERS).status_code == 200
    assert [m["content"] for m in client.get(f"/api/conversations/{cid}").json()["messages"]] == [
        m["content"] for m in edited
    ]
    assert post(client, cid, content="Continue restored version").status_code == 200
    create_member(client)
    sign_in_member(client)
    assert client.get(f"/api/conversations/{cid}/versions").status_code == 404
    assert client.post(f"/api/conversations/{cid}/versions/{newer['id']}/restore", headers=HEADERS).status_code == 404


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_report_restart_recovers_captured_snapshot_and_cached_narrative(client, admin, claude, provider):
    cid = prepare(client, provider)
    report = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Restart-safe report", "conversation_id": cid, "rows": [{"value": 12}]},
    ).json()
    assert wait_report(client, report["id"])["status"] == "completed"
    db = client.app.state.db
    original = db.one("SELECT * FROM reports WHERE id=?", (report["id"],))
    db.execute("UPDATE reports SET status='running',stage='excel' WHERE id=?", (report["id"],))
    with TestClient(create_app(client.app.state.settings)) as recovered:
        recovered.cookies.set("duka_session", client.cookies.get("duka_session"))
        assert wait_report(recovered, report["id"])["status"] == "completed"
        final = db.one("SELECT * FROM reports WHERE id=?", (report["id"],))
        assert original["snapshot_id"] == final["snapshot_id"]
        assert original["content_json"] == final["content_json"]
        assert recovered.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_submission_request_keys_prevent_duplicate_messages_after_transport_retry(client, admin, claude, provider):
    cid = prepare(client, provider)
    key = uid()
    first = post(client, cid, content="One exact submission", request_id=key)
    second = post(client, cid, content="One exact submission", request_id=key)
    assert first.status_code == second.status_code == 200
    assert first.text == second.text
    messages = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert len(messages) == 2
    accepted = client.get(f"/api/conversations/{cid}/requests/{key}").json()
    assert accepted["run_id"] == messages[-1]["id"]
    other = client.post("/api/conversations", headers=HEADERS, json={}).json()["id"]
    assert post(client, other, content="Different chat", request_id=key).status_code == 422
    create_member(client)
    sign_in_member(client)
    assert client.get(f"/api/conversations/{cid}/requests/{key}").status_code == 404
    assert client.get(f"/api/conversations/{cid}/runs/{accepted['run_id']}/events").status_code == 404


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_restore_preserves_branch_attachments_reports_and_calculation_visibility(client, admin, claude, provider):
    cid = prepare(client, provider)
    upload = client.post(
        f"/api/conversations/{cid}/attachments",
        headers=HEADERS,
        files={"file": ("evidence.csv", b"name,value\nA,10", "text/csv")},
    ).json()
    post(client, cid, content="Original evidence", attachment_ids=[upload["id"]])
    original = client.get(f"/api/conversations/{cid}").json()["messages"][0]
    first_report = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Original report", "conversation_id": cid, "rows": [{"value": 10}]},
    ).json()
    assert wait_report(client, first_report["id"])["status"] == "completed"
    db = client.app.state.db
    calc = uid()
    db.execute(
        "INSERT INTO calculation_runs VALUES(?,?,?,?,?,?,?,?)",
        (calc, admin["id"], cid, "{}", "{}", "{}", now(), "complete"),
    )
    post(client, cid, content="Edited without evidence", retry_message_id=original["id"], attachment_ids=[])
    second_report = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Edited report", "conversation_id": cid, "rows": [{"value": 20}]},
    ).json()
    assert wait_report(client, second_report["id"])["status"] == "completed"
    version = client.get(f"/api/conversations/{cid}/versions").json()[0]
    assert client.post(f"/api/conversations/{cid}/versions/{version['id']}/restore", headers=HEADERS).status_code == 200
    restored = client.get(f"/api/conversations/{cid}").json()["messages"][0]
    assert restored["attachments"][0]["id"] == upload["id"]
    assert db.one("SELECT conversation_id FROM reports WHERE id=?", (first_report["id"],))["conversation_id"] == cid
    assert db.one("SELECT conversation_id FROM reports WHERE id=?", (second_report["id"],))["conversation_id"] is None
    assert not db.one("SELECT * FROM archived_calculations WHERE calculation_id=?", (calc,))
    edited_version = client.get(f"/api/conversations/{cid}/versions").json()[0]
    assert (
        client.post(f"/api/conversations/{cid}/versions/{edited_version['id']}/restore", headers=HEADERS).status_code
        == 200
    )
    assert client.get(f"/api/conversations/{cid}").json()["messages"][0]["attachments"] == []
    assert db.one("SELECT * FROM archived_calculations WHERE calculation_id=?", (calc,))
    assert db.one("SELECT conversation_id FROM reports WHERE id=?", (second_report["id"],))["conversation_id"] == cid
    for report in (first_report, second_report):
        assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200
    with db.connect() as c:
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
