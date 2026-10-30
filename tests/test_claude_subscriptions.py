"""Provider selection changes the full chat/report path, not just a UI label."""

import json
import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.claude_provider import ClaudeRuntime, login_url
from app.provider import ProviderError
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_excel_reports import subscribe, wait_report


@pytest.fixture
def claude(client, monkeypatch):
    import claude_agent_sdk as sdk
    fixture = Path(__file__).with_name("fake_claude.py")
    fixture.chmod(0o755)
    client.app.state.settings.claude_binary = str(fixture.resolve())
    calls = []

    class Client:
        def __init__(self, options):
            self.options = options
            self.session = options.resume or options.session_id or str(uuid4())
            self.interrupted = False
            calls.append(self)

        async def __aenter__(self):
            assert self.options.tools == ["WebSearch", "WebFetch"]
            assert self.options.permission_mode == "dontAsk"
            assert self.options.strict_mcp_config is True
            assert self.options.setting_sources == []
            assert "bare" not in self.options.extra_args
            return self

        async def __aexit__(self, *args):
            pass

        async def get_server_info(self):
            return {"models": [{"value": "default", "displayName": "Claude default", "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]}, {"value": "opus", "displayName": "Claude Opus", "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]}]}

        async def query(self, content):
            self.content = content

        async def interrupt(self):
            self.interrupted = True

        async def receive_response(self):
            directory = Path(self.options.env["CLAUDE_CONFIG_DIR"]) / "projects" / "fixture"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / (self.session + ".jsonl")).touch()
            structured = None
            if self.options.output_format:
                prompt = json.loads(self.content)
                data = [prompt["provenance"], *prompt["additional_analyses"]]
                structured = {
                    "title": prompt["title"], "summary": "Report generated with Claude.", "metrics": [], "sections": [], "limitations": [],
                    "workbook": {"language": "en", "labels": [], "analyses": [
                        {"index": i, "name": "Data " + str(i), "scope": "Requested scope", "query_explanation": "Fixture",
                         "columns": [{"column": c["name"], "label": c["name"]} for c in item["columns"]]}
                        for i, item in enumerate(data)
                    ], "python_script": "def build(report):\n    s=report.sheet('Claude review')\n    s.title()\n    s.table(0)"},
                }
                text = json.dumps(structured)
            else:
                text = "Claude response: " + self.content
                yield sdk.StreamEvent(uuid=str(uuid4()), session_id=self.session,
                                      event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}})
                yield sdk.AssistantMessage(content=[sdk.TextBlock(text=text)], model="fixture-claude")
            yield sdk.ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False,
                                    num_turns=1, session_id=self.session, result=text, structured_output=structured,
                                    terminal_reason="aborted_streaming" if self.interrupted else "completed")

    monkeypatch.setattr(sdk, "ClaudeSDKClient", Client)
    return calls


def connect_claude(client):
    response = client.post("/api/subscription/login?provider=claude", headers=HEADERS)
    assert response.status_code == 200, response.text
    login = response.json()
    assert login["requiresCode"] is True and login_url(login["verificationUrl"])
    assert client.post("/api/subscription/login/code", headers=HEADERS, json={
        "login_id": login["loginId"], "code": "fixture-single-use-code",
    }).status_code == 200
    for _ in range(100):
        result = client.get("/api/subscription?provider=claude").json()
        if result["connected"]:
            return result
        time.sleep(.01)
    raise AssertionError("Claude fixture login did not complete")


def choose(client, provider):
    response = client.post("/api/subscription/select", headers=HEADERS, json={"provider": provider})
    assert response.status_code == 200, response.text


def send(client, chat, text="Hello", model=None):
    response = client.post(f"/api/conversations/{chat}/messages", headers=HEADERS,
                           json={"content": text, "model": model})
    assert response.status_code == 200, response.text
    events = [json.loads(line) for line in response.text.splitlines()]
    assert not any(e["type"] == "error" for e in events), events
    return events


