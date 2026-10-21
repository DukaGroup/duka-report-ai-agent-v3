"""Both native transports announce reasoning without exposing its content."""

import json
from datetime import datetime
from uuid import uuid4

import pytest

from test_chat_controls import prepare, post
from test_claude_subscriptions import claude as claude_fixture


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_reasoning_phase_survives_chat_stream_without_private_text(client, admin, claude, monkeypatch, provider):
    if provider == "claude":
        import claude_agent_sdk as sdk
        original = sdk.ClaudeSDKClient

        class ThinkingClient(original):
            async def receive_response(self):
                yield sdk.StreamEvent(uuid=str(uuid4()), session_id=self.session, event={
                    "type": "content_block_start", "index": 0,
                    "content_block": {"type": "thinking", "thinking": "PRIVATE_REASONING_FIXTURE"},
                })
                yield sdk.StreamEvent(uuid=str(uuid4()), session_id=self.session, event={
                    "type": "content_block_delta", "index": 0,
                    "delta": {"type": "thinking_delta", "thinking": "PRIVATE_REASONING_FIXTURE"},
                })
                async for event in super().receive_response():
                    yield event

        monkeypatch.setattr(sdk, "ClaudeSDKClient", ThinkingClient)
    cid = prepare(client, provider)
    response = post(client, cid, content="Reasoning phase fixture")
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    activity = next(i for i, event in enumerate(events) if event.get("activity") == "reasoning")
    assert events[activity]["type"] == "activity"
    assert any(event["type"] == "delta" for event in events[activity + 1:])
    assert events[-1]["type"] == "done" and events[-1]["status"] == "completed"
    completed_at = events[-1]["completed_at"]
    assert datetime.fromisoformat(completed_at).tzinfo is not None
    assert "PRIVATE_REASONING_FIXTURE" not in response.text
    messages = client.get(f"/api/conversations/{cid}").json()["messages"]
    assert messages[-1]["completed_at"] == completed_at
    assert messages[0]["completed_at"] is None
    run_id = next(event["id"] for event in events if event["type"] == "message")
    replay = client.get(f"/api/conversations/{cid}/runs/{run_id}/events").text
    replayed = [json.loads(line) for line in replay.splitlines() if line.strip()]
    assert replayed[-1]["completed_at"] == completed_at
    assert "PRIVATE_REASONING_FIXTURE" not in json.dumps(messages)
