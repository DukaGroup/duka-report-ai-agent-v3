"""Real native protocol / SDK envelopes, synthetic subscriptions only."""

import json
import asyncio
import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.provider import ProviderError, native_error
from app.subscription_pool import digest, encoded, read_checkpoint
from conftest import HEADERS
from test_claude_subscriptions import claude as claude_fixture, connect_claude
from test_excel_reports import subscribe, wait_report


@pytest.fixture
def claude(client, monkeypatch):
    calls = claude_fixture.__wrapped__(client, monkeypatch)
    import claude_agent_sdk as sdk
    from claude_agent_sdk.types import RateLimitEvent, RateLimitInfo

    original = sdk.ClaudeSDKClient

    class Client(original):
        async def get_server_info(self):
            data = await super().get_server_info()
            data["models"].append(
                {
                    "value": "opus55-alias",
                    "resolvedModel": "claude-opus-5-5",
                    "displayName": "Claude Opus 5.5",
                    "supportsEffort": True,
                    "supportedEffortLevels": ["low", "medium", "high", "max"],
                }
            )
            return data

        async def query(self, content):
            self.received_content = content
            await super().query(content)

        async def receive_response(self):
            home = Path(self.options.env["CLAUDE_CONFIG_DIR"])
            if (home / "quota.json").exists():
                yield sdk.StreamEvent(
                    uuid=str(uuid4()),
                    session_id=self.session,
                    event={"delta": {"type": "text_delta", "text": "UNFINISHED CLAUDE"}},
                )
                yield RateLimitEvent(
                    rate_limit_info=RateLimitInfo(status="rejected", resets_at=int(time.time() + 3600), raw={}),
                    uuid=str(uuid4()),
                    session_id=self.session,
                )
                return
            if '"task":"Compact this continuation checkpoint.' in self.content:
                yield sdk.AssistantMessage(
                    content=[
                        sdk.TextBlock(
                            text="Working summary: preserve the original cutoff, SAP 400, bank-loan exclusion; inspect full evidence by checkpoint ID."
                        )
                    ],
                    model="fixture",
                )
                yield sdk.ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id=self.session,
                    result="Working summary: preserve the original cutoff, SAP 400, bank-loan exclusion; inspect full evidence by checkpoint ID.",
                )
                return
            if '"handoff_checkpoint"' in self.content:
                context = json.loads(self.content)["context"]
                if self.options.output_format:
                    self.content = context["current_request"]
                else:
                    yield sdk.AssistantMessage(
                        content=[sdk.TextBlock(text="Completed from the saved investigation checkpoint.")],
                        model="claude-opus-5-5",
                    )
                    yield sdk.ResultMessage(
                        subtype="success",
                        duration_ms=1,
                        duration_api_ms=1,
                        is_error=False,
                        num_turns=1,
                        session_id=self.session,
                        result="Completed from the saved investigation checkpoint.",
                    )
                    return
            async for event in super().receive_response():
                yield event

    monkeypatch.setattr(sdk, "ClaudeSDKClient", Client)
    return calls


def add(client, provider, label):
    result = client.post("/api/admin/subscriptions", headers=HEADERS, json={"provider": provider, "label": label})
    assert result.status_code == 201, result.text
    return result.json()["id"]


def home(client, identifier):
    manager = client.app.state.manager
    account = manager.pool.get(identifier)
    return (
        client.app.state.settings.data_dir
        / ("codex" if account["provider"] == "chatgpt" else "claude")
        / account["credential_key"]
    )


def connect(client, identifier):
    result = client.post(f"/api/admin/subscriptions/{identifier}/login", headers=HEADERS)
    assert result.status_code == 200, result.text
    login = result.json()
    if login.get("requiresCode"):
        result = client.post(
            f"/api/admin/subscriptions/{identifier}/login/code",
            headers=HEADERS,
            json={"login_id": login["loginId"], "code": "fixture-single-use-code"},
        )
        assert result.status_code == 200, result.text
    for _ in range(80):
        accounts = client.get("/api/admin/subscriptions").json()
        if next(a for a in accounts if a["id"] == identifier)["connected"]:
            return
        time.sleep(0.01)
    raise AssertionError("Fixture subscription did not connect")


