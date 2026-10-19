"""Stop latency cannot depend on provider RPC acknowledgement or serialized cleanup."""
import asyncio
import contextlib
import sys
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.claude_provider import ClaudeRuntime
from app.config import Settings
from app.provider import CodexRuntime
from app.schemas import ChatMessage
from conftest import HEADERS
from test_chat_controls import prepare, claude as claude_fixture
from test_live_conversation_controls import endpoint


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_stop_skips_hung_interrupt_and_stops_all_jobs_together(client, admin, claude, monkeypatch, provider):
    cid = prepare(client, provider)
    state = client.app.state
    interrupts = []

    async def unresponsive(*args):
        interrupts.append(args)
        await asyncio.Event().wait()

    async def held(self, *args, **kwargs):
        yield {'type': 'delta', 'text': 'Partial answer'}
        await asyncio.Event().wait()

    async def slow_cleanup(db, manager, rid, *args):
        try:
            db.execute("UPDATE reports SET status='running' WHERE id=?", (rid,))
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(.15)

    monkeypatch.setattr(state.manager, 'interrupt_worker', unresponsive)
    monkeypatch.setattr(CodexRuntime if provider == 'chatgpt' else ClaudeRuntime, 'stream', held)
    monkeypatch.setattr('app.main.generate_report', slow_cleanup)
    send = endpoint(client, '/api/conversations/{conversation_id}/messages', 'POST')
    stop = endpoint(client, '/api/conversations/{conversation_id}/stop', 'POST')
    request = SimpleNamespace(app=client.app)

    async def begin():
        await send(cid, ChatMessage(content='Investigate'), request, admin)
        await asyncio.sleep(.05)
    client.portal.call(begin)
    reports = [client.post('/api/reports', headers=HEADERS, json={
        'conversation_id': cid, 'title': 'Held', 'rows': [{'value': 10}]}).json()['id'] for _ in range(2)]

    async def measure():
        started = time.monotonic()
        result = await asyncio.wait_for(stop(cid, request, admin), timeout=1)
        elapsed = time.monotonic() - started
        assert elapsed < .8
        assert not interrupts
        assert result['message']['status'] == 'interrupted'
        assert result['message']['content'] == 'Partial answer'
        assert set(result['interrupted_report_ids']) == set(reports)
        assert not state.manager.worker_leases
        assert not state.locks[cid].locked()
        return elapsed
    assert client.portal.call(measure) < .8


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
@pytest.mark.parametrize('phase', ['discovery', 'thread'])
def test_stop_during_startup_cannot_resubmit_the_cancelled_request(client, admin, claude, monkeypatch, provider, phase):
    cid = prepare(client, provider)
    state = client.app.state
    send = endpoint(client, '/api/conversations/{conversation_id}/messages', 'POST')
    stop = endpoint(client, '/api/conversations/{conversation_id}/stop', 'POST')
    request = SimpleNamespace(app=client.app)

    async def run():
        reached = asyncio.Event()
        async def blocked(*args, **kwargs):
            reached.set()
            await asyncio.Event().wait()
        if phase == 'discovery':
            monkeypatch.setattr(state.manager.pool, 'available_control', blocked)
        else:
            monkeypatch.setattr(CodexRuntime if provider == 'chatgpt' else ClaudeRuntime, 'thread', blocked)
        body = ChatMessage(content='ca bone?', request_id='cancel-before-accept')
        pending = asyncio.create_task(send(cid, body, request, admin))
        await asyncio.wait_for(reached.wait(), 1)
        result = await asyncio.wait_for(stop(cid, request, admin), 1)
        assert result['cancelled_before_start'] is True
        with pytest.raises(HTTPException) as interrupted:
            await pending
        assert interrupted.value.status_code == 410
        with pytest.raises(HTTPException) as retry:
            await send(cid, body, request, admin)
        assert retry.value.status_code == 410
        assert not state.db.one('SELECT id FROM chat_runs WHERE conversation_id=?', (cid,))
        assert not state.manager.worker_leases
        assert not state.pending_chat_submissions
        assert not state.locks.get(cid, asyncio.Lock()).locked()
        assert state.db.one('SELECT * FROM chat_request_cancellations WHERE request_key=?', (body.request_id,))
    client.portal.call(run)


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
async def test_native_stop_kills_stubborn_owned_process_without_touching_another_chat(tmp_path, provider):
    code = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'
    processes = [await asyncio.create_subprocess_exec(sys.executable, '-c', code,
                 stdout=asyncio.subprocess.PIPE, start_new_session=True) for _ in range(2)]
    try:
        for process in processes:
            assert await process.stdout.readline() == b'ready\n'
        settings = Settings(data_dir=tmp_path)
        settings.prepare()
        runtime = (CodexRuntime if provider == 'chatgpt' else ClaudeRuntime)(settings, 'actor', None)
        if provider == 'chatgpt':
            runtime.process = processes[0]
        else:
            runtime.clients['thread'] = SimpleNamespace(_transport=SimpleNamespace(_process=processes[0]))
        started = time.monotonic()
        runtime.request_stop()
        await asyncio.wait_for(processes[0].wait(), .8)
        assert time.monotonic() - started < .8
        assert processes[1].returncode is None
    finally:
        for process in processes:
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
            await process.wait()


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_stop_can_overtake_message_post_and_cancellation_survives_restart(client, admin, claude, provider):
    cid = prepare(client, provider)
    stopped = client.post(f'/api/conversations/{cid}/stop', headers=HEADERS,
                          json={'request_id': 'late-arrival'})
    assert stopped.status_code == 200 and stopped.json()['cancelled_before_start']
    # Initial POST arrives late (or a browser retries it), including after DB reopen.
    client.app.state.db.initialize()
    response = client.post(f'/api/conversations/{cid}/messages', headers=HEADERS,
                           json={'content': 'Do not run this', 'request_id': 'late-arrival'})
    assert response.status_code == 410
    assert not client.get(f'/api/conversations/{cid}').json()['messages']
    response = client.post(f'/api/conversations/{cid}/messages', headers=HEADERS,
                           json={'content': 'Next request', 'request_id': 'next'})
    assert response.status_code == 200 and '"status": "completed"' in response.text


@pytest.mark.asyncio
async def test_slow_worker_close_does_not_hold_the_global_registry_lock(client, admin):
    state = client.app.state

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_close():
            entered.set()
            await release.wait()
        key = (admin['id'], 'report', 'slow-report')
        state.manager.workers[key] = SimpleNamespace(close=slow_close)
        state.manager.worker_leases.add(key)
        closing = asyncio.create_task(state.manager.release_worker(*key))
        try:
            await entered.wait()
            async with asyncio.timeout(.1):
                async with state.manager.worker_lock:
                    assert key not in state.manager.workers
                    assert key not in state.manager.worker_leases
        finally:
            release.set()
            await closing
    client.portal.call(run)


def test_stop_request_key_cannot_cancel_another_conversation(client, admin):
    first = prepare(client, 'chatgpt')
    second = client.post('/api/conversations', headers=HEADERS, json={}).json()['id']
    assert client.post(f'/api/conversations/{first}/stop', headers=HEADERS, json={'request_id': 'scope-key'}).status_code == 200
    response = client.post(f'/api/conversations/{second}/stop', headers=HEADERS, json={'request_id': 'scope-key'})
    assert response.status_code == 422