def test_both_accounts_stay_connected_and_selection_is_workspace_wide(client, admin, claude):
    subscribe(client)
    status = connect_claude(client)
    assert status["account"]["email"] == "claude@example.com"
    assert client.get("/api/subscription").json()["provider_id"] == "chatgpt"
    choose(client, "claude")
    assert client.get("/api/subscription").json()["provider_id"] == "claude"
    assert client.get("/api/subscription?provider=chatgpt").json()["connected"] is True
    models = client.get("/api/subscription/models").json()
    assert models[0]["model"] == "claude:default" and models[1]["model"] == "claude:opus"
    choose(client, "chatgpt")
    assert client.get("/api/subscription?provider=claude").json()["connected"] is True
    choose(client, "claude")
    member = create_member(client)
    sign_in_member(client)
    assert client.get("/api/subscription").json()["provider_id"] == "claude"
    assert client.get("/api/subscription?provider=claude").json()["connected"] is True
    assert client.app.state.manager.selected_provider(admin["id"]) == "claude"
    assert client.app.state.manager.selected_provider(member["id"]) == "claude"


def test_two_new_claude_chats_are_isolated_reopening_keeps_id_and_provider_switch_restores_each_session(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    choose(client, "claude")
    a, b = [client.post("/api/conversations", headers=HEADERS, json={}).json()["id"] for _ in range(2)]
    send(client, a, "Only in A")
    send(client, b, "Only in B")
    db = client.app.state.db
    thread_a = db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (a,))["provider_thread_id"]
    thread_b = db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (b,))["provider_thread_id"]
    assert thread_a.startswith("claude:") and thread_a != thread_b
    client.get(f"/api/conversations/{a}")
    send(client, a, "Again A")
    assert db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (a,))["provider_thread_id"] == thread_a
    assert claude[-1].options.resume == thread_a.removeprefix("claude:")
    assert "Only in B" not in claude[-1].content
    gpt_model = client.get("/api/subscription/models?provider=chatgpt").json()[0]["model"]
    choose(client, "chatgpt")
    send(client, a, "Use ChatGPT", gpt_model)
    gpt_thread = db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (a,))["provider_thread_id"]
    assert gpt_thread != thread_a and not gpt_thread.startswith("claude:")
    choose(client, "claude")
    send(client, a, "Back to Claude", "claude:opus")
    assert db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (a,))["provider_thread_id"] == thread_a
    choose(client, "chatgpt")
    send(client, a, "Back to ChatGPT", gpt_model)
    assert db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (a,))["provider_thread_id"] == gpt_thread
    assert len(db.all("SELECT * FROM conversation_provider_threads WHERE conversation_id=?", (a,))) == 2


def test_background_report_uses_selected_claude_and_same_validated_excel_pipeline(client, admin, claude):
    connect_claude(client)
    choose(client, "claude")
    response = client.post("/api/reports", headers=HEADERS, json={
        "title": "Claude report", "rows": [{"sales": 125, "currency": "ALL"}],
    })
    assert response.status_code == 201, response.text
    report = wait_report(client, response.json()["id"])
    assert report["status"] == "completed", report
    assert report["model"] == "claude:default"
    assert report["document"]["summary"] == "Report generated with Claude."
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200
    assert claude[-1].options.output_format["type"] == "json_schema"
    assert client.app.state.manager.workers == {}


def test_disconnect_is_provider_specific_and_new_login_cannot_reuse_previous_account_threads(client, admin, claude):
    subscribe(client)
    connect_claude(client)
    choose(client, "claude")
    a = client.post("/api/conversations", headers=HEADERS, json={}).json()["id"]
    send(client, a)
    old_thread = client.app.state.db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (a,))["provider_thread_id"]
    assert client.post("/api/subscription/disconnect?provider=claude", headers=HEADERS).status_code == 200
    assert client.get("/api/subscription?provider=chatgpt").json()["connected"] is True
    assert client.get("/api/subscription").json()["connected"] is False
    assert client.app.state.db.all("SELECT * FROM conversation_provider_threads WHERE conversation_id=?", (a,)) == []
    connect_claude(client)
    send(client, a)
    assert client.app.state.db.one("SELECT provider_thread_id FROM conversations WHERE id=?", (a,))["provider_thread_id"] != old_thread
    assert "previous_messages" in claude[-1].content


