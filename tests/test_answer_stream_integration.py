"""Progress notes stay out of streamed, saved and replayed chat answers."""

import json
from uuid import uuid4

import pytest

from app.provider import CodexRuntime
from test_chat_controls import prepare, post
from test_claude_subscriptions import claude as claude_fixture


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_progress_note_before_tool_never_enters_chat_or_replay(client, admin, claude, monkeypatch, provider):
    note = "INTERMEDIATE_PROGRESS_NOTE_FIXTURE"
    if provider == "chatgpt":
        original_rpc = CodexRuntime.rpc

        async def with_progress(self, method, params=None):
            if method == "turn/start":
                queue = self.queues[params["threadId"]]
                for kind, body in (
                    ("item/started", {"item": {"id": "note", "type": "agentMessage", "phase": "commentary"}}),
                    ("item/agentMessage/delta", {"itemId": "note", "delta": note}),
                    ("item/completed", {"item": {"id": "note", "type": "agentMessage", "phase": "commentary", "text": note}}),
                    ("item/started", {"item": {"id": "tool", "type": "dynamicToolCall", "tool": "list_sources"}}),
                ):
                    queue.put_nowait({"method": kind, "params": body})
            return await original_rpc(self, method, params)

        monkeypatch.setattr(CodexRuntime, "rpc", with_progress)
    else:
        import claude_agent_sdk as sdk

        original_client = sdk.ClaudeSDKClient

        class WithProgress(original_client):
            async def receive_response(self):
                for event in (
                    {"type": "message_start"},
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": note}},
                    {"type": "content_block_start", "content_block": {"type": "tool_use"}},
                    {"type": "message_start"},
                ):
                    yield sdk.StreamEvent(uuid=str(uuid4()), session_id=self.session, event=event)
                async for event in super().receive_response():
                    yield event

        monkeypatch.setattr(sdk, "ClaudeSDKClient", WithProgress)

    cid = prepare(client, provider)
    response = post(client, cid, content="Public answer boundary fixture")
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]["type"] == "done" and events[-1]["status"] == "completed", events
    assert note not in response.text
    messages = client.get(f"/api/conversations/{cid}").json()["messages"]
    answer = messages[-1]
    assert answer["role"] == "assistant" and answer["content"]
    assert note not in json.dumps(messages)
    run_id = next(event["id"] for event in events if event["type"] == "message")
    replay = client.get(f"/api/conversations/{cid}/runs/{run_id}/events")
    assert replay.status_code == 200
    assert note not in replay.text

