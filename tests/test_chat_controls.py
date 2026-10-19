import json
import sqlite3

import pytest

from app.db import Database, now
from app.provider import CodexRuntime
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_claude_subscriptions import claude as claude_fixture, choose, connect_claude
from test_excel_reports import subscribe, wait_report


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


def prepare(client, provider):
    subscribe(client)
    if provider == 'claude':
        connect_claude(client)
        choose(client, provider)
    return client.post('/api/conversations', headers=HEADERS, json={}).json()['id']


def post(client, chat, **body):
    return client.post(f'/api/conversations/{chat}/messages', headers=HEADERS, json=body)


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
@pytest.mark.parametrize('edited', [False, True])
def test_retry_replaces_latest_attempt_and_rebuilds_context(client, admin, claude, monkeypatch, provider, edited):
    chat = prepare(client, provider)
    calls = []
    rpc = CodexRuntime.rpc

    async def record(self, method, params=None):
        if method == 'turn/start':
            calls.append(params)
        return await rpc(self, method, params)

    monkeypatch.setattr(CodexRuntime, 'rpc', record)
    assert post(client, chat, content='Earlier complete question').status_code == 200
    upload = client.post(f'/api/conversations/{chat}/attachments', headers=HEADERS,
                         files={'file': ('original.csv', b'name,value\nA,10', 'text/csv')}).json()
    assert post(client, chat, content='Original request', attachment_ids=[upload['id']]).status_code == 200
    before = client.get(f'/api/conversations/{chat}').json()
    original, partial = before['messages'][-2:]
    db = client.app.state.db
    db.execute("UPDATE messages SET content='Partial response',status='interrupted' WHERE id=?", (partial['id'],))
    # Another provider's old context must also be invalidated after editing.
    other = 'chatgpt' if provider == 'claude' else 'claude'
    db.execute('INSERT INTO conversation_provider_threads VALUES(?,?,?)', (chat, other, 'stale-context'))
    report = client.post('/api/reports', headers=HEADERS, json={
        'title': 'Preserved report', 'conversation_id': chat, 'rows': [{'value': 10}]}).json()
    assert wait_report(client, report['id'])['status'] == 'completed'
    request = 'Edited request' if edited else original['content']
    response = post(client, chat, content=request, retry_message_id=original['id'])
    assert response.status_code == 200, response.text
    after = client.get(f'/api/conversations/{chat}').json()
    assert after['provider_thread_id'] != before['provider_thread_id']
    assert len(after['messages']) == 4
    assert after['messages'][-2]['id'] == original['id']
    assert after['messages'][-2]['content'] == request
    assert after['messages'][-2]['attachments'][0]['id'] == upload['id']
    assert after['messages'][-1]['status'] == 'completed'
    revision = db.one('SELECT * FROM message_revisions WHERE conversation_id=?', (chat,))
    assert revision['previous_content'] == 'Original request'
    assert revision['assistant_content'] == 'Partial response'
    assert json.loads(revision['attachment_ids_json']) == [upload['id']]
    assert db.one('SELECT * FROM conversation_provider_threads WHERE conversation_id=? AND provider=?', (chat, other)) is None
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200
    if provider == 'chatgpt':
        content = json.loads(calls[-1]['input'][0]['text'])
    else:
        content = json.loads(claude[-1].content)
    assert content['new_message'] == request
    assert [m['content'] for m in content['previous_messages'] if m['role'] == 'user'] == ['Earlier complete question']
    # Reopening and continuing the revised chat still resumes its new context.
    native = after['provider_thread_id']
    assert post(client, chat, content='Follow up').status_code == 200
    assert client.get(f'/api/conversations/{chat}').json()['provider_thread_id'] == native


