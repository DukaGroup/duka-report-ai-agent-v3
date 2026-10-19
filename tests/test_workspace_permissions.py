"""Role boundaries and shared subscriptions must not share business authorization."""

import pytest

from app.connectors import SourceNotConfigured
from conftest import HEADERS
from test_claude_subscriptions import claude as claude_fixture, connect_claude, choose, send
from test_excel_reports import subscribe, wait_report
from test_member_data_access import database as database_fixture, catalog, selection, read, query


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.fixture
def database(client, admin):
    return database_fixture.__wrapped__(client, admin)


def add(client, role="manager", name="Member", **extra):
    response = client.post('/api/admin/users', headers=HEADERS, json={
        'name': name, 'email': name.lower() + '@example.com',
        'password': 'member-long-password', 'role': role, **extra,
    })
    assert response.status_code == 201, response.text
    return response.json()


def login(client, user):
    client.cookies.clear()
    response = client.post('/api/auth/login', headers=HEADERS, json={
        'email': user['email'], 'password': 'member-long-password',
    })
    assert response.status_code == 200, response.text


@pytest.mark.parametrize('role', ['manager', 'president'])
def test_non_devs_cannot_configure_workspace_or_shared_subscriptions(client, admin, role):
    member = add(client, role)
    login(client, member)
    for path in ['/admin/overview', '/admin/sources', '/admin/datasets', '/admin/database',
                 '/admin/audit', '/admin/traffic', '/subscription/usage']:
        assert client.get('/api' + path).status_code == 403, path
    for provider in ['chatgpt', 'claude']:
        for action in ['login', 'disconnect']:
            assert client.post(f'/api/subscription/{action}?provider={provider}', headers=HEADERS).status_code == 403
        assert client.post('/api/subscription/select', headers=HEADERS, json={'provider': provider}).status_code == 403
    assert client.post('/api/subscription/login/code', headers=HEADERS,
                       json={'login_id': 'other', 'code': 'private-code'}).status_code == 403
    assert client.post('/api/admin/sources', headers=HEADERS,
                       json={'name': 'Forbidden', 'kind': 'sqlserver'}).status_code == 403
    assert client.patch(f"/api/admin/users/{admin['id']}", headers=HEADERS,
                        json={'role': 'manager'}).status_code == 403
    assert client.post(f"/api/admin/users/{admin['id']}/password-reset", headers=HEADERS).status_code == 403
    assert client.post(f"/api/admin/runtimes/{admin['id']}/restart", headers=HEADERS).status_code == 403
    assert client.put(f"/api/admin/users/{member['id']}/access", headers=HEADERS,
                      json={'databases': []}).status_code == 403
    assert client.get('/api/conversations').status_code == 200
    assert client.get('/api/reports').status_code == 200
    if role == 'manager':
        assert client.get('/api/admin/users').status_code == 403
        assert client.get('/api/admin/access-catalog').status_code == 403
        assert client.post('/api/admin/users', headers=HEADERS, json={
            'name': 'Forbidden', 'email': 'forbidden@example.com', 'password': 'member-long-password',
        }).status_code == 403
        assert client.delete(f"/api/admin/users/{admin['id']}", headers=HEADERS).status_code == 403


def test_president_can_add_scoped_members_and_remove_without_widening_existing_grants(client, admin, database):
    source, _ = database
    alpha = next(unit for unit in catalog(client, database) if unit.get('prefix') == 'Alpha$')
    president = add(client, 'president', 'President')
    existing = add(client, name='Existing', database_access={'databases': [selection(source, [alpha])]})
    db = client.app.state.db
    tables = ['source_grants', 'source_access_policies', 'database_grants', 'dataset_grants']
    before = {table: db.all('SELECT * FROM ' + table + ' WHERE user_id=?', (existing['id'],)) for table in tables}
    login(client, existing)
    existing_cookie = client.cookies.get('duka_session')
    login(client, president)
    assert client.get('/api/admin/access-catalog').status_code == 200
    created = add(client, name='New', database_access={'databases': [selection(source, [alpha])]})
    assert read(client, created, source)['rows'] == [{'total': 30}]
    assert client.post('/api/admin/users', headers=HEADERS, json={
        'name': 'Escalation', 'email': 'escalation@example.com', 'password': 'member-long-password', 'role': 'devs',
    }).status_code == 403
    assert client.delete(f"/api/admin/users/{admin['id']}", headers=HEADERS).status_code == 403
    assert client.delete(f"/api/admin/users/{president['id']}", headers=HEADERS).status_code == 422
    assert client.delete(f"/api/admin/users/{existing['id']}", headers=HEADERS).status_code == 200
    assert existing['id'] not in [u['id'] for u in client.get('/api/admin/users').json()]
    assert before == {table: db.all('SELECT * FROM ' + table + ' WHERE user_id=?', (existing['id'],)) for table in tables}
    client.cookies.set('duka_session', existing_cookie)
    assert client.get('/api/conversations').status_code == 401
    assert client.post('/api/auth/login', headers=HEADERS, json={
        'email': existing['email'], 'password': 'member-long-password',
    }).status_code == 401


