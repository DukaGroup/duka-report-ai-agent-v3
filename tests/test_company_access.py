"""Private company resolution distinguishes permission denial from ambiguity."""

import json
from functools import partial

import pytest

from app.connectors import SourceNotConfigured
from app.data_access import DataAccess
from app.provider import BASE_INSTRUCTIONS, REPORT_TOOLS
from conftest import HEADERS
from test_database_chat import call_tool
from test_member_data_access import CompanyDatabase, catalog, create_scoped, database as database_fixture
from test_workspace_permissions import add, claude as claude_fixture
from test_claude_subscriptions import connect_claude
from test_excel_reports import subscribe


@pytest.fixture
def database(client, admin):
    return database_fixture.__wrapped__(client, admin)


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.fixture
def companies(client, admin, database):
    source, connector = database
    # GoTech and D&D live on separate sources, as in the reported failure.
    connector.connection.execute("UPDATE dbo.Company SET Name='GoTech' WHERE Name='Alpha'")
    gotech = next(u for u in catalog(client, database) if u.get('prefix') == 'GoTech$')
    member = create_scoped(client, source, [gotech])
    hana = client.post('/api/admin/sources', headers=HEADERS,
                       json={'name': 'Restricted SAP', 'kind': 'saphana'}).json()
    sap = CompanyDatabase(client.app.state.settings, client.app.state.connectors.catalog, dialect='hana')
    sap.connection.execute("UPDATE SAP.T001 SET BUTXT='D & D Distribution (ECO)' WHERE BUKRS='A'")
    client.app.state.connectors.register(hana['id'], sap)
    return member, source, connector, hana, sap


def resolve(client, member, name):
    return call_tool(client, member, 'resolve_company_access', {'company': name})


def test_cross_source_denial_contains_no_restricted_metadata_or_business_rows(client, companies):
    member, source, go, hana, sap = companies
    tables = ['source_grants', 'source_access_policies', 'database_grants', 'data_access_versions']
    db = client.app.state.db
    before = {t: db.all('SELECT * FROM ' + t) for t in tables}
    assert resolve(client, member, 'd&d') == {
        'status': 'denied', 'message': 'Qasja nuk lejohet.', 'matches': [],
    }
    assert {t: db.all('SELECT * FROM ' + t) for t in tables} == before
    assert resolve(client, member, 'GOTECH')['status'] == 'allowed'
    assert resolve(client, member, 'D & D')['status'] == 'denied'
    for connector in (go, sap):
        assert all('BSEG' not in sql and '$Sales' not in sql for sql, _ in connector.calls)
    # Resolving never grants access to the restricted source, even for metadata.
    with pytest.raises(SourceNotConfigured):
        client.portal.call(partial(client.app.state.connectors.database_call,
                                   member['id'], hana['id'], 'schemas', database='Finance'))


def test_resumed_codex_catalog_compatibility_checks_access_without_sales_or_reports(client, companies):
    from jsonschema import Draft202012Validator
    member = companies[0]
    arguments = {'source_id': '', 'company': 'D&D'}
    definition = next(t for t in REPORT_TOOLS[0]['tools'] if t['name'] == 'discover_sales')
    Draft202012Validator(definition['inputSchema']).validate(arguments)
    assert call_tool(client, member, 'discover_sales', arguments) == resolve(client, member, 'D&D')
    assert client.app.state.db.all('SELECT id FROM reports') == []


def test_same_database_company_restriction_and_alias_collisions(client, admin, database):
    source, connector = database
    units = catalog(client, database)
    member = create_scoped(client, source, [next(u for u in units if u.get('prefix') == 'Alpha$')])
    assert resolve(client, member, 'Beta')['status'] == 'denied'
    # Alpha exists in both an allowed BC company and restricted SAP identities.
    result = resolve(client, member, 'Alpha')
    assert result['status'] == 'ambiguous'
    assert {m['company']['kind'] for m in result['matches']} == {'table_prefix'}
    assert 'SAP' not in json.dumps(result) and 'Archive' not in json.dumps(result)
    connector.connection.execute("UPDATE dbo.Company SET Name='Alpha Trading' WHERE Name='Alpha'")
    assert resolve(client, member, 'Beta copies')['status'] == 'denied'
    assert resolve(client, member, 'Unrecognized Company')['status'] == 'not_found'


