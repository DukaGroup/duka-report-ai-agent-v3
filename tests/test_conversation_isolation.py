from app.provider import CodexRuntime
import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from conftest import HEADERS
from test_excel_reports import subscribe


def new_chat(client):
    return client.post("/api/conversations", headers=HEADERS, json={}).json()["id"]


@pytest.mark.parametrize("max_workers", [1, 2])
def test_chat_thread_starts_once_and_resumes_when_reopened(client, admin, monkeypatch, max_workers):
    subscribe(client)
    manager = client.app.state.manager
    manager.settings.max_workers = max_workers
    calls = []
    original_rpc = CodexRuntime.rpc

    async def record_rpc(self, method, params=None):
        result = await original_rpc(self, method, params)
        if method in ("thread/start", "thread/resume", "turn/start"):
            calls.append((method, params, result))
        return result

    monkeypatch.setattr(CodexRuntime, "rpc", record_rpc)
    a, b = new_chat(client), new_chat(client)
    for cid in (a, b):
        detail = client.get(f"/api/conversations/{cid}").json()
        assert detail["provider_thread_id"] is None
        assert detail["messages"] == []
    assert calls == []  # Creating/opening an unused conversation makes no Codex thread.

    threads = {}
    for cid, text in ((a, "Only in chat A"), (b, "Only in chat B")):
        response = client.post(f"/api/conversations/{cid}/messages", headers=HEADERS, json={"content": text})
        assert response.status_code == 200 and '"status": "completed"' in response.text
        threads[cid] = client.get(f"/api/conversations/{cid}").json()["provider_thread_id"]
    assert threads[a] and threads[b] and threads[a] != threads[b]
    assert len([c for c in calls if c[0] == "thread/start"]) == 2
    first_turns = [params for method, params, result in calls if method == "turn/start"]
    assert [p["threadId"] for p in first_turns] == [threads[a], threads[b]]
    assert [p["input"][-1]["text"] for p in first_turns] == ["Only in chat A", "Only in chat B"]

    before_opening = len(calls)
    client.get("/api/conversations")
    client.get(f"/api/conversations/{a}")
    assert len(calls) == before_opening
    response = client.post(f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "Continue A"})
    assert response.status_code == 200
    assert client.get(f"/api/conversations/{a}").json()["provider_thread_id"] == threads[a]
    assert len([c for c in calls if c[0] == "thread/start"]) == 2

    # A restarted or recycled worker must resume the saved thread, not start a replacement.
    client.portal.call(manager.release, admin["id"])
    calls.clear()
    for cid in (b, a):
        client.get(f"/api/conversations/{cid}")
    assert calls == []
    response = client.post(f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "Still A"})
    assert response.status_code == 200 and '"status": "completed"' in response.text
    assert [method for method, params, result in calls] == ["thread/resume", "turn/start"]
    assert all(params["threadId"] == threads[a] for method, params, result in calls)
    detail = client.get(f"/api/conversations/{a}").json()
    assert detail["provider_thread_id"] == threads[a]
    assert [m["content"] for m in detail["messages"] if m["role"] == "user"] == [
        "Only in chat A", "Continue A", "Still A"
    ]


def test_reports_messages_uploads_and_stop_are_scoped_to_their_chat(client, admin):
    subscribe(client)
    a, b, c = [new_chat(client) for _ in range(3)]
    hold = client.app.state.settings.data_dir / "codex" / admin["id"] / "hold-reports"
    hold.touch()
    reports = []
    for cid in (a, b):
        response = client.post(
            "/api/reports",
            headers=HEADERS,
            json={"title": "Held report", "conversation_id": cid, "rows": [{"revenue": 10}]},
        )
        assert response.status_code == 201
        reports.append(response.json()["id"])
    assert (
        client.post(f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "Blocked here"}).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/conversations/{c}/messages", headers=HEADERS, json={"content": "Independent chat"}
        ).status_code
        == 200
    )
    upload = client.post(
        f"/api/conversations/{c}/attachments",
        headers=HEADERS,
        files={"file": ("data.csv", b"name,revenue\nTest,10", "text/csv")},
    )
    assert upload.status_code == 201
    assert client.post(f"/api/conversations/{a}/stop", headers=HEADERS).status_code == 200
    assert client.get(f"/api/reports/{reports[0]}").json()["stage"] == "interrupted"
    assert client.get(f"/api/reports/{reports[1]}").json()["status"] in ("queued", "running")
    assert reports[1] in client.app.state.report_jobs
    assert (
        client.post(
            f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "Available again"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/conversations/{b}/messages", headers=HEADERS, json={"content": "Still blocked here"}
        ).status_code
        == 409
    )
    assert client.delete(f"/api/conversations/{b}", headers=HEADERS).status_code == 200
    saved = client.get(f"/api/reports/{reports[1]}").json()
    assert saved["stage"] == "interrupted" and saved["conversation_id"] is None
    assert client.get(f"/api/conversations/{a}").status_code == 200


