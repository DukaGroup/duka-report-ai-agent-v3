#!/usr/bin/env python3
"""Protocol fixture. Never connects to OpenAI or pretends to be a live provider."""

import json
import os
import sys
import tomllib
from pathlib import Path

assert not any(key.startswith("SQLSERVER_") for key in os.environ)

account_path = Path(os.environ["CODEX_HOME"]) / "fixture-account.json"
config = tomllib.loads((account_path.parent / "config.toml").read_text())
assert "sandbox_mode" not in config
assert config["default_permissions"] == "duka_read_only"
profile = config["permissions"]["duka_read_only"]
assert profile["filesystem"] == {str(Path.cwd()): "read"}
assert profile["network"]["enabled"] is False
threads = set()
turn = 0
held_turns = {}


def emit(value):
    print(json.dumps(value), flush=True)


for line in sys.stdin:
    request = json.loads(line)
    method, params, identifier = request.get("method"), request.get("params", {}), request.get("id")
    if identifier is None or not method:
        continue
    result = {}
    if method == "account/read":
        result = {
            "account": json.loads(account_path.read_text()) if account_path.exists() else None,
            "requiresOpenaiAuth": True,
        }
    elif method == "account/login/start":
        assert params["type"] == "chatgptDeviceCode"
        result = {
            "type": "chatgptDeviceCode",
            "loginId": "fixture-login",
            "verificationUrl": "https://auth.openai.com/codex/device",
            "userCode": "TEST-CODE",
        }
        emit({"id": identifier, "result": result})
        account_path.write_text(json.dumps({"type": "chatgpt", "email": "fixture@example.com", "planType": "plus"}))
        emit(
            {
                "method": "account/login/completed",
                "params": {"loginId": "fixture-login", "success": True, "error": None},
            }
        )
        continue
    elif method == "account/logout":
        account_path.unlink(missing_ok=True)
    elif method == "model/list":
        result = {
            "data": [{"id": "fixture", "model": "fixture", "displayName": "Test fixture", "isDefault": True}],
            "nextCursor": None,
        }
    elif method in ("thread/start", "thread/resume"):
        thread_id = params.get("threadId", f"thread-{len(threads)}")
        if method == "thread/resume" and thread_id == "missing-rollout":
            emit(
                {
                    "id": identifier,
                    "error": {"code": -32600, "message": "no rollout found for thread id missing-rollout"},
                }
            )
            continue
        assert params["permissions"] == "duka_read_only"
        assert "sandbox" not in params
        assert params["config"]["features.shell_tool"] is False
        threads.add(thread_id)
        result = {"thread": {"id": thread_id}}
    elif method == "turn/start":
        turn += 1
        turn_id, thread_id = f"turn-{turn}", params["threadId"]
        assert params["permissions"] == "duka_read_only"
        assert "sandboxPolicy" not in params
        result = {"turn": {"id": turn_id}}
        emit({"id": identifier, "result": result})
        if params.get("outputSchema") and (account_path.parent / "hold-reports").exists():
            held_turns[thread_id] = turn_id
            continue
        text = "Protocol fixture reply."
        content = params["input"][0]["text"]
        if content.startswith('{"previous_messages":'):
            history = json.loads(content)
            text = "Recovered context: " + history["previous_messages"][0]["content"]
        if params.get("outputSchema"):
            text = json.dumps(
                {
                    "title": "Fixture report",
                    "summary": "Based on provided rows.",
                    "sections": [{"heading": "Findings", "body": "The supplied data was used."}],
                    "metrics": [],
                    "limitations": ["Fixture output; not live inference."],
                }
            )
        # A stray event from another turn must not leak into this stream.
        emit(
            {
                "method": "item/agentMessage/delta",
                "params": {"threadId": thread_id, "turnId": "old-turn", "delta": "WRONG"},
            }
        )
        emit({"method": "item/agentMessage/delta", "params": {"threadId": thread_id, "turnId": turn_id, "delta": text}})
        emit(
            {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "item": {"id": "assistant", "type": "agentMessage", "text": text},
                },
            }
        )
        emit(
            {
                "method": "turn/completed",
                "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed", "error": None}},
            }
        )
        continue
    elif method == "turn/interrupt" and params.get("threadId") in held_turns:
        thread_id = params["threadId"]
        emit(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {"id": held_turns.pop(thread_id), "status": "interrupted", "error": None},
                },
            }
        )
    emit({"id": identifier, "result": result})