def test_exact_accessible_name_does_not_hide_a_restricted_short_name_collision(client, companies):
    member, _, _, _, sap = companies
    sap.connection.execute("UPDATE SAP.T001 SET BUTXT='GoTech Distribution' WHERE BUKRS='A'")
    result = resolve(client, member, 'GoTech')
    assert result['status'] == 'ambiguous'
    assert {m['company']['name'] for m in result['matches']} == {'GoTech'}
    assert 'Distribution' not in json.dumps(result)
    assert resolve(client, member, 'GoTech Distribution')['status'] == 'denied'


@pytest.mark.parametrize('role', ['devs', 'president'])
def test_full_roles_can_resolve_every_company_without_explicit_grants(client, admin, companies, role):
    member = add(client, role=role, name='Full')
    result = resolve(client, member, 'D&D')
    assert result['status'] == 'allowed'
    assert {m['company']['client'] for m in result['matches']} == {'400', '500'}


def test_live_revocation_and_company_name_changes_are_not_cached(client, companies):
    member, source, go, _, _ = companies
    assert resolve(client, member, 'GoTech')['status'] == 'allowed'
    with client.app.state.db.connect() as c:
        DataAccess(client.app.state.db).replace(c, member['id'], [])
    assert resolve(client, member, 'GoTech')['status'] == 'denied'
    go.connection.execute("UPDATE dbo.Company SET Name='New GoTech' WHERE Name='GoTech'")
    assert resolve(client, member, 'GoTech')['status'] == 'not_found'
    assert resolve(client, member, 'New GoTech')['status'] == 'denied'


def test_catalog_failures_do_not_become_permission_denials_or_leak_errors(client, companies, monkeypatch):
    member, _, _, _, sap = companies

    async def broken(**kwargs):
        raise SourceNotConfigured('PRIVATE_HOST PRIVATE_LOGIN PRIVATE_SCHEMA')

    monkeypatch.setattr(sap, 'databases', broken)
    result = resolve(client, member, 'D&D')
    assert result == {'status': 'unavailable', 'matches': [], 'catalog_complete': False}
    assert resolve(client, member, 'GoTech')['status'] == 'allowed'


def test_branch_qualifier_resolves_authorized_company_despite_an_unrelated_outage(client, companies, monkeypatch):
    member, _, go, _, sap = companies
    go.connection.execute("UPDATE dbo.Company SET Name='Gotech Live' WHERE Name='GoTech'")
    # Preserve a realistic database-wide grant; matching a display name never
    # rewrites a company-specific grant or grants another company's tables.
    with client.app.state.db.connect() as c:
        c.execute('UPDATE database_grants SET all_companies=1 WHERE user_id=?', (member['id'],))
        DataAccess.bump(c, member['id'])

    async def broken(**kwargs):
        raise SourceNotConfigured('PRIVATE_HOST')

    monkeypatch.setattr(sap, 'databases', broken)
    result = resolve(client, member, 'Gotech Fier')
    assert result['status'] == 'scope_required'
    assert result['qualifier'] == {'company_name': 'gotech', 'remaining_text': 'fier'}
    assert result['catalog_complete'] is False
    assert {m['company']['name'] for m in result['matches']} == {'Gotech Live'}
    assert resolve(client, member, 'Gotech Live Fier')['qualifier']['remaining_text'] == 'fier'
    assert resolve(client, member, 'GoTech')['status'] == 'allowed'
    # "New GoTech" is a different name, not a location after the known alias.
    assert resolve(client, member, 'New GoTech')['status'] == 'unavailable'