def test_simultaneous_chat_streams_keep_separate_threads_and_stop_targets(client, admin, monkeypatch):
    subscribe(client)
    a, b = new_chat(client), new_chat(client)
    started, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def stream(self, thread_id, content, model=None, output_schema=None):
        seen.append((thread_id, content))
        if content == "First chat held":
            started.set()
            await release.wait()
        yield {"type": "done", "status": "completed", "text": content + " answer"}

    monkeypatch.setattr(CodexRuntime, "stream", stream)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(
            client.post, f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "First chat held"}
        )
        client.portal.call(started.wait)
        assert any(row["id"] == a and row["running"] for row in client.get("/api/conversations").json())
        assert (
            client.post(f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "Duplicate"}).status_code
            == 409
        )
        response = client.post(f"/api/conversations/{b}/messages", headers=HEADERS, json={"content": "Second chat"})
        assert response.status_code == 200 and "Second chat answer" in response.text
        client.portal.call(release.set)
        assert pending.result(timeout=5).status_code == 200
    assert seen[0][0] != seen[1][0]
    for cid, expected in ((a, "First chat held"), (b, "Second chat")):
        messages = client.get(f"/api/conversations/{cid}").json()["messages"]
        assert [m["content"] for m in messages] == [expected, expected + " answer"]


def test_report_tool_cannot_choose_another_conversations_context(client, admin):
    subscribe(client)
    a, b = new_chat(client), new_chat(client)
    client.post(f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "Only in A"})
    manager = client.app.state.manager
    thread = client.get(f"/api/conversations/{a}").json()["provider_thread_id"]
    body = manager.report_request(
        admin["id"], {"threadId": thread}, {"title": "A report", "conversation_id": b, "rows": [{"revenue": 1}]}
    )
    assert body.conversation_id == a
    with pytest.raises(ValueError, match="active conversation"):
        manager.report_request(
            admin["id"], {"threadId": "unrelated"}, {"title": "No context", "rows": [{"revenue": 1}]}
        )
    client.portal.call(manager.release, admin["id"])
    response = client.post(f"/api/conversations/{b}/messages", headers=HEADERS, json={"content": "Hello from B"})
    assert response.status_code == 200 and "Only in A" not in response.text and "Recovered context" not in response.text


def test_stalled_native_transport_cannot_queue_a_different_conversation(client, admin):
    import time

    subscribe(client)
    a, b = new_chat(client), new_chat(client)
    home = client.app.state.settings.data_dir / "codex" / admin["id"]
    marker = home / "hold-process"
    marker.touch()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            client.post, f"/api/conversations/{a}/messages", headers=HEADERS, json={"content": "Hold this process"}
        )
        try:
            for _ in range(300):
                if (home / "process-held").exists():
                    break
                time.sleep(0.01)
            assert (home / "process-held").exists()
            second = pool.submit(
                client.post,
                f"/api/conversations/{b}/messages",
                headers=HEADERS,
                json={"content": "Respond independently"},
            )
            response = second.result(timeout=5)
            assert response.status_code == 200 and "Protocol fixture reply." in response.text
            assert not first.done()
            assert client.post("/api/subscription/disconnect", headers=HEADERS).status_code == 409
            assert client.post(f"/api/admin/runtimes/{admin['id']}/restart", headers=HEADERS).status_code == 409
            manager = client.app.state.manager
            control = manager.for_user(admin["id"])
            one = manager.workers[(admin["id"], "chat", a)]
            two = manager.workers[(admin["id"], "chat", b)]
            assert len({control.process.pid, one.process.pid, two.process.pid}) == 3
            assert one.workspace != two.workspace
            assert one.home == two.home == control.home
        finally:
            marker.unlink(missing_ok=True)
        assert first.result(timeout=5).status_code == 200


def test_idle_workers_recycle_without_evicting_busy_chats(client, admin):
    from app.provider import ProviderError

    manager = client.app.state.manager
    manager.settings.max_workers = 2
    one = client.portal.call(manager.acquire_worker, admin["id"], "chat", "one")
    two = client.portal.call(manager.acquire_worker, admin["id"], "chat", "two")
    with pytest.raises(ProviderError, match="simultaneous conversation capacity"):
        client.portal.call(manager.acquire_worker, admin["id"], "chat", "three")
    client.portal.call(manager.release_worker, admin["id"], "chat", "two")
    third = client.portal.call(manager.acquire_worker, admin["id"], "chat", "three")
    assert manager.workers[(admin["id"], "chat", "one")] is one
    assert (admin["id"], "chat", "two") not in manager.workers
    assert third is not two
    client.portal.call(manager.release, admin["id"])
    assert not manager.workers and not manager.worker_leases


def test_second_excel_finishes_while_first_report_remains_running(client, admin, monkeypatch):
    import json
    from test_excel_reports import wait_report

    subscribe(client)
    first_chat, second_chat = new_chat(client), new_chat(client)
    original = CodexRuntime.stream
    started = asyncio.Event()

    async def hold_first(self, thread_id, content, model=None, output_schema=None):
        if output_schema and json.loads(content)["title"] == "Held first report":
            started.set()
            await asyncio.Event().wait()
        async for event in original(self, thread_id, content, model, output_schema):
            yield event

    monkeypatch.setattr(CodexRuntime, "stream", hold_first)
    first = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"conversation_id": first_chat, "title": "Held first report", "rows": [{"revenue": 10}]},
    ).json()
    client.portal.call(started.wait)
    second = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"conversation_id": second_chat, "title": "Independent second report", "rows": [{"revenue": 20}]},
    ).json()
    assert wait_report(client, second["id"])["status"] == "completed"
    assert client.get(f"/api/reports/{second['id']}/export/xlsx").status_code == 200
    assert client.get(f"/api/reports/{first['id']}").json()["status"] == "running"
    client.post(f"/api/conversations/{first_chat}/stop", headers=HEADERS)
    assert client.get(f"/api/reports/{second['id']}").json()["status"] == "completed"
