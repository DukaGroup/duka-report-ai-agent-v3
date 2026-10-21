"""Recoverable deletion and exact, owner-scoped conversation trash purging."""
import asyncio
import json
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


def trash(client, ids, permanent=False):
    return client.post('/api/conversations/bulk-delete', headers=HEADERS,
                       json={'conversation_ids': ids, 'permanent': permanent})


def populated(client, text='Original question'):
    cid = new_chat(client)
    client.app.state.db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', (cid+'-message', cid, 'user', text, 'completed', now()))
    return cid


def test_soft_delete_restore_keeps_history_settings_bindings_uploads_and_report(client, admin):
    cid = populated(client)
    db = client.app.state.db
    for provider in ['chatgpt', 'claude']:
        db.execute('INSERT INTO conversation_provider_threads VALUES(?,?,?)', (cid, provider, provider+'-native'))
    upload = client.post(f'/api/conversations/{cid}/attachments', headers=HEADERS,
                         files={'file': ('notes.txt', b'Original fixture upload')}).json()
    path, snapshot = report(client, admin['id'], 'saved')
    db.execute("UPDATE reports SET conversation_id=? WHERE id='saved'", (cid,))
    before = client.get(f'/api/conversations/{cid}').json()
    assert client.delete(f'/api/conversations/{cid}', headers=HEADERS).status_code == 200
    assert client.get(f'/api/conversations/{cid}').status_code == 404
    assert client.get('/api/conversations').json() == []
    deleted = client.get('/api/conversations?deleted=true').json()
    assert len(deleted) == 1 and deleted[0]['id'] == cid and deleted[0]['deleted_at']
    assert db.one("SELECT conversation_id FROM reports WHERE id='saved'")['conversation_id'] == cid
    assert path.exists() and db.one('SELECT id FROM dataset_snapshots WHERE id=?', (snapshot,))
    # Ordinary chat routes reject a trashed origin.
    for url in [f'/api/conversations/{cid}/messages',f'/api/conversations/{cid}/stop',f'/api/conversations/{cid}/attachments']:
        response = client.post(url, headers=HEADERS, json={} if url.endswith('/stop') else {'content':'Must not run'}) if not url.endswith('/attachments') else client.post(url, headers=HEADERS, files={'file':('bad.txt',b'No')})
        assert response.status_code == 404
    assert client.get(f'/api/conversations/{cid}/versions').status_code == 404
    assert client.post(f'/api/conversations/{cid}/restore').status_code == 403
    assert client.post(f'/api/conversations/{cid}/restore', headers=HEADERS).status_code == 200
    after = client.get(f'/api/conversations/{cid}').json()
    assert after == before and client.get('/api/conversations?deleted=true').json() == []
    assert len(db.all('SELECT * FROM conversation_provider_threads WHERE conversation_id=?',(cid,))) == 2
    assert client.get(f"/api/attachments/{upload['id']}/download").content == b'Original fixture upload'


def test_exact_permanent_selection_keeps_unselected_trash_live_chat_and_exports(client, admin):
    db = client.app.state.db
    a,b,live = [populated(client) for _ in range(3)]
    path, _ = report(client, admin['id'], 'keep-export')
    db.execute("UPDATE reports SET conversation_id=? WHERE id='keep-export'", (a,))
    db.execute('INSERT INTO model_checkpoints VALUES(?,?,?,?,?,?,?,?)', ('evidence',admin['id'],'chat',a,0,'{}','hash',now()))
    assert trash(client,[a,b]).status_code == 200
    assert trash(client,[a,a],True).json()['deleted_count'] == 1
    assert not db.one('SELECT id FROM conversations WHERE id=?',(a,))
    assert not db.one('SELECT id FROM messages WHERE conversation_id=?',(a,))
    assert not db.one("SELECT id FROM model_checkpoints WHERE id='evidence'")
    assert {c['id'] for c in client.get('/api/conversations?deleted=true').json()} == {b}
    assert {c['id'] for c in client.get('/api/conversations').json()} == {live}
    assert db.one("SELECT conversation_id FROM reports WHERE id='keep-export'")['conversation_id'] is None
    assert path.read_bytes() == b'keep-export'
    assert client.post(f'/api/conversations/{a}/restore',headers=HEADERS).status_code == 404
    assert client.post(f'/api/conversations/{b}/restore',headers=HEADERS).status_code == 200
    with db.connect() as connection:
        assert not connection.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('unavailable',['foreign','missing','live'])