def chat(client, model="fixture"):
    return client.post("/api/conversations", headers=HEADERS, json={"model": model}).json()["id"]


def send(client, cid, text="Use SAP 400 only, include August 25, exclude bank loans.", **options):
    result = client.post(f"/api/conversations/{cid}/messages", headers=HEADERS, json={"content": text, **options})
    assert result.status_code == 200, result.text
    return [json.loads(line) for line in result.text.splitlines()]


def exhaust(client, identifier):
    directory = home(client, identifier)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "quota.json").write_text("{}")


def test_midstream_quota_uses_next_same_provider_and_keeps_native_account_binding(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    second = add(client, "chatgpt", "ChatGPT 2")
    connect(client, second)
    exhaust(client, "legacy-chatgpt")
    cid = chat(client)
    events = send(client, cid, reasoning_effort="xhigh")
    assert events[-1]["status"] == "completed"
    assert any(e.get("activity") == "switching" for e in events)
    assert not any(e.get("provider") == "claude" for e in events)
    assert (
        client.app.state.db.one(
            "SELECT account_id FROM subscription_thread_accounts WHERE thread_id=(SELECT provider_thread_id FROM conversations WHERE id=?)",
            (cid,),
        )["account_id"]
        == second
    )
    checkpoint = client.app.state.db.one("SELECT content_json FROM model_checkpoints WHERE scope_id=?", (cid,))
    context = json.loads(checkpoint["content_json"])
    assert "SAP 400 only" in context["current_request"]
    assert context["unfinished_draft_unverified"] == "UNFINISHED FIXTURE"
    first_thread = client.get(f"/api/conversations/{cid}").json()["provider_thread_id"]
    events = send(client, cid, "Continue using the same exclusions.")
    assert events[-1]["status"] == "completed"
    assert client.get(f"/api/conversations/{cid}").json()["provider_thread_id"] == first_thread
    assert home(client, second) != home(client, "legacy-chatgpt")
    assert not [c for c in claude if hasattr(c, "received_content")]


def test_cross_provider_handoff_uses_opus55_and_valid_supported_effort(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    exhaust(client, "legacy-chatgpt")
    cid = chat(client)
    events = send(client, cid, reasoning_effort="xhigh")
    route = next(e for e in events if e["type"] == "route" and e["provider"] == "claude")
    assert route["model"] == "claude:claude-opus-5-5" and route["reasoning_effort"] == "max"
    assert events[-1]["status"] == "completed"
    inference = [c for c in claude if hasattr(c, "received_content")][-1]
    context = json.loads(inference.received_content)["context"]
    assert "exclude bank loans" in context["messages"][0]["content"]
    assert "UNFINISHED FIXTURE" in context["unfinished_draft_unverified"]
    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["model"] == "claude:claude-opus-5-5"
    assert detail["messages"][-1]["content"] == "Completed from the saved investigation checkpoint."


def test_claude_tries_next_claude_then_chatgpt_and_restores_context(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    second = add(client, "claude", "Claude 2")
    connect(client, second)
    exhaust(client, "legacy-claude")
    cid = chat(client, "claude:default")
    assert send(client, cid)[-1]["status"] == "completed"
    assert (
        client.app.state.db.one(
            "SELECT account_id FROM subscription_thread_accounts WHERE thread_id=(SELECT provider_thread_id FROM conversations WHERE id=?)",
            (cid,),
        )["account_id"]
        == second
    )
    exhaust(client, second)
    events = send(client, cid, "Check the exact same scope again.")
    assert events[-1]["status"] == "completed"
    assert any(e.get("provider") == "chatgpt" for e in events)
    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["model"] == "fixture"


def test_both_exhausted_or_missing_ends_with_saved_error_and_next_chat_is_ready(client, admin, claude):
    cid = chat(client)
    missing = send(client, cid)
    assert missing[-1]["type"] == "error"
    assert "No connected subscription" in client.get(f"/api/conversations/{cid}").json()["messages"][-1]["content"]
    subscribe(client)
    connect_claude(client)
    exhaust(client, "legacy-chatgpt")
    exhaust(client, "legacy-claude")
    events = send(client, chat(client))
    assert events[-1]["type"] == "error"
    assert len([e for e in events if e["type"] == "snapshot"]) == 1
    assert not client.app.state.manager.worker_leases
    (home(client, "legacy-chatgpt") / "quota.json").unlink()
    assert send(client, chat(client))[-1]["status"] == "completed"


def test_corrupt_tool_evidence_stops_instead_of_switching_with_incomplete_context(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    cid = chat(client)
    request = encoded({"tool": "query_database"})
    client.app.state.db.execute(
        "INSERT INTO model_tool_journal(user_id,kind,scope_id,thread_id,request_json,response_json,sha256,access_revision,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (admin["id"], "chat", cid, "old", request, "{}", "corrupt", 0, "now"),
    )
    exhaust(client, "legacy-chatgpt")
    events = send(client, cid)
    assert events[-1]["type"] == "error" and "context could not be read" in events[-1]["message"]
    assert not [c for c in claude if hasattr(c, "received_content")]


def test_report_generation_survives_quota_mid_json(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    exhaust(client, "legacy-chatgpt")
    response = client.post(
        "/api/reports",
        headers=HEADERS,
        json={
            "title": "Requested cutoff",
            "template_id": "executive",
            "rows": [{"Partner": "Alpha", "Balance": 100}],
            "model": "fixture",
        },
    )
    assert response.status_code == 201, response.text
    report = wait_report(client, response.json()["id"])
    assert report["status"] == "completed", report
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200


@pytest.mark.parametrize(
    "info,category",
    [
        ("usageLimitExceeded", "quota"),
        ("UsageLimitExceeded", "quota"),
        ("rate_limit", "quota"),
        ("authentication_failed", "auth"),
        ("InternalServerError", None),
        ("ContextWindowExceeded", "context"),
    ],
)
def test_native_error_categories_are_structured(info, category):
    assert native_error({"codexErrorInfo": info, "message": "fixture"}).category == category


def test_checkpoint_cannot_be_read_from_another_chat_or_member(client, admin):
    from app.db import now
    from app.subscription_pool import revision

    cid = chat(client)
    identifier = str(uuid4())
    value = encoded({"private": "evidence"})
    client.app.state.db.execute(
        "INSERT INTO model_checkpoints VALUES(?,?,?,?,?,?,?,?)",
        (identifier, admin["id"], "chat", cid, revision(client.app.state.db, admin["id"]), value, digest(value), now()),
    )
    with pytest.raises(ProviderError, match="unavailable"):
        read_checkpoint(
            client.app.state.manager,
            admin["id"],
            {"threadId": "another-chat", "arguments": {"checkpoint_id": identifier}},
        )


def test_large_context_is_compacted_on_destination_with_complete_archive(client, admin, claude):
    from app.db import now

    subscribe(client)
    connect_claude(client)
    cid = chat(client)
    previous = "Original cutoff includes August 25; SAP 500 excluded. " + "Historical evidence. " * 4000
    client.app.state.db.execute(
        "INSERT INTO messages VALUES(?,?,?,?,?,?)", (str(uuid4()), cid, "user", previous, "completed", now())
    )
    exhaust(client, "legacy-chatgpt")
    assert send(client, cid)[-1]["status"] == "completed"
    checkpoint = client.app.state.db.one(
        "SELECT * FROM model_checkpoints WHERE scope_id=? ORDER BY created_at DESC", (cid,)
    )
    compactions = [
        json.loads(c.received_content)
        for c in claude
        if hasattr(c, "received_content") and '"task":"Compact this continuation checkpoint.' in c.received_content
    ]
    assert len(compactions) > 1
    assert "".join(c["chunk"] for c in compactions) == encoded(json.loads(checkpoint["content_json"]))
    assert all(c.options.model == "claude-opus-5-5" for c in claude if hasattr(c, "received_content"))
    final = json.loads([c.received_content for c in claude if hasattr(c, "received_content")][-1])
    assert final["context"]["full_context_checkpoint"] == checkpoint["id"]
    assert len(encoded(final)) < 30000
    assert previous in checkpoint["content_json"]


def test_three_chatgpt_two_claude_accounts_are_each_tried_once_in_order(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    accounts = [
        "legacy-chatgpt",
        add(client, "chatgpt", "GPT 2"),
        add(client, "chatgpt", "GPT 3"),
        "legacy-claude",
        add(client, "claude", "Claude 2"),
    ]
    for identifier in accounts:
        if not identifier.startswith("legacy-"):
            connect(client, identifier)
        exhaust(client, identifier)
    events = send(client, chat(client))
    assert events[-1]["type"] == "error"
    assert [e["provider"] for e in events if e["type"] == "route"] == [
        "chatgpt",
        "chatgpt",
        "chatgpt",
        "claude",
        "claude",
    ]
    switches = client.app.state.db.all(
        "SELECT detail_json FROM audit_events WHERE action='subscription.failover' ORDER BY created_at,rowid"
    )
    assert [json.loads(s["detail_json"])["to_account"] for s in switches] == accounts[1:]
    assert not client.app.state.manager.worker_leases


def test_reordering_is_atomic_and_missing_or_duplicate_accounts_are_rejected(client, admin):
    subscribe(client)
    second = add(client, "chatgpt", "Second")
    third = add(client, "chatgpt", "Third")
    body = {"provider": "chatgpt", "account_ids": [third, "legacy-chatgpt", second]}
    assert client.post("/api/admin/subscription-order", headers=HEADERS, json=body).status_code == 200
    assert [a["id"] for a in client.app.state.manager.pool.accounts("chatgpt")] == body["account_ids"]
    assert (
        client.post(
            "/api/admin/subscription-order", headers=HEADERS, json={**body, "account_ids": [third, third, second]}
        ).status_code
        == 422
    )
    assert [a["id"] for a in client.app.state.manager.pool.accounts("chatgpt")] == body["account_ids"]


def test_account_management_is_devs_only_and_preserves_original_credential_home(client, admin):
    from test_application import create_member, sign_in_member

    subscribe(client)
    original = client.app.state.settings.data_dir / "codex" / admin["id"]
    assert home(client, "legacy-chatgpt") == original
    identifier = add(client, "chatgpt", "Second account")
    assert client.post(f"/api/admin/subscriptions/{identifier}/login").status_code == 403
    create_member(client)
    sign_in_member(client)
    assert client.get("/api/admin/subscriptions").status_code == 403
    assert (
        client.post(
            "/api/admin/subscriptions", headers=HEADERS, json={"provider": "claude", "label": "Forbidden"}
        ).status_code
        == 403
    )


def test_grant_change_during_compaction_stops_before_transferring_continuation(client, admin, claude, monkeypatch):
    from app.db import now
    from app.claude_provider import ClaudeRuntime

    subscribe(client)
    connect_claude(client)
    cid = chat(client)
    client.app.state.db.execute(
        "INSERT INTO messages VALUES(?,?,?,?,?,?)",
        (str(uuid4()), cid, "user", "Earlier constraints. " * 6000, "completed", now()),
    )
    exhaust(client, "legacy-chatgpt")
    original = ClaudeRuntime.stream

    async def change_access(self, thread, content, *args, **kwargs):
        if '"task":"Compact this continuation checkpoint.' in content:
            client.app.state.db.execute(
                "INSERT INTO data_access_versions VALUES(?,1) ON CONFLICT(user_id) DO UPDATE SET revision=revision+1",
                (admin["id"],),
            )
            yield {"type": "done", "status": "completed", "text": "Factual summary."}
        else:
            async for event in original(self, thread, content, *args, **kwargs):
                yield event

    monkeypatch.setattr(ClaudeRuntime, "stream", change_access)
    events = send(client, cid)
    assert events[-1]["type"] == "error" and "access changed" in events[-1]["message"]
    assert not [c for c in claude if hasattr(c, "received_content")]


def test_user_can_interrupt_while_destination_is_continuing(client, admin, claude, monkeypatch):
    from app.claude_provider import ClaudeRuntime
    from app.schemas import ChatMessage
    from types import SimpleNamespace

    subscribe(client)
    connect_claude(client)
    exhaust(client, "legacy-chatgpt")
    cid = chat(client)
    original = ClaudeRuntime.stream

    async def exercise():
        entered, gate = asyncio.Event(), asyncio.Event()

        async def held(self, thread, content, *args, **kwargs):
            entered.set()
            await gate.wait()
            yield {"type": "done", "status": "completed", "text": "Should not publish"}

        monkeypatch.setattr(ClaudeRuntime, "stream", held)
        endpoint = next(
            r.endpoint
            for r in client.app.routes
            if getattr(r, "path", "") == "/api/conversations/{conversation_id}/messages"
        )
        await endpoint(
            cid, ChatMessage(content="Investigate with automatic handoff"), SimpleNamespace(app=client.app), admin
        )
        await asyncio.wait_for(entered.wait(), 5)
        await client.app.state.chat_jobs.stop(cid)
        assert not client.app.state.manager.worker_leases
        assert not client.app.state.locks[cid].locked()

    client.portal.call(exercise)
    monkeypatch.setattr(ClaudeRuntime, "stream", original)
    detail = client.get(f"/api/conversations/{cid}").json()
    assert detail["messages"][-1]["status"] == "interrupted"
    assert "Should not publish" not in detail["messages"][-1]["content"]
    assert send(client, chat(client))[-1]["status"] == "completed"


def test_repeated_report_tool_after_account_switch_reuses_same_run_result(client, admin, monkeypatch):
    from app.db import now
    from unittest.mock import AsyncMock

    subscribe(client)
    cid = chat(client)
    manager = client.app.state.manager
    mocked = AsyncMock(
        return_value={
            "success": True,
            "contentItems": [{"type": "inputText", "text": encoded({"report_id": "saved-report", "status": "queued"})}],
        }
    )
    monkeypatch.setattr(manager, "_tool_call", mocked)

    async def exercise():
        runtime = await manager.acquire_worker(admin["id"], "chat", cid, "fixture")
        thread = await runtime.thread(None, "fixture")
        identifier = str(uuid4())
        with client.app.state.db.connect() as c:
            c.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?)", (identifier, cid, "assistant", "", "streaming", now())
            )
            client.app.state.chat_jobs.enqueue(
                c, identifier, cid, admin["id"], {"thread": thread, "model": "fixture", "content": "Create one report"}
            )
        arguments = {
            "dataset_id": "fixture",
            "parameters": {},
            "title": "One report",
            "instructions": "Requested scope",
            "template_id": "sales",
        }
        first = await manager.tool_call(
            admin["id"], {"threadId": thread, "tool": "create_report", "arguments": arguments}
        )
        runtime.native_thread = await runtime.native.thread(None, "fixture")
        runtime.bind()
        second = await manager.tool_call(
            admin["id"], {"threadId": runtime.native_thread, "tool": "create_report", "arguments": arguments}
        )
        assert first == second and mocked.await_count == 1
        client.app.state.db.execute("UPDATE chat_runs SET status='interrupted' WHERE id=?", (identifier,))
        client.app.state.db.execute("UPDATE messages SET status='interrupted' WHERE id=?", (identifier,))
        await manager.release_worker(admin["id"], "chat", cid)

    client.portal.call(exercise)