def test_restart_rejects_other_chat_assistant_and_missing_messages(client, admin):
    chat = prepare(client, 'chatgpt')
    post(client, chat, content='Completed question')
    messages = client.get(f'/api/conversations/{chat}').json()['messages']
    other = client.post('/api/conversations', headers=HEADERS, json={}).json()['id']
    assert post(client, other, content='Edit', retry_message_id=messages[0]['id']).status_code == 404
    assert post(client, chat, content='Edit', retry_message_id=messages[1]['id']).status_code == 404
    assert post(client, chat, content='Edit', retry_message_id='missing').status_code == 404
    create_member(client)
    sign_in_member(client)
    assert post(client, chat, content='Edit', retry_message_id=messages[0]['id']).status_code == 404
    assert len(client.app.state.db.all('SELECT * FROM messages WHERE conversation_id=?', (chat,))) == 2


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_effort_reaches_native_chat_report_and_automatic_reset(client, admin, claude, monkeypatch, provider):
    chat = prepare(client, provider)
    turns = []
    rpc = CodexRuntime.rpc

    async def record(self, method, params=None):
        if method == 'turn/start':
            turns.append(params)
        return await rpc(self, method, params)

    monkeypatch.setattr(CodexRuntime, 'rpc', record)
    models = client.get('/api/subscription/models').json()
    assert 'high' in models[0]['supported_reasoning_efforts']
    assert post(client, chat, content='Investigate', reasoning_effort='high').status_code == 200
    assert client.get(f'/api/conversations/{chat}').json()['reasoning_effort'] == 'high'
    if provider == 'chatgpt':
        assert turns[-1]['effort'] == 'high'
    else:
        assert claude[-1].options.effort == 'high'
    # Omitted level inherits the conversation's selection, including tool reports.
    post(client, chat, content='Continue')
    manager = client.app.state.manager
    native = client.get(f'/api/conversations/{chat}').json()['provider_thread_id']
    body = manager.report_request(admin['id'], {'threadId': native}, {
        'title': 'Model report', 'reasoning_effort': 'low', 'rows': [{'value': 10}]})
    assert body.reasoning_effort == 'high'
    report = client.post('/api/reports', headers=HEADERS, json={
        'title': 'Reasoning report', 'conversation_id': chat, 'rows': [{'value': 10}]}).json()
    assert wait_report(client, report['id'])['status'] == 'completed'
    assert (turns[-1]['effort'] if provider == 'chatgpt' else claude[-1].options.effort) == 'high'
    post(client, chat, content='Automatic', reasoning_effort=None)
    assert client.get(f'/api/conversations/{chat}').json()['reasoning_effort'] is None
    assert (turns[-1]['effort'] if provider == 'chatgpt' else claude[-1].options.effort) == ('medium' if provider == 'chatgpt' else None)
    assert post(client, chat, content='Unsupported', reasoning_effort='minimal').status_code == 422
    assert client.get(f'/api/conversations/{chat}').json()['messages'][-2]['content'] == 'Automatic'


def test_roles_keep_source_grants_and_do_not_grant_president_admin(client, admin):
    assert admin['role'] == 'devs'
    member = create_member(client)
    assert member['role'] == 'manager'
    source = client.post('/api/admin/sources', headers=HEADERS, json={'name': 'Granted database', 'kind': 'sqlserver'}).json()
    client.app.state.db.execute("INSERT INTO source_grants VALUES(?,?)", (source["id"], member["id"]))
    assert client.patch(f"/api/admin/users/{member['id']}", headers=HEADERS, json={'role': 'president'}).status_code == 200
    assert client.app.state.db.one('SELECT * FROM source_grants WHERE user_id=? AND source_id=?', (member['id'], source['id']))
    assert client.patch(f"/api/admin/users/{admin['id']}", headers=HEADERS, json={'role': 'manager'}).status_code == 422
    sign_in_member(client)
    assert client.get('/api/auth/status').json()['user']['role'] == 'president'
    assert client.get('/api/admin/users').status_code == 200
    assert client.get('/api/admin/overview').status_code == 403
    assert [s['id'] for s in client.get('/api/sources').json()] == [source['id']]


