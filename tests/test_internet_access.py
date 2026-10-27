"""Public web capability stays separate from local files and internal networks."""

import socket
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.internet_access import public_web_fetch
from app.provider import BASE_INSTRUCTIONS, CodexRuntime, READ_ONLY_PROFILE
from app.claude_provider import ClaudeRuntime


@pytest.mark.parametrize("url", [
    "file:///run/duka.env", "ftp://example.com/file", "http://localhost/", "http://localhost./",
    "http://sub.localhost/", "http://server.internal/", "http://database.local/",
    "http://127.0.0.1/", "http://169.254.169.254/latest/meta-data/", "http://10.0.0.1/",
    "http://192.168.1.1/", "http://172.16.0.1/", "http://100.64.0.1/", "http://0.0.0.0/",
    "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[64:ff9b::7f00:1]/",
    "http://[2002:7f00:1::]/", "https://user:password@example.com/", "https://example.com:8080/",
    "http://224.0.0.1/", "http://[ff02::1]/", "http://[fec0::1]/",
    "http://example.com\\@127.0.0.1/", "https://example.com/\nunsafe", "http://2130706433/",
])
async def test_web_fetch_rejects_local_private_and_ambiguous_addresses(url, monkeypatch):
    def resolve(host, port, **kwargs):
        # Mimic OS resolution of private IP spellings, without using real DNS.
        mapping = {"2130706433": "127.0.0.1"}
        address = mapping.get(host, host)
        return [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr("app.internet_access.socket.getaddrinfo", resolve)
    result = await public_web_fetch({"tool_input": {"url": url}})
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "password" not in result["hookSpecificOutput"]["permissionDecisionReason"]


async def test_public_web_fetch_allows_public_dns_but_rejects_mixed_answers(monkeypatch):
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
    monkeypatch.setattr("app.internet_access.socket.getaddrinfo", lambda *args, **kwargs: answers)
    assert await public_web_fetch({"tool_input": {"url": "https://example.com/research"}}) == {}
    answers.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)))
    assert (await public_web_fetch({"tool_input": {"url": "https://example.com/"}}))["hookSpecificOutput"]["permissionDecision"] == "deny"


async def test_dns_failure_does_not_grant_access(monkeypatch):
    def unavailable(*args, **kwargs):
        raise socket.gaierror("fixture failure")
    monkeypatch.setattr("app.internet_access.socket.getaddrinfo", unavailable)
    assert (await public_web_fetch({"tool_input": {"url": "https://missing.example/"}}))["hookSpecificOutput"]["permissionDecision"] == "deny"


async def test_new_and_resumed_chatgpt_threads_have_live_search_with_restricted_permissions(tmp_path):
    runtime = CodexRuntime(Settings(data_dir=tmp_path, env_file=None), "fixture", None)
    runtime.require_account = AsyncMock()
    runtime.rpc = AsyncMock(return_value={"thread": {"id": "new-thread"}})
    assert await runtime.thread(None, None) == "new-thread"
    assert await runtime.thread("existing-thread", None) == "existing-thread"
    for call in runtime.rpc.call_args_list:
        params = call.args[1]
        assert params["config"]["web_search"] == "live"
        assert params["permissions"] == READ_ONLY_PROFILE
        assert params["config"]["features.shell_tool"] is False
        assert params["config"]["features.multi_agent"] is False
        assert params["environments"] == []


def test_claude_only_enables_web_builtins_and_the_public_fetch_guard(tmp_path):
    runtime = ClaudeRuntime(Settings(data_dir=tmp_path, env_file=None), "fixture", None)
    options = runtime.options()
    assert set(options.tools) == {"WebSearch", "WebFetch"}
    assert options.setting_sources == [] and options.strict_mcp_config
    assert options.permission_mode == "dontAsk"
    assert "disableAllHooks" not in options.settings
    hook = options.hooks["PreToolUse"][0]
    assert hook.matcher == "WebFetch" and hook.hooks == [public_web_fetch]
    assert "Never put credentials" in BASE_INSTRUCTIONS
    assert "Never invent current conditions" in BASE_INSTRUCTIONS