def test_invalid_purge_selection_cannot_delete_any_owned_history(client, admin, unavailable):
    db=client.app.state.db
    selected=populated(client)
    assert trash(client,[selected]).status_code == 200
    if unavailable == 'live':
        unavailable=populated(client)
    elif unavailable == 'foreign':
        other=create_member(client)
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',('foreign',other['id'],'Foreign',None,None,now(),now()))
        db.execute('INSERT INTO conversation_trash VALUES(?,?)',('foreign',now()))
    assert trash(client,[selected,unavailable],True).status_code == 404
    assert db.one('SELECT id FROM conversations WHERE id=?',(selected,))
    assert client.post(f'/api/conversations/{unavailable}/restore',headers=HEADERS).status_code == 404


def test_existing_database_migration_is_additive_and_idempotent(client,admin):
    cid=populated(client)
    db=client.app.state.db
    before=db.all('SELECT * FROM conversations')
    db.execute('DROP TABLE conversation_trash')
    db.execute('DELETE FROM schema_migrations WHERE version=14')
    db.initialize();db.initialize()
    assert db.all('SELECT * FROM conversations') == before
    assert db.one('SELECT version FROM schema_migrations WHERE version=14')
    assert client.delete(f'/api/conversations/{cid}',headers=HEADERS).status_code == 200
    db.initialize()
    assert client.get('/api/conversations?deleted=true').json()[0]['id'] == cid


@pytest.mark.parametrize('provider',['chatgpt','claude'])
def test_running_chat_stops_then_restores_and_continues_for_both_providers(client,admin,claude,monkeypatch,provider):
    cid=prepare(client,provider)
    state=client.app.state
    calls=[]
    async def stream(self,thread,content,*args,**kwargs):
        calls.append((thread,content))
        yield {'type':'delta','text':'Preserved partial answer' if len(calls)==1 else 'Continued after restore'}
        if len(calls)==1:
            await asyncio.Event().wait()
        yield {'type':'done','status':'completed'}
    monkeypatch.setattr(CodexRuntime if provider=='chatgpt' else ClaudeRuntime,'stream',stream)
    send=endpoint(client,'/api/conversations/{conversation_id}/messages','POST')
    bulk=endpoint(client,'/api/conversations/bulk-delete','POST')
    restore=endpoint(client,'/api/conversations/{conversation_id}/restore','POST')
    request=SimpleNamespace(app=client.app)
    async def run():
        await send(cid,ChatMessage(content='Original investigation'),request,admin)
        for _ in range(200):
            if calls:break
            await asyncio.sleep(.01)
        assert calls
        await bulk(ConversationSelection(conversation_ids=[cid]),request,admin)
        assert not state.chat_jobs.tasks
        assert not state.db.one("SELECT id FROM chat_runs WHERE conversation_id=? AND status IN ('queued','running','paused')",(cid,))
        assert state.db.one("SELECT id FROM messages WHERE conversation_id=? AND content='Preserved partial answer'",(cid,))
        await restore(cid,request,admin)
        await send(cid,ChatMessage(content='Continue investigation'),request,admin)
        for _ in range(200):
            if len(calls)==2 and not state.chat_jobs.tasks:break
            await asyncio.sleep(.01)
        assert len(calls)==2
        assert state.db.one("SELECT id FROM messages WHERE conversation_id=? AND content='Continued after restore'",(cid,)), state.db.all('SELECT role,content,status FROM messages WHERE conversation_id=?',(cid,))
        assert len(state.db.all("SELECT id FROM messages WHERE conversation_id=? AND role='user'",(cid,)))==2
    client.portal.call(run)