def test_role_migration_retains_sessions_grants_history_and_foreign_keys(tmp_path):
    path = tmp_path / 'existing.sqlite'
    # First create the exact old users constraint and its dependent schema.
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL COLLATE NOCASE,name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','member')),active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL)")
        c.executemany('INSERT INTO users VALUES(?,?,?,?,?,?,?)', [
            ('a','a@example.com','Admin','hash','admin',1,now()), ('m','m@example.com','Member','hash','member',1,now())])
    from pathlib import Path
    with sqlite3.connect(path) as c:
        c.executescript((Path(__file__).parents[1] / 'backend/app/schema.sql').read_text())
        c.execute("INSERT INTO sessions VALUES('token','m',4070908800)")
        c.execute("INSERT INTO conversations VALUES('chat','m','History','fixture',NULL,?,?)", (now(),now()))
        c.execute("INSERT INTO messages VALUES('message','chat','user','Keep this','completed',?)", (now(),))
        # A minimal source/grant is populated using column names to preserve schema compatibility.
        c.execute("INSERT INTO data_sources(id,name,kind,status,created_at) VALUES('source','DB','sqlserver','not_configured',?)", (now(),))
        c.execute("INSERT INTO source_grants(user_id,source_id) VALUES('m','source')")
    db = Database(path)
    db.initialize()
    db.initialize()  # migration must be idempotent
    assert db.one("SELECT role FROM users WHERE id='a'")['role'] == 'devs'
    assert db.one("SELECT role FROM users WHERE id='m'")['role'] == 'manager'
    assert db.one("SELECT * FROM sessions WHERE user_id='m'")
    assert db.one("SELECT * FROM source_grants WHERE user_id='m'")
    assert db.one("SELECT content FROM messages WHERE id='message'")['content'] == 'Keep this'
    with db.connect() as c:
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
@pytest.mark.parametrize('position', [0, 1, 2])
@pytest.mark.parametrize('edited', [False, True])
def test_restart_from_any_completed_message_excludes_future_context(client, admin, claude, monkeypatch, provider, position, edited):
    chat = prepare(client, provider)
    turns = []
    rpc = CodexRuntime.rpc

    async def record(self, method, params=None):
        if method == 'turn/start':
            turns.append(params)
        return await rpc(self, method, params)

    monkeypatch.setattr(CodexRuntime, 'rpc', record)
    files = []
    for n in range(3):
        upload = client.post(f'/api/conversations/{chat}/attachments', headers=HEADERS,
                             files={'file': (f'turn-{n}.csv', b'name,value\nA,10', 'text/csv')}).json()
        files.append(upload['id'])
        assert post(client, chat, content=f'Question {n}', attachment_ids=[upload['id']]).status_code == 200
    before = client.get(f'/api/conversations/{chat}').json()
    target = before['messages'][position * 2]
    db = client.app.state.db
    # A saved result from the discarded suffix must not be reused by its ID.
    from app.db import uid
    calculation_id = uid()
    db.execute('INSERT INTO calculation_runs VALUES(?,?,?,?,?,?,?,?)', (
        calculation_id, admin['id'], chat, '{}', '{}', '{}', now(), 'complete'))
    replacement = 'Edited request' if edited else target['content']
    response = post(client, chat, content=replacement, retry_message_id=target['id'])
    assert response.status_code == 200, response.text
    after = client.get(f'/api/conversations/{chat}').json()
    assert after['messages'][:position * 2] == before['messages'][:position * 2]
    assert [m['content'] for m in after['messages'] if m['role'] == 'user'] == [f'Question {n}' for n in range(position)] + [replacement]
    assert after['messages'][-2]['id'] == target['id']
    assert after['messages'][-2]['attachments'][0]['id'] == files[position]
    assert len(after['messages']) == (position + 1) * 2
    assert after['provider_thread_id'] != before['provider_thread_id']
    content = json.loads(turns[-1]['input'][0]['text'] if provider == 'chatgpt' else claude[-1].content)
    assert content['new_message'] == replacement
    assert content.get('previous_messages', []) == [
        {'role': m['role'], 'content': m['content']} for m in before['messages'][:position * 2]]
    assert {a['id'] for a in content['attachments']} == set(files[:position + 1])
    manifest = client.app.state.attachments.sent_files(admin['id'], chat)
    assert {a['id'] for a in manifest} == set(files[:position + 1])
    archive = json.loads(db.one('SELECT snapshot_json FROM conversation_branches WHERE conversation_id=?', (chat,))['snapshot_json'])
    assert [m['id'] for m in archive['messages']] == [m['id'] for m in before['messages']]
    assert calculation_id in archive['calculation_ids']
    from app.calculations import CalculationService
    with pytest.raises(ValueError, match='Calculation not found'):
        CalculationService(client.app.state.settings, db, client.app.state.connectors, client.app.state.attachments).owned(admin['id'], chat, calculation_id)
    # Reopening and continuing uses the rebuilt thread, without restoring the discarded suffix.
    post(client, chat, content='Continue revised path')
    reopened = client.get(f'/api/conversations/{chat}').json()
    assert reopened['provider_thread_id'] == after['provider_thread_id']
    assert len(reopened['messages']) == len(after['messages']) + 2
    # A still earlier restart must retain the previous branch archive.
    first = reopened['messages'][0]
    assert post(client, chat, content='Start again', retry_message_id=first['id']).status_code == 200
    assert db.one('SELECT count(*) AS n FROM conversation_branches WHERE conversation_id=?', (chat,))['n'] == 2
    with db.connect() as c:
        assert c.execute('PRAGMA foreign_key_check').fetchall() == []


