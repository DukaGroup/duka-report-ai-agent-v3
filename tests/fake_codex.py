#!/usr/bin/env python3
"""Protocol fixture. Never connects to OpenAI or pretends to be a live provider."""

import json
import os
import sys
import time
import threading
import tomllib
from pathlib import Path

assert not any(key.startswith("SQLSERVER_") for key in os.environ)

account_path = Path(os.environ["CODEX_HOME"]) / "fixture-account.json"
config = tomllib.loads((account_path.parent / "config.toml").read_text())
for index, value in enumerate(sys.argv):
    if value == '--config':
        key, setting = sys.argv[index + 1].split('=', 1)
        assert key == 'permissions.duka_read_only.filesystem'
        config['permissions']['duka_read_only']['filesystem'] = tomllib.loads('value=' + setting)['value']
assert "sandbox_mode" not in config
assert config["default_permissions"] == "duka_read_only"
assert config["project_doc_max_bytes"] == 0
assert config["web_search"] == "live"
profile = config["permissions"]["duka_read_only"]
assert len(profile["filesystem"]) == 1
root, access = next(iter(profile["filesystem"].items()))
assert access == "read" and Path.cwd().is_relative_to(Path(root))
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
        if (account_path.parent / "network-offline").exists():
            emit({"id": identifier, "error": {"code": -32603, "message": "workspace routing discovery failed"}})
            continue
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
            "data": [{"id": "fixture", "model": "fixture", "displayName": "Test fixture", "isDefault": True, "supportedReasoningEfforts": [{"reasoningEffort": e, "description": e} for e in ["low", "medium", "high", "xhigh"]], "defaultReasoningEffort": "medium"}],
            "nextCursor": None,
        }
    elif method in ("thread/start", "thread/resume"):
        (account_path.parent / "last-thread-input.json").write_text(json.dumps(params))
        thread_id = params.get("threadId", f"thread-{os.getpid()}-{len(threads)}")
        if method == "thread/resume" and thread_id == "sandbox-blocked":
            emit(
                {
                    "id": identifier,
                    "error": {
                        "code": -32603,
                        "message": "error resuming thread: failed to load AGENTS.md instructions for environment `local`: fs sandbox helper failed with status exit status: 1: bwrap: No permissions to create a new namespace",
                    },
                }
            )
            continue
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
        assert params["config"]["project_doc_max_bytes"] == 0
        threads.add(thread_id)
        result = {"thread": {"id": thread_id}}
    elif method == "turn/start":
        if params["input"][-1]["text"] == "Hold this process":
            (account_path.parent / "process-held").touch()
            while (account_path.parent / "hold-process").exists():
                time.sleep(0.01)
        (account_path.parent / "last-turn-input.json").write_text(json.dumps(params["input"]))
        turn += 1
        turn_id, thread_id = f"turn-{turn}", params["threadId"]
        assert params["permissions"] == "duka_read_only"
        assert "sandboxPolicy" not in params
        result = {"turn": {"id": turn_id}}
        emit({"id": identifier, "result": result})
        quota_path = account_path.parent / "quota.json"
        if quota_path.exists():
            quota = json.loads(quota_path.read_text())
            emit({"method": "item/agentMessage/delta", "params": {"threadId": thread_id, "turnId": turn_id, "delta": quota.get("partial", "UNFINISHED FIXTURE")}})
            emit({"method": "turn/completed", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "failed", "error": {"message": "You've hit your usage limit.", "codexErrorInfo": "usageLimitExceeded"}}}})
            continue
        crash_path = account_path.parent / "crash-once"
        if crash_path.exists():
            # The native process dies mid-answer; the subscription itself is fine.
            crash_path.unlink()
            emit({"method": "item/agentMessage/delta", "params": {"threadId": thread_id, "turnId": turn_id, "delta": "PARTIAL BEFORE CRASH"}})
            os._exit(1)
        if params.get("outputSchema") and (account_path.parent / "hold-reports").exists():
            held_turns[thread_id] = turn_id
            continue
        text = "Protocol fixture reply."
        content = params["input"][-1]["text"]
        if content == "Reasoning phase fixture":
            emit({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id,
                  "item": {"id": "reasoning", "type": "reasoning", "summary": [{"text": "PRIVATE_REASONING_FIXTURE"}]}}})
            emit({"method": "item/reasoning/summaryTextDelta", "params": {"threadId": thread_id, "turnId": turn_id,
                  "delta": "PRIVATE_REASONING_FIXTURE"}})
        if '"handoff_checkpoint"' in content:
            envelope = json.loads(content)
            context = envelope.get("context", {})
            content = context.get("current_request", content)
            params["input"][-1]["text"] = content
        slow = account_path.parent / "long-investigation.json"
        if content.startswith("Long investigation fixture") and slow.exists():
            delay = json.loads(slow.read_text())["seconds"]
            held_turns[thread_id] = turn_id

            def finish_long_response(tid=thread_id, turnid=turn_id):
                if held_turns.get(tid) != turnid:
                    return
                held_turns.pop(tid)
                answer = "Investigation completed automatically after the long wait."
                emit({"method": "item/completed", "params": {"threadId": tid, "turnId": turnid,
                      "item": {"id": "assistant", "type": "agentMessage", "text": answer}}})
                emit({"method": "turn/completed", "params": {"threadId": tid,
                      "turn": {"id": turnid, "status": "completed", "error": None}}})

            timer = threading.Timer(delay, finish_long_response)
            timer.daemon = True
            timer.start()
            continue
        if content.startswith('{"previous_messages":'):
            history = json.loads(content)
            text = "Recovered context: " + history["previous_messages"][0]["content"]
        if (params.get("outputSchema") or {}).get("properties", {}).keys() == {"python_script"}:
            text = json.dumps({"python_script": "def build(report):\n    report.default_layout()\n"})
        elif params.get("outputSchema"):
            payload = json.loads(content)
            request_text = (payload.get("user_request") or payload.get("instructions") or "").lower()
            albanian = (
                any(w in request_text for w in ("më ", "për ", "raportin", "shitjeve"))
                and "reply in english" not in request_text
            )
            datasets = [payload["provenance"]] + payload.get("additional_analyses", [])
            translated = {
                "revenue": "Të ardhurat",
                "cost": "Kosto",
                "month": "Muaji",
                "period": "Periudha",
                "text": "Teksti",
                "segment": "Pjesa",
            }
            workbook = {
                "python_script": "def build(report):\n    report.default_layout()\n",
                "language": "sq" if albanian else "en",
                "labels": [],
                "analyses": [
                    {
                        "index": i,
                        "name": f"Analiza {i + 1}" if albanian else f"Analysis {i + 1}",
                        "columns": [
                            {
                                "column": c["name"],
                                "label": translated.get(c["name"], c["name"]) if albanian else c["name"],
                            }
                            for c in d.get("columns", [])
                        ],
                        "column_order": [],
                        "scope": "Të gjithë rreshtat e përzgjedhur" if albanian else "All selected rows",
                        "query_explanation": "Filtrat e kërkesës së raportit" if albanian else "Report request filters",
                    }
                    for i, d in enumerate(datasets)
                ],
            }
            text = json.dumps(
                {
                    "title": "Raport testimi" if albanian else "Fixture report",
                    "summary": "Nga të dhënat e ofruara." if albanian else "Based on provided rows.",
                    "sections": [
                        {
                            "heading": "Gjetjet" if albanian else "Findings",
                            "body": "U përdorën të dhënat e ofruara." if albanian else "The supplied data was used.",
                        }
                    ],
                    "metrics": [],
                    "limitations": [
                        "Dalje testimi; nuk është analizë reale." if albanian else "Fixture output; not live inference."
                    ],
                    "workbook": workbook,
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