def restore_selected(client, ids):
    return client.post('/api/conversations/bulk-restore', headers=HEADERS, json={'conversation_ids':ids})


def test_bulk_restore_exact_selection_preserves_history_context_and_reports(client, admin):
    db = client.app.state.db
    a,b,kept = [populated(client) for _ in range(3)]
    for cid in [a,b,kept]:
        for provider in ['chatgpt','claude']:
            db.execute('INSERT INTO conversation_provider_threads VALUES(?,?,?)',(cid,provider,cid+'-'+provider))
    path,_ = report(client,admin['id'],'restore-export')
    db.execute("UPDATE reports SET conversation_id=? WHERE id='restore-export'",(a,))
    before = {cid:client.get('/api/conversations/'+cid).json() for cid in [a,b]}
    assert trash(client,[a,b,kept]).status_code == 200
    assert client.post('/api/conversations/bulk-restore', json={'conversation_ids':[a,b]}).status_code == 403
    response = restore_selected(client,[a,b,a])
    assert response.status_code == 200 and response.json()['restored_count'] == 2
    for cid in [a,b]:
        assert client.get('/api/conversations/'+cid).json() == before[cid]
        assert len(db.all('SELECT * FROM conversation_provider_threads WHERE conversation_id=?',(cid,))) == 2
    assert {c['id'] for c in client.get('/api/conversations').json()} == {a,b}
    assert {c['id'] for c in client.get('/api/conversations?deleted=true').json()} == {kept}
    assert path.read_bytes() == b'restore-export'
    assert db.one("SELECT conversation_id FROM reports WHERE id='restore-export'")['conversation_id'] == a
    assert len(db.all("SELECT id FROM audit_events WHERE action='conversation.restored'")) == 2


@pytest.mark.parametrize('unavailable',['foreign','missing','live'])
def test_bulk_restore_invalid_selection_is_atomic(client,admin,unavailable):
    db=client.app.state.db
    selected=populated(client)
    assert trash(client,[selected]).status_code == 200
    if unavailable=='live':
        unavailable=populated(client)
    elif unavailable=='foreign':
        other=create_member(client)
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?,?,?)',('foreign',other['id'],'Other',None,None,now(),now()))
        db.execute('INSERT INTO conversation_trash VALUES(?,?)',('foreign',now()))
    assert restore_selected(client,[selected,unavailable]).status_code == 404
    with pytest.raises(LookupError):
        db.restore_conversations(admin['id'],[selected,unavailable])
    assert db.one('SELECT conversation_id FROM conversation_trash WHERE conversation_id=?',(selected,))
    assert not db.all("SELECT id FROM audit_events WHERE action='conversation.restored'")


@pytest.mark.parametrize('ids',[[],['../bad'],['a'*129],['a']*5001])
def test_bulk_restore_rejects_invalid_ids(client,admin,ids):
    assert restore_selected(client,ids).status_code == 422


def test_overlapping_bulk_restores_are_serialized_without_partial_success(client,admin):
    a,b,c=[populated(client) for _ in range(3)]
    assert trash(client,[a,b,c]).status_code == 200
    restore=endpoint(client,'/api/conversations/bulk-restore','POST')
    request=SimpleNamespace(app=client.app)
    async def run():
        results=await asyncio.wait_for(asyncio.gather(
            restore(ConversationSelection(conversation_ids=[a,b]),request,admin),
            restore(ConversationSelection(conversation_ids=[c,b]),request,admin),
            return_exceptions=True),5)
        successful=[r for r in results if isinstance(r,dict)]
        errors=[r for r in results if not isinstance(r,dict)]
        assert len(successful)==1 and successful[0]['restored_count']==2
        assert len(errors)==1 and errors[0].status_code==404
        assert all(not lock.locked() for lock in client.app.state.conversation_mutations.values())
        assert all(not lock.locked() for lock in client.app.state.locks.values())
    client.portal.call(run)
    assert len(client.get('/api/conversations').json())==2
    assert len(client.get('/api/conversations?deleted=true').json())==1
