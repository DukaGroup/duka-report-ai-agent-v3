"""Bulk conversation deletion preserves ownership, other work and saved reports."""
import asyncio
from types import SimpleNamespace

import pytest

from app.db import now
from app.provider import CodexRuntime
from app.claude_provider import ClaudeRuntime
from app.schemas import ChatMessage, ConversationSelection
from conftest import HEADERS
from test_application import create_member
from test_conversation_isolation import new_chat
from test_chat_controls import prepare, claude as claude_fixture
from test_live_conversation_controls import endpoint
from test_report_selection import report


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


def delete(client, ids):
    return client.post('/api/conversations/bulk-delete', headers=HEADERS, json={'conversation_ids': ids})


def test_exact_selection_keeps_other_history_and_saved_exports(client, admin):
    db = client.app.state.db
    ids = [new_chat(client) for _ in range(3)]
    for cid in ids:
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', (cid+'-message', cid, 'user', 'Fixture', 'completed', now()))
    export, _ = report(client, admin['id'], 'saved')
    db.execute("UPDATE reports SET conversation_id=? WHERE id='saved'", (ids[0],))
    assert client.post('/api/conversations/bulk-delete', json={'conversation_ids': ids[:2]}).status_code == 403
    response = delete(client, ids[:2]+ids[:1])
    assert response.status_code == 200 and response.json()['deleted_count'] == 2
    for cid in ids[:2]:
        assert client.get('/api/conversations/'+cid).status_code == 404
        assert db.one('SELECT id FROM messages WHERE conversation_id=?', (cid,))
    assert client.get('/api/conversations/'+ids[2]).status_code == 200
    assert db.one("SELECT conversation_id FROM reports WHERE id='saved'")['conversation_id'] == ids[0]
    assert export.read_bytes() == b'saved'
    assert len(db.all("SELECT id FROM audit_events WHERE action='conversation.trashed'")) == 2
    with db.connect() as connection:
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('unavailable', ['foreign', 'missing'])
def test_unavailable_selection_does_not_interrupt_or_delete_anything(client, admin, monkeypatch, unavailable):
    db = client.app.state.db
    own = new_chat(client)
    if unavailable == 'foreign':
        other = create_member(client)
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)', ('foreign',other['id'],'Other',None,None,now(),now()))
    stopped = []
    async def stop(cid):
        stopped.append(cid)
    monkeypatch.setattr(client.app.state.chat_jobs, 'stop', stop)
    assert delete(client, [own, unavailable]).status_code == 404
    assert not stopped and client.get('/api/conversations/'+own).status_code == 200
    with pytest.raises(LookupError):
        db.delete_conversations(admin['id'], [own, unavailable])
    assert db.one('SELECT id FROM conversations WHERE id=?', (own,))


@pytest.mark.parametrize('ids', [[], ['../bad'], ['a'*129], ['a']*5001])
def test_invalid_selection_is_rejected(client, admin, ids):
    assert delete(client, ids).status_code == 422


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
@pytest.mark.parametrize('deletion_endpoint', ['/api/conversations/bulk-delete', '/api/conversations/bulk-purge'])
def test_bulk_delete_stops_only_selected_running_chats_for_both_providers(client, admin, claude, monkeypatch, provider, deletion_endpoint):
    state = client.app.state
    selected = [prepare(client, provider), new_chat(client)]
    kept = new_chat(client)
    # New conversations inherit the selected provider; all native workers remain isolated.
    cancelled = []
    async def held(self, thread, content, *args, **kwargs):
        try:
            yield {'type':'delta','text':'Partial investigation'}
            await asyncio.Event().wait()
        finally:
            cancelled.append(content)
    monkeypatch.setattr(CodexRuntime if provider == 'chatgpt' else ClaudeRuntime, 'stream', held)
    send = endpoint(client, '/api/conversations/{conversation_id}/messages', 'POST')
    bulk = endpoint(client, deletion_endpoint, 'POST')
    request = SimpleNamespace(app=client.app)
    async def run():
        for cid in [*selected, kept]:
            await send(cid, ChatMessage(content=cid), request, admin)
        for _ in range(200):
            if len(state.db.all("SELECT id FROM messages WHERE role='assistant' AND content!=''")) == 3:
                break
            await asyncio.sleep(.01)
        else:
            raise AssertionError('All three workers must start')
        result = await bulk(ConversationSelection(conversation_ids=selected), request, admin)
        assert result['deleted_count'] == 2
        assert len(cancelled) == 2
        assert state.db.one("SELECT id FROM chat_runs WHERE conversation_id=? AND status='running'", (kept,))
        assert state.locks[kept].locked()
        for cid in selected:
            assert not state.locks[cid].locked()
            assert not state.db.one("SELECT id FROM chat_runs WHERE conversation_id=? AND status IN ('queued','running','paused')", (cid,))
            assert (admin['id'], 'chat', cid) not in state.manager.worker_leases
            if deletion_endpoint.endswith('bulk-purge'):
                assert not state.db.one('SELECT id FROM conversations WHERE id=?', (cid,))
        # Reverse overlapping selections must release locks and fail cleanly.
        with pytest.raises(Exception) as error:
            await bulk(ConversationSelection(conversation_ids=list(reversed(selected))), request, admin)
        assert error.value.status_code == 404
        assert state.db.one('SELECT id FROM conversations WHERE id=?', (kept,))
    client.portal.call(run)
