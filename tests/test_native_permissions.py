"""Exercise actual native permission validation without credentials or inference billing."""

import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.provider import CodexRuntime, ProviderError, READ_ONLY_PROFILE


@pytest.mark.asyncio
async def test_native_codex_accepts_restricted_turn_permissions(tmp_path):
    binary = os.getenv("NATIVE_CODEX_BINARY") or shutil.which("codex")
    if not binary:
        pytest.skip("Set NATIVE_CODEX_BINARY to exercise the installed Codex CLI.")
    settings = Settings(data_dir=tmp_path / "isolated-native", codex_binary=str(Path(binary).resolve()))
    settings.prepare()
    runtime = CodexRuntime(settings, "permission-regression", None)
    try:
        await runtime.start()
        assert (await runtime.account())["connected"] is False
        profiles = await runtime.rpc("permissionProfile/list", {"cwd": str(runtime.workspace)})
        assert any(p["id"] == READ_ONLY_PROFILE and p["allowed"] for p in profiles["data"])
        # Isolated native process has no credentials. Bypass only the application precheck
        # to test turn request validation; native authentication must still reject inference.
        runtime.require_account = AsyncMock()
        thread_id = await runtime.thread(None, None)
        events = []
        with pytest.raises(ProviderError) as error:
            async for event in runtime.stream(thread_id, "Permission protocol validation only."):
                events.append(event)
        assert events and events[0]["type"] == "started", str(error.value)
        message = str(error.value).lower()
        assert any(word in message for word in ("auth", "token", "sign in", "401")), message
        assert "invalid request" not in message
        # The resumed-thread path must apply the same profile to pre-existing histories.
        runtime.loaded_threads.clear()
        assert await runtime.thread(thread_id, None) == thread_id
        legacy = await runtime.rpc(
            "thread/start",
            {"cwd": str(runtime.workspace), "approvalPolicy": "never", "sandbox": "read-only"},
        )
        # A rejected first turn leaves no saved rollout. Continuing it must recover
        # by creating a new restricted thread rather than trapping the UI in errors.
        replacement = await runtime.thread(legacy["thread"]["id"], None)
        assert replacement != legacy["thread"]["id"]
        assert replacement in runtime.loaded_threads
    finally:
        await runtime.close()