def test_explicit_restricted_company_wins_over_an_accessible_company_with_qualifier(client, companies):
    member, _, _, _, sap = companies
    assert resolve(client, member, 'D&D Fier')['status'] == 'denied'
    sap.connection.execute("UPDATE SAP.T001 SET BUTXT='GoTech Fier' WHERE BUKRS='A'")
    assert resolve(client, member, 'GoTech Fier') == {
        'status': 'denied', 'message': 'Qasja nuk lejohet.', 'matches': [],
    }
    # A fabricated branch name is only an unresolved qualifier, never allowed.
    assert resolve(client, member, 'GoTech Nonexistent')['status'] == 'ambiguous'


def test_qualifier_is_not_a_grant_and_keeps_company_restrictions(client, companies):
    member, source, _, _, _ = companies
    db = client.app.state.db
    before = DataAccess(db).saved(member['id'])
    result = resolve(client, member, 'GoTech Fier')
    assert result['status'] == 'scope_required'
    assert {m['company']['name'] for m in result['matches']} == {'GoTech'}
    assert result['qualifier']['remaining_text'] == 'fier'
    assert DataAccess(db).saved(member['id']) == before
    with pytest.raises(SourceNotConfigured):
        client.portal.call(partial(client.app.state.connectors.database_call,
                                   member['id'], source['id'], 'query', database='Finance',
                                   query={'tables': [{'schema': 'dbo', 'name': 'Beta$Sales', 'alias': 's'}],
                                          'select': [{'column': 's.Amount'}]}))


def test_grant_changes_during_discovery_require_a_fresh_check(client, companies, monkeypatch):
    member, _, go, _, _ = companies
    original = go.databases

    async def revoke(**kwargs):
        with client.app.state.db.connect() as c:
            DataAccess(client.app.state.db).replace(c, member['id'], [])
        return await original(**kwargs)

    monkeypatch.setattr(go, 'databases', revoke)
    result = resolve(client, member, 'GoTech')
    assert result['status'] == 'unavailable'
    assert result['matches'] == []


@pytest.mark.parametrize('value', ['', '*', 'a', 'x' * 161, None])
def test_resolver_rejects_empty_or_invalid_catalog_probes(client, companies, value):
    result = resolve(client, companies[0], value)
    assert result['status'] == 'unavailable' and 'error' in result and result['matches'] == []


@pytest.mark.parametrize('provider', ['chatgpt', 'claude'])
def test_shared_provider_uses_acting_managers_access_not_subscription_owners(client, admin, companies, claude, provider):
    member = companies[0]
    subscribe(client) if provider == 'chatgpt' else connect_claude(client)
    manager = client.app.state.manager
    model = 'fixture' if provider == 'chatgpt' else 'claude:default'
    runtime = client.portal.call(partial(manager.acquire_worker, member['id'], 'chat', 'access-check', model))
    thread = client.portal.call(runtime.thread, None, model)
    params = {'namespace': 'duka_reporting', 'tool': 'resolve_company_access',
              'arguments': {'company': 'D&D'}, 'threadId': thread}
    response = client.portal.call(runtime.native.tool_handler, member['id'], params)
    assert json.loads(response['contentItems'][0]['text']) == {
        'status': 'denied', 'message': 'Qasja nuk lejohet.', 'matches': [],
    }
    scoped = client.portal.call(runtime.native.tool_handler, member['id'],
                               {**params, 'arguments': {'company': 'GoTech Fier'}})
    result = json.loads(scoped['contentItems'][0]['text'])
    assert result['status'] == 'scope_required'
    assert result['qualifier']['remaining_text'] == 'fier'
    assert {m['company']['name'] for m in result['matches']} == {'GoTech'}
    assert 'FIRST call resolve_company_access' in BASE_INSTRUCTIONS
    assert 'If status is denied, reply only "Qasja nuk lejohet." and stop' in BASE_INSTRUCTIONS
    assert any(t['name'] == 'resolve_company_access' for t in REPORT_TOOLS[0]['tools'])
    client.portal.call(manager.release_worker, member['id'], 'chat', 'access-check')
