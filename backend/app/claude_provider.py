"""Claude subscriptions through the official SDK; no API-key billing fallback."""

import asyncio
import contextlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

from .provider import BASE_INSTRUCTIONS, REPORT_TOOLS, ProviderError


def login_url(value):
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname in ("claude.com", "claude.ai", "platform.claude.com") and "oauth" in parsed.path


class ClaudeRuntime:
    provider = "claude"

    def __init__(self, settings, user_id, tool_handler, scope=None):
        self.settings, self.user_id, self.tool_handler = settings, user_id, tool_handler
        self.home = settings.data_dir / "claude" / user_id
        self.workspace = settings.data_dir / "claude-workspaces" / user_id / (scope or "subscription")
        self.traffic = getattr(getattr(tool_handler, "__self__", None), "traffic", None)
        self.active_turns, self.sessions, self.clients = {}, set(), {}
        self.login, self.login_process, self.login_task = None, None, None
        self.login_lock = asyncio.Lock()
        self.model_catalog = None

    def prepare(self):
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        return self.home

    def binary(self):
        if self.settings.claude_binary:
            return self.settings.claude_binary
        try:
            import claude_agent_sdk
        except ImportError as exc:
            raise ProviderError("Claude SDK is unavailable. Rebuild the application image.") from exc
        return str(Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")

    def environment(self, sdk=False):
        # The SDK merges env over the parent. Explicitly blank everything else,
        # including API keys, cloud credentials and business database settings.
        allowed = {"PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"}
        env = {key: value if key in allowed else "" for key, value in os.environ.items()} if sdk else {
            key: value for key, value in os.environ.items() if key in allowed
        }
        env.update(CLAUDE_CONFIG_DIR=str(self.prepare()), BROWSER="false",
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1")
        return env

    async def auth_command(self, *args):
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary(), "auth", *args, cwd=self.prepare(), env=self.environment(),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
        except FileNotFoundError as exc:
            raise ProviderError("Claude CLI is unavailable. Rebuild the application image.") from exc
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 20)
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            raise
        return process.returncode, output

    async def account(self):
        _, output = await self.auth_command("status")
        try:
            status = json.loads(output)
        except (ValueError, UnicodeError) as exc:
            raise ProviderError("Claude subscription status could not be read. Reconnect Claude.") from exc
        connected = bool(status.get("loggedIn"))
        if connected and status.get("authMethod") not in ("claude.ai", "oauth_token"):
            raise ProviderError("Use a Claude subscription login. API-key and Console billing are not enabled.")
        return {"connected": connected, "account": {
            "email": status.get("email"), "planType": status.get("subscriptionType") or "Claude",
        } if connected else None, "login": self.login}

    async def require_account(self):
        if not (await self.account())["connected"]:
            raise ProviderError("Connect your Claude subscription before sending a message.", category="auth")

    async def begin_login(self):
        async with self.login_lock:
            await self.cancel_login()
            self.model_catalog = None
            self.login = {"loginId": str(uuid4()), "status": "pending", "provider": "claude", "requiresCode": True}
            try:
                self.login_process = await asyncio.create_subprocess_exec(
                    self.binary(), "auth", "login", "--claudeai", cwd=self.prepare(), env=self.environment(),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                )
            except FileNotFoundError as exc:
                self.login = None
                raise ProviderError("Claude CLI is unavailable. Rebuild the application image.") from exc
            ready = asyncio.Event()
            self.login_task = asyncio.create_task(self.read_login(self.login_process, ready))
            try:
                await asyncio.wait_for(ready.wait(), 20)
            except TimeoutError:
                await self.cancel_login()
                self.login.update(status="failed", error="Claude login did not start. Try connecting again.")
            return dict(self.login)

    async def read_login(self, process, ready):
        text = ""
        try:
            async with asyncio.timeout(600):
                while chunk := await process.stdout.read(4096):
                    # Only return the provider's public authorization URL, never
                    # raw CLI output, credential files, or token/error payloads.
                    text = (text + chunk.decode(errors="replace"))[-24000:]
                    for match in re.finditer(r"https://[^\s\x1b]+(?=[\s\x1b])", text):
                        value = match.group().rstrip('"<>')
                        if login_url(value):
                            self.login["verificationUrl"] = value
                            ready.set()
                code = await process.wait()
                self.login.update(status="completed" if code == 0 else "failed")
                if code:
                    self.login["error"] = "Claude login did not complete. Start a new connection and try again."
        except TimeoutError:
            self.login.update(status="failed", error="Claude login expired. Start a new connection.")
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
        finally:
            ready.set()

    async def finish_login(self, login_id, code):
        async with self.login_lock:
            if not self.login or self.login["loginId"] != login_id or self.login["status"] != "pending" or not self.login_process or self.login_process.returncode is not None:
                raise ProviderError("This Claude login has expired. Start a new connection.")
            code = code.strip()
            if not code or len(code) > 4096 or "\n" in code or "\r" in code:
                raise ProviderError("Paste the single-use code shown by Claude after signing in.")
            self.login_process.stdin.write((code + "\n").encode())
            await self.login_process.stdin.drain()
            return {"status": "pending"}

    async def cancel_login(self):
        if self.login_process and self.login_process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.login_process.terminate()
            await self.login_process.wait()
        if self.login_task:
            self.login_task.cancel()
            await asyncio.gather(self.login_task, return_exceptions=True)
        self.login_process = self.login_task = None

    async def logout(self):
        await self.cancel_login()
        await self.auth_command("logout")
        self.login = None
        self.sessions.clear()
        self.model_catalog = None

    def options(self, model=None, **kwargs):
        from claude_agent_sdk import ClaudeAgentOptions
        return ClaudeAgentOptions(
            tools=[], permission_mode="dontAsk", setting_sources=[], strict_mcp_config=True,
            cwd=str(self.workspace), cli_path=self.binary(), env=self.environment(sdk=True),
            system_prompt=BASE_INSTRUCTIONS, model=model.removeprefix("claude:") if model else None,
            settings=json.dumps({"forceLoginMethod": "claudeai", "disableAllHooks": True}),
            # --bare disables subscription OAuth. Use restricted mode with an
            # empty built-in toolset, private directories and explicit MCP only.
            extra_args={"restricted": None, "no-chrome": None, "disable-slash-commands": None,
                        "system-prompt-snapshot": "off"},
            stderr=lambda _: None, **kwargs,
        )

    async def models(self):
        from claude_agent_sdk import ClaudeSDKClient
        await self.require_account()
        if self.model_catalog is not None:
            return self.model_catalog
        try:
            async with ClaudeSDKClient(self.options()) as client:
                info = await client.get_server_info()
            self.model_catalog = [{"id": "claude:" + model["value"], "model": "claude:" + model["value"],
                     "displayName": model.get("displayName") or model["value"], "isDefault": index == 0,
                     "description": model.get("description", ""),
                     "resolved_model": 'claude:' + model['resolvedModel'] if model.get('resolvedModel') else None,
                     "supported_reasoning_efforts": model.get("supportedEffortLevels", []) if model.get("supportsEffort") else [],
                     "default_reasoning_effort": None}
                    for index, model in enumerate((info or {}).get("models", []))]
            # Native CLI catalogs usually advertise aliases (default/opus), not
            # version IDs. Add the verified resolved target so handoff can pin
            # Opus 5.5 and the same ID stays selectable/valid after reopening.
            target = 'claude:claude-opus-5-5'
            resolved = next((m for m in self.model_catalog if m.get('resolved_model') == target), None)
            if resolved and not any(m['model'] == target for m in self.model_catalog):
                self.model_catalog.append({**resolved, 'id': target, 'model': target, 'displayName': 'Claude Opus 5.5', 'isDefault': False})
            if not self.model_catalog:
                raise ProviderError("Claude returned no available models. Check your subscription connection.")
            return self.model_catalog
        except Exception as exc:
            raise ProviderError("Claude models could not be loaded. Check your subscription connection.") from exc

    async def thread(self, thread_id, model):
        await self.require_account()
        if thread_id and thread_id.startswith("claude:"):
            try:
                UUID(thread_id.removeprefix("claude:"))
                if thread_id in self.sessions or any((self.home / "projects").glob("*/" + thread_id.removeprefix("claude:") + ".jsonl")):
                    return thread_id
            except ValueError:
                pass
        return "claude:" + str(uuid4())

    def tool_server(self, thread_id, turn_id):
        from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server
        tools = []
        for definition in REPORT_TOOLS[0]["tools"]:
            async def invoke(arguments, name=definition["name"]):
                response = await self.tool_handler(self.user_id, {
                    "namespace": "duka_reporting", "tool": name, "arguments": arguments,
                    "threadId": thread_id, "turnId": turn_id,
                })
                return {"content": [{"type": "text", "text": item["text"]} for item in response["contentItems"]],
                        "isError": not response["success"]}
            tools.append(SdkMcpTool(definition["name"], definition["description"], definition["inputSchema"], invoke))
        return create_sdk_mcp_server(name="duka_reporting", version="1.0.0", tools=tools)

    async def stream(self, thread_id, content, model=None, output_schema=None, reasoning_effort=None):
        from .response_stream import keepalive
        try:
            async with contextlib.aclosing(keepalive(self._stream(thread_id, content, model, output_schema, reasoning_effort),
                                                   timeout=self.settings.turn_timeout or None)) as events:
                async for event in events:
                    yield event
        except TimeoutError as exc:
            raise ProviderError("Claude reached the configured response time limit. Try again.") from exc

    async def _stream(self, thread_id, content, model=None, output_schema=None, reasoning_effort=None):
        from claude_agent_sdk import ClaudeSDKClient, AssistantMessage, TextBlock, ToolUseBlock, StreamEvent, ResultMessage
        from claude_agent_sdk.types import RateLimitEvent
        if thread_id in self.active_turns:
            raise ProviderError("A response is already running in this conversation.")
        session = thread_id.removeprefix("claude:")
        # Each native session is restricted to its user's private config tree.
        persisted = any((self.home / "projects").glob("*/" + session + ".jsonl"))
        turn = str(uuid4())
        self.active_turns[thread_id] = turn
        options = self.options(model, effort=reasoning_effort, mcp_servers={"duka_reporting": self.tool_server(thread_id, turn)},
                               allowed_tools=["mcp__duka_reporting__" + t["name"] for t in REPORT_TOOLS[0]["tools"]],
                               include_partial_messages=True,
                               output_format={"type": "json_schema", "schema": output_schema} if output_schema else None,
                               **({"resume": session} if persisted else {"session_id": session}))
        fragments, partial = [], False
        try:
            client = ClaudeSDKClient(options)
            # Include initialization in the stop path, before __aenter__ awaits.
            self.clients[thread_id] = client
            async with client:
                await client.query(content)
                yield {"type": "started", "turn_id": turn}
                async for message in client.receive_response():
                    if isinstance(message, RateLimitEvent) and message.rate_limit_info.status == "rejected":
                        raise ProviderError("Claude subscription usage limit reached.", category="quota", reset_at=message.rate_limit_info.resets_at)
                    if isinstance(message, StreamEvent):
                        delta = message.event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            partial = True
                            fragments.append(delta["text"])
                            yield {"type": "delta", "text": delta["text"]}
                    elif isinstance(message, AssistantMessage):
                        if message.error:
                            from .provider import native_error
                            error_text = ' '.join(block.text for block in message.content if isinstance(block, TextBlock))
                            raise native_error({"error": message.error, "message": error_text or "Claude subscription: " + message.error})
                        for block in message.content:
                            if isinstance(block, ToolUseBlock):
                                yield {"type": "tool", "name": block.name.removeprefix("mcp__duka_reporting__")}
                            elif isinstance(block, TextBlock) and not partial:
                                fragments.append(block.text)
                                yield {"type": "delta", "text": block.text}
                    elif isinstance(message, ResultMessage):
                        if message.is_error:
                            from .provider import native_error
                            raise native_error({"subtype": message.subtype, "message": message.result or "Claude could not complete this response.",
                                                "error": "rate_limit" if message.api_error_status == 429 else "authentication_failed" if message.api_error_status == 401 else ""})
                        text = json.dumps(message.structured_output, ensure_ascii=False) if message.structured_output is not None else message.result or "".join(fragments)
                        self.sessions.add(thread_id)
                        status = "interrupted" if message.terminal_reason in ("aborted_streaming", "aborted_tools") else "completed"
                        yield {"type": "done", "status": status, "text": text}
                        return
                raise ProviderError("Claude stopped before completing its response. Try again.")
        except ProviderError:
            raise
        except Exception as exc:
            # SDK/CLI exceptions can contain auth material; never expose them.
            from claude_agent_sdk import ProcessError
            if isinstance(exc, ProcessError):
                from .provider import native_error
                error = native_error({'message': str(exc)})
                if error.category in ('quota', 'auth'):
                    raise ProviderError('Claude subscription is unavailable.', category=error.category) from exc
            raise ProviderError("Claude connection failed. Check your subscription connection and try again.") from exc
        finally:
            self.clients.pop(thread_id, None)
            self.active_turns.pop(thread_id, None)

    async def interrupt(self, thread_id):
        client = self.clients.get(thread_id)
        if client:
            await client.interrupt()

    def request_stop(self):
        from .process_stop import request_process_stop
        for client in list(self.clients.values()):
            # Pinned SDK 0.2.168 owns this subprocess. Only signal it here;
            # SDK connect/receive/disconnect still unwind in their owning task.
            transport = getattr(client, "_transport", None)
            request_process_stop(getattr(transport, "_process", None))

    async def close(self):
        await self.cancel_login()
        for thread_id in list(self.clients):
            await self.interrupt(thread_id)
