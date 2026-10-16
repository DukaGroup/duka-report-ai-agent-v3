"""Unlimited investigations retain cancellation, optional deadlines and SDK task ownership."""

import asyncio
from contextlib import aclosing
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.provider import CodexRuntime, ProviderError
from app.claude_provider import ClaudeRuntime
from app.response_stream import keepalive
from conftest import HEADERS
from test_claude_subscriptions import claude, connect_claude, choose  # noqa: F401
from test_excel_reports import subscribe


def test_response_limit_defaults_to_disabled_and_negative_values_are_rejected(tmp_path):
    settings = Settings(data_dir=tmp_path, env_file=None)
    assert settings.turn_timeout == 0
    settings.turn_timeout = -1
    with pytest.raises(ValueError, match='TURN_TIMEOUT_SECONDS'):
        settings.prepare()
    settings.turn_timeout = 7200
    settings.prepare()


async def test_quiet_provider_heartbeats_never_cancel_work_or_change_its_task():
    task_ids, closed = [], []
    async def provider():
        task_ids.append(asyncio.current_task())
        try:
            yield {'type': 'started'}
            await asyncio.sleep(.06)
            task_ids.append(asyncio.current_task())
            yield {'type': 'done', 'status': 'completed'}
        finally:
            closed.append(asyncio.current_task())
    events = [e async for e in keepalive(provider(), interval=.01)]
    assert sum(e['type'] == 'heartbeat' for e in events) >= 2
    assert events[-1] == {'type': 'done', 'status': 'completed'}
    assert task_ids[0] is task_ids[1] is closed[0]


async def test_sdk_cleanup_after_final_answer_never_reopens_frontend_typing_indicator():
    async def provider():
        yield {'type': 'done', 'status': 'completed'}
        await asyncio.sleep(.04)
    assert [e async for e in keepalive(provider(), interval=.005)] == [{'type': 'done', 'status': 'completed'}]


@pytest.mark.parametrize('finish', ['deadline', 'disconnect', 'provider_error', 'provider_cancellation'])
async def test_stream_always_closes_provider_and_does_not_hang(finish):
    entered, closed = asyncio.Event(), asyncio.Event()
    async def provider():
        try:
            entered.set()
            yield {'type': 'started'}
            if finish == 'provider_error':
                raise RuntimeError('Connection lost')
            if finish == 'provider_cancellation':
                raise asyncio.CancelledError()
            await asyncio.Event().wait()
        finally:
            closed.set()
    async def consume():
        async with aclosing(keepalive(provider(), timeout=.03 if finish == 'deadline' else None, interval=.01)) as events:
            return [e async for e in events]
    task = asyncio.create_task(consume())
    await entered.wait()
    if finish == 'disconnect':
        task.cancel()
    with pytest.raises({'deadline': TimeoutError, 'disconnect': asyncio.CancelledError,
                        'provider_error': RuntimeError, 'provider_cancellation': RuntimeError}[finish]):
        await asyncio.wait_for(task, .5)
    assert closed.is_set()


@pytest.mark.parametrize('limit', [0, .01])
async def test_codex_no_response_deadline_unless_explicitly_configured(tmp_path, limit):
    runtime = CodexRuntime(Settings(data_dir=tmp_path, turn_timeout=limit, env_file=None), 'fixture', None)
    async def rpc(method, params=None):
        async def finish():
            await asyncio.sleep(.05)
            await runtime.queues['chat'].put({'method': 'turn/completed', 'params': {'turn': {'id': 'turn', 'status': 'completed'}}})
        if method == 'turn/start':
            task = asyncio.create_task(finish())
            runtime.tasks.add(task)
            return {'turn': {'id': 'turn'}}
    runtime.rpc = rpc
    try:
        if limit:
            with pytest.raises(ProviderError, match='server time limit'):
                [e async for e in runtime.stream('chat', 'Investigate')]
        else:
            events = [e async for e in runtime.stream('chat', 'Investigate')]
            assert events[-1]['status'] == 'completed'
        assert runtime.active_turns == {} and runtime.queues == {}
    finally:
        await runtime.close()


@pytest.mark.parametrize('limit', [0, .01])
async def test_claude_unlimited_response_and_deadline_close_sdk_in_same_task(tmp_path, monkeypatch, limit):
    import claude_agent_sdk as sdk
    tasks, closed = [], []
    class Client:
        def __init__(self, options):
            pass
        async def __aenter__(self):
            tasks.append(asyncio.current_task())
            return self
        async def __aexit__(self, *args):
            closed.append(asyncio.current_task())
        async def query(self, content):
            pass
        async def receive_response(self):
            tasks.append(asyncio.current_task())
            await asyncio.sleep(.05)
            yield sdk.ResultMessage(subtype='success', duration_ms=1, duration_api_ms=1, is_error=False,
                                    num_turns=1, session_id='fixture', result='Investigation finished')
    monkeypatch.setattr(sdk, 'ClaudeSDKClient', Client)
    runtime = ClaudeRuntime(Settings(data_dir=tmp_path, turn_timeout=limit, env_file=None), 'fixture', None)
    monkeypatch.setattr(runtime, 'options', lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(runtime, 'tool_server', lambda *args: {})
    if limit:
        with pytest.raises(ProviderError, match='configured response time limit'):
            [e async for e in runtime.stream('claude:fixture', 'Investigate')]
    else:
        events = [e async for e in runtime.stream('claude:fixture', 'Investigate')]
        assert events[-1]['text'] == 'Investigation finished'
    assert len(tasks) == 2 and tasks[0] is tasks[1] is closed[0]
    assert runtime.active_turns == {} and runtime.clients == {}


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
@pytest.mark.usefixtures('claude')
def test_frontend_api_completes_one_slow_request_without_continuation(client, admin, provider, monkeypatch):
    if provider == 'chatgpt':
        subscribe(client)
    else:
        connect_claude(client)
        choose(client, provider)
    runtime_type = CodexRuntime if provider == 'chatgpt' else ClaudeRuntime
    original = runtime_type.stream
    async def delayed(self, *args, **kwargs):
        # Exercise the actual HTTP stream and persistence after quiet keepalives.
        async def source():
            await asyncio.sleep(.05)
            async for event in original(self, *args, **kwargs):
                yield event
        async for event in keepalive(source(), interval=.01):
            yield event
    monkeypatch.setattr(runtime_type, 'stream', delayed)
    chat = client.post('/api/conversations', headers=HEADERS, json={}).json()['id']
    response = client.post(f'/api/conversations/{chat}/messages', headers=HEADERS, json={'content': 'Investigate fully'})
    assert response.status_code == 200
    assert 'heartbeat' in response.text and '"status": "completed"' in response.text
    detail = client.get(f'/api/conversations/{chat}').json()
    assert len(detail['messages']) == 2 and detail['messages'][-1]['status'] == 'completed'
    assert not client.app.state.manager.worker_leases