def test_restart_failure_leaves_history_and_reports_intact(client, admin, monkeypatch):
    from app.provider import ProviderError
    chat = prepare(client, 'chatgpt')
    post(client, chat, content='First complete question')
    post(client, chat, content='Later complete question')
    before = client.get(f'/api/conversations/{chat}').json()
    report = client.post('/api/reports', headers=HEADERS, json={
        'title': 'Keep if restart fails', 'conversation_id': chat, 'rows': [{'value': 10}]}).json()
    assert wait_report(client, report['id'])['status'] == 'completed'

    async def unavailable(self, thread_id, model):
        raise ProviderError('Provider unavailable')

    monkeypatch.setattr(CodexRuntime, 'thread', unavailable)
    assert post(client, chat, content='Edited', retry_message_id=before['messages'][0]['id']).status_code == 409
    after = client.get(f'/api/conversations/{chat}').json()
    assert after['messages'] == before['messages']
    assert after['provider_thread_id'] == before['provider_thread_id']
    assert client.get(f"/api/reports/{report['id']}").json()['conversation_id'] == chat
    assert not client.app.state.db.all('SELECT * FROM conversation_branches WHERE conversation_id=?', (chat,))


def test_restart_keeps_earlier_reports_and_detaches_only_replaced_reports(client, admin):
    chat = prepare(client, 'chatgpt')
    post(client, chat, content='First complete question')
    reports = []
    for title in ['Before restart point', 'After restart point']:
        report = client.post('/api/reports', headers=HEADERS, json={
            'title': title, 'conversation_id': chat, 'rows': [{'value': 10}]}).json()
        assert wait_report(client, report['id'])['status'] == 'completed'
        reports.append(report['id'])
        if len(reports) == 1:
            post(client, chat, content='Restart from this completed message')
    messages = client.get(f'/api/conversations/{chat}').json()['messages']
    assert post(client, chat, content='Revised second question', retry_message_id=messages[2]['id']).status_code == 200
    assert client.get(f'/api/reports/{reports[0]}').json()['conversation_id'] == chat
    assert client.get(f'/api/reports/{reports[1]}').json()['conversation_id'] is None
    for identifier in reports:
        assert client.get(f'/api/reports/{identifier}/export/xlsx').status_code == 200


def test_restart_replays_all_prior_turns_even_beyond_forty_messages(client, admin, monkeypatch):
    from app.db import uid
    chat = prepare(client, 'chatgpt')
    db = client.app.state.db
    timestamp = now()
    # Identical timestamps intentionally exercise the stable rowid tie-breaker.
    for n in range(45):
        db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)', (uid(),chat,'user' if n % 2 == 0 else 'assistant',f'History {n}','completed',timestamp))
    messages = client.get(f'/api/conversations/{chat}').json()['messages']
    captured = []
    rpc = CodexRuntime.rpc

    async def record(self, method, params=None):
        if method == 'turn/start':
            captured.append(params)
        return await rpc(self, method, params)

    monkeypatch.setattr(CodexRuntime, 'rpc', record)
    assert post(client, chat, content='Revised final question', retry_message_id=messages[-1]['id']).status_code == 200
    assert len(json.loads(captured[-1]['input'][0]['text'])['previous_messages']) == 44
    assert client.get(f'/api/conversations/{chat}').json()['messages'][:44] == messages[:44]
