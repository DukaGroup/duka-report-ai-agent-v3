"""Replacement/deletion are serialized with accepted native work for both providers."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.claude_provider import ClaudeRuntime
from app.provider import CodexRuntime
from app.schemas import ChatMessage
from conftest import HEADERS
from test_chat_controls import prepare, claude as claude_fixture


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


def endpoint(client, path, method):
    return next(r.endpoint for r in client.app.routes if getattr(r, 'path', '') == path and method in r.methods)


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_replace_upload_and_delete_running_chat(client, admin, claude, monkeypatch, provider):
    cid = prepare(client, provider)
    state = client.app.state
    calls, cancelled = [], []

    async def held(self, thread, content, *args, **kwargs):
        calls.append(content)
        try:
            yield {'type': 'delta', 'text': 'Partial investigation'}
            await asyncio.Event().wait()
        finally:
            cancelled.append(content)

    monkeypatch.setattr(CodexRuntime if provider == 'chatgpt' else ClaudeRuntime, 'stream', held)
    send = endpoint(client, '/api/conversations/{conversation_id}/messages', 'POST')
    delete = endpoint(client, '/api/conversations/{conversation_id}', 'DELETE')
    request = SimpleNamespace(app=client.app)

    async def held_report(db, manager, identifier, *args):
        db.execute("UPDATE reports SET status='running' WHERE id=?", (identifier,))
        await asyncio.Event().wait()

    monkeypatch.setattr('app.main.generate_report', held_report)

    def report():
        response = client.post('/api/reports', headers=HEADERS, json={
            'title': 'Preserved report', 'conversation_id': cid, 'rows': [{'value': 10}]})
        assert response.status_code == 201
        return response.json()['id']

    async def begin(body):
        await send(cid, body, request, admin)
        for _ in range(100):
            await asyncio.sleep(.01)
            row = state.db.one("SELECT * FROM chat_runs WHERE conversation_id=? AND status='running'", (cid,))
            if row and state.db.one('SELECT content FROM messages WHERE id=?', (row['id'],))['content']:
                return row['id']
        raise AssertionError('Native response did not start')

    first = client.portal.call(begin, ChatMessage(content='Original', request_id='original'))
    upload = client.post(f'/api/conversations/{cid}/attachments', headers=HEADERS,
                         files={'file': ('next.csv', b'name,value\nA,10', 'text/csv')})
    assert upload.status_code == 201, upload.text
    assert len(calls) == 1 and not cancelled
    assert state.attachments.sent_files(admin['id'], cid) == []  # unsent upload stays out of native context
    attachment = upload.json()['id']
    first_report = report()

    async def replace_and_reconnect():
        # Validation happens before interruption, including ownership of attachments.
        with pytest.raises(HTTPException) as invalid:
            await send(cid, ChatMessage(content='Invalid', interrupt_current=True, attachment_ids=['missing']), request, admin)
        assert invalid.value.status_code == 404
        assert not cancelled
        second = await begin(ChatMessage(content='Replacement', interrupt_current=True, request_id='replacement', attachment_ids=[attachment]))
        assert state.db.one('SELECT status FROM chat_runs WHERE id=?', (first,))['status'] == 'interrupted'
        assert len(cancelled) == 1
        assert len(calls) == 2
        assert state.db.one('SELECT stage FROM reports WHERE id=?', (first_report,))['stage'] == 'interrupted'
        assert 'Replacement' in calls[-1]
        assert attachment in calls[-1]
        # Replayed POST must reconnect the old request without stopping its successor.
        await send(cid, ChatMessage(content='Original', request_id='original', interrupt_current=True), request, admin)
        assert state.db.one('SELECT status FROM chat_runs WHERE id=?', (second,))['status'] == 'running'
        assert len(cancelled) == 1
        await delete(cid, request, admin)
        assert len(cancelled) == 2
        assert state.db.one('SELECT conversation_id FROM conversation_trash WHERE conversation_id=?', (cid,))
        assert not state.db.one("SELECT id FROM chat_runs WHERE conversation_id=? AND status IN ('queued','running','paused')", (cid,))
        assert not state.locks[cid].locked()
        assert (admin['id'], 'chat', cid) not in state.manager.worker_leases
        await asyncio.sleep(.05)
        with state.db.connect() as c:
            assert not c.execute('PRAGMA foreign_key_check').fetchall()
        assert not state.chat_jobs.tasks
        saved = state.db.one('SELECT * FROM reports WHERE id=?', (first_report,))
        assert saved['conversation_id'] == cid and saved['stage'] == 'interrupted'

    client.portal.call(replace_and_reconnect)
    assert client.get(f'/api/conversations/{cid}').status_code == 404


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_stop_before_job_first_scheduling_turn_releases_resources(client, admin, claude, provider):
    cid = prepare(client, provider)
    state = client.app.state
    send = endpoint(client, '/api/conversations/{conversation_id}/messages', 'POST')
    request = SimpleNamespace(app=client.app)

    async def immediate_stop():
        await send(cid, ChatMessage(content='Stop immediately'), request, admin)
        await state.chat_jobs.stop(cid)
        assert not state.locks[cid].locked()
        assert (admin['id'], 'chat', cid) not in state.manager.worker_leases
        job = state.db.one('SELECT * FROM chat_runs WHERE conversation_id=?', (cid,))
        assert job['status'] == 'interrupted'
        assert not state.chat_jobs.pending_resources
        response = await send(cid, ChatMessage(content='Next request'), request, admin)
        async for line in response.body_iterator:
            assert json.loads(line)['type'] != 'error'

    client.portal.call(immediate_stop)


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
@pytest.mark.parametrize('interrupt_fails', [False, True])
def test_rapid_replacements_and_delete_leave_no_late_work(client, admin, claude, monkeypatch, provider, interrupt_fails):
    cid = prepare(client, provider)
    state = client.app.state

    if interrupt_fails:
        async def unavailable(*args):
            raise RuntimeError('Provider transport closed')
        monkeypatch.setattr(state.manager, 'interrupt_worker', unavailable)

    async def held(self, *args, **kwargs):
        yield {'type': 'delta', 'text': 'Partial'}
        await asyncio.Event().wait()

    monkeypatch.setattr(CodexRuntime if provider == 'chatgpt' else ClaudeRuntime, 'stream', held)
    send = endpoint(client, '/api/conversations/{conversation_id}/messages', 'POST')
    delete = endpoint(client, '/api/conversations/{conversation_id}', 'DELETE')
    request = SimpleNamespace(app=client.app)

    async def race():
        await send(cid, ChatMessage(content='Initial'), request, admin)
        await asyncio.gather(*[
            send(cid, ChatMessage(content=f'Replace {i}', request_id=f'key-{i}', interrupt_current=True), request, admin)
            for i in range(3)
        ])
        jobs = state.db.all('SELECT status FROM chat_runs WHERE conversation_id=? ORDER BY rowid', (cid,))
        assert len(jobs) == 4
        assert all(j['status'] == 'interrupted' for j in jobs[:-1])
        assert jobs[-1]['status'] in ('queued', 'running')
        assert len(state.manager.worker_leases) == 1
        await delete(cid, request, admin)
        with pytest.raises(HTTPException) as missing:
            await send(cid, ChatMessage(content='Too late', interrupt_current=True), request, admin)
        assert missing.value.status_code == 404
        assert not state.locks[cid].locked()
        assert not state.manager.worker_leases
        assert not state.chat_jobs.pending_resources

    client.portal.call(race)