def test_devs_can_remove_members_but_not_self_and_removed_accounts_cannot_be_reactivated(client, admin):
    target = add(client, 'devs', 'Developer')
    assert client.delete(f"/api/admin/users/{admin['id']}", headers=HEADERS).status_code == 422
    assert client.delete(f"/api/admin/users/{target['id']}", headers=HEADERS).status_code == 200
    assert client.patch(f"/api/admin/users/{target['id']}", headers=HEADERS, json={'active': True}).status_code == 409
    assert client.app.state.db.one("SELECT count(*) AS n FROM users WHERE role='devs' AND active=1")['n'] == 1
    with client.app.state.db.connect() as connection:
        assert connection.execute('PRAGMA foreign_key_check').fetchall() == []


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_devs_cannot_change_a_shared_account_while_another_members_worker_is_leased(client, admin, claude, provider):
    from functools import partial
    member = add(client)
    subscribe(client) if provider == 'chatgpt' else connect_claude(client)
    manager = client.app.state.manager
    model = 'claude:default' if provider == 'claude' else 'fixture'
    client.portal.call(partial(manager.acquire_worker, member['id'], 'chat', 'active-member-chat', model))
    for action in ['disconnect', 'login']:
        response = client.post(f'/api/subscription/{action}?provider={provider}', headers=HEADERS)
        assert response.status_code == 409, response.text
    assert client.get(f'/api/subscription?provider={provider}').json()['connected']
    client.portal.call(manager.release_worker, member['id'], 'chat', 'active-member-chat')
    assert client.post(f'/api/subscription/disconnect?provider={provider}', headers=HEADERS).status_code == 200


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_shared_connection_separate_member_chats_reports_and_tool_permissions(client, admin, database, claude, provider):
    source, _ = database
    alpha = next(unit for unit in catalog(client, database) if unit.get('prefix') == 'Alpha$')
    alice = add(client, name='Alice', database_access={'databases': [selection(source, [alpha])]})
    bob = add(client, name='Bob')
    subscribe(client) if provider == 'chatgpt' else connect_claude(client)
    choose(client, provider)
    admin_cookie = client.cookies.get('duka_session')
    threads = []
    for member in [alice, bob]:
        login(client, member)
        status = client.get('/api/subscription').json()
        assert status['connected'] and status['shared'] and status['provider_id'] == provider
        assert status['account'] is None and status['login'] is None
        chat = client.post('/api/conversations', headers=HEADERS, json={}).json()
        send(client, chat['id'], 'Private request for ' + member['name'])
        detail = client.get('/api/conversations/' + chat['id']).json()
        threads.append((member, chat['id'], detail['provider_thread_id']))
        runtime = client.app.state.manager.workers[(member['id'], 'chat', chat['id'])]
        assert runtime.user_id == member['id']
        assert runtime.home == client.app.state.manager.for_user(admin['id'], provider).home
        assert member['id'] in str(runtime.workspace)
        report = client.post('/api/reports', headers=HEADERS, json={
            'title': 'Private ' + member['name'], 'rows': [{'amount': 12}],
        }).json()
        assert wait_report(client, report['id'])['status'] == 'completed'
        assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200
    assert threads[0][2] != threads[1][2]
    assert client.get('/api/conversations/' + threads[0][1]).status_code == 404
    assert [item['title'] for item in client.get('/api/reports').json()] == ['Private Bob']
    assert read(client, alice, source)['rows'] == [{'total': 30}]
    with pytest.raises(SourceNotConfigured, match='grant|access|available'):
        read(client, bob, source, query())
    login(client, alice)
    send(client, threads[0][1], 'Continue Alice')
    assert client.get('/api/conversations/' + threads[0][1]).json()['provider_thread_id'] == threads[0][2]
    client.cookies.set('duka_session', admin_cookie)
    assert client.post(f'/api/subscription/disconnect?provider={provider}', headers=HEADERS).status_code == 200
    login(client, bob)
    assert not client.get('/api/subscription').json()['connected']
    assert client.app.state.db.all('SELECT * FROM conversation_provider_threads WHERE provider=?', (provider,)) == []
    assert client.get('/api/conversations/' + threads[1][1]).json()['messages']