def test_claude_auth_code_is_csrf_protected_and_pending_account_uses_connected_chatgpt(client, admin, claude):
    assert client.post("/api/subscription/select", json={"provider": "claude"}).status_code == 403
    login = client.post("/api/subscription/login?provider=claude", headers=HEADERS).json()
    assert client.post("/api/subscription/login/code", headers=HEADERS, json={"login_id": "wrong", "code": "private-code"}).status_code == 409
    assert client.post("/api/subscription/login/code", headers=HEADERS, json={"login_id": login["loginId"], "code": "one\ntwo"}).status_code == 409
    subscribe(client)
    choose(client, "claude")
    chat = client.post("/api/conversations", headers=HEADERS, json={}).json()["id"]
    response = client.post(f"/api/conversations/{chat}/messages", headers=HEADERS, json={"content": "Hello"})
    assert response.status_code == 200 and '"status": "completed"' in response.text
    assert claude == []  # A pending Claude login does not block connected ChatGPT inference.
    assert len(client.app.state.db.all("SELECT * FROM messages")) == 2


async def test_tools_forward_original_schemas_and_user_chat_context_without_builtin_tools(tmp_path, monkeypatch):
    import claude_agent_sdk as sdk
    from app.config import Settings
    captured, calls = [], []

    async def handle(user, params):
        calls.append((user, params))
        return {"success": False, "contentItems": [{"type": "inputText", "text": '{"error":"Not granted"}'}]}

    def server(**kwargs):
        captured.extend(kwargs["tools"])
        return {"type": "sdk", "name": kwargs["name"], "instance": None}

    monkeypatch.setattr(sdk, "create_sdk_mcp_server", server)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-api-key")
    monkeypatch.setenv("SQLSERVER_PASSWORD", "secret-db-password")
    runtime = ClaudeRuntime(Settings(data_dir=tmp_path, env_file=None), "owner", handle)
    runtime.tool_server("claude-thread", "turn")
    tool = next(t for t in captured if t.name == "calculate_data")
    result = await tool.handler({"source_id": "authorized-source"})
    assert result["isError"] is True
    assert calls == [("owner", {"namespace": "duka_reporting", "tool": "calculate_data",
                                  "arguments": {"source_id": "authorized-source"}, "threadId": "claude-thread", "turnId": "turn"})]
    options = runtime.options()
    assert options.env["ANTHROPIC_API_KEY"] == "" and options.env["SQLSERVER_PASSWORD"] == ""
    assert "ANTHROPIC_API_KEY" not in runtime.environment()
    assert options.tools == ["WebSearch", "WebFetch"] and options.allowed_tools == []
    assert set(t.name for t in captured).isdisjoint({"Bash", "Read", "Edit", "WebFetch", "Agent"})


async def test_non_subscription_credentials_fail_closed(client, admin, claude):
    runtime = client.app.state.manager.for_user(admin["id"], "claude")
    runtime.prepare()
    (runtime.home / "fixture-account.json").write_text(json.dumps({"loggedIn": True, "authMethod": "api_key"}))
    with pytest.raises(ProviderError, match="subscription"):
        await runtime.account()


def test_provider_login_urls_reject_arbitrary_redirects():
    assert login_url("https://claude.com/cai/oauth/authorize?state=public")
    assert not login_url("https://claude.com.evil.example/oauth/authorize")
    assert not login_url("http://claude.com/oauth/authorize")
    assert not login_url("https://evil.example/oauth/authorize")


def test_runtimes_on_one_login_share_status_and_models(client, admin, monkeypatch):
    import asyncio
    from app.claude_provider import ClaudeRuntime

    reads = []

    async def status(self, *args):
        reads.append(args)
        return 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "claude@example.com"}).encode()

    monkeypatch.setattr(ClaudeRuntime, "auth_command", status)
    manager = client.app.state.manager
    # A chat worker created after switching providers is a new runtime object.
    first = manager.runtime(admin["id"], "claude", "chat/one")
    second = manager.runtime(admin["id"], "claude", "chat/two")

    async def both():
        return await first.account(), await second.account()

    assert all(result["connected"] for result in asyncio.run(both()))
    assert reads == [("status",)]
    first.model_catalog = [{"model": "claude:default"}]
    assert second.model_catalog == [{"model": "claude:default"}]
    # Signing out on one runtime is seen by every runtime on that login.
    first.account_cache = first.last_connected = first.model_catalog = None
    assert second.model_catalog is None and second.account_cache is None
