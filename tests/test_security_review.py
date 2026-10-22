"""Regressions for the 2026-10-22 security review; no live credentials needed."""

import csv
import io
import json
import stat
import hashlib

import pytest

from app.config import Settings
from app.data_access import DataAccess, company_unit
from app.db import now, uid
from app.connectors import SourceNotConfigured
from app.report_access import authorize_saved_report, saved_report_scope
from app.reports import csv_snapshot
from app.security import PASSWORD_SCHEME, hash_password, verify_password
from conftest import HEADERS


def test_stronger_password_hash_accepts_legacy_and_rejects_wrong_password():
    password = 'long-test-password'
    salt = '01' * 16
    legacy = 'scrypt$' + salt + '$' + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                                   n=16384, r=8, p=1).hex()
    current = hash_password(password)
    assert current.startswith(PASSWORD_SCHEME + '$')
    for encoded in [legacy, current]:
        assert verify_password(password, encoded)
        assert not verify_password('wrong', encoded)
    assert not verify_password(password, 'unsupported$' + salt + '$00')


def test_successful_login_upgrades_legacy_hash_without_changing_identity(client, admin):
    db = client.app.state.db
    salt = '02' * 16
    password = 'a-long-test-password'
    legacy = 'scrypt$' + salt + '$' + hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                                                   n=16384, r=8, p=1).hex()
    db.execute('UPDATE users SET password_hash=? WHERE id=?', (legacy, admin['id']))
    old_token = client.cookies.get('duka_session')
    assert client.post('/api/auth/login', headers=HEADERS,
                       json={'email': admin['email'], 'password': 'wrong'}).status_code == 401
    assert db.one('SELECT password_hash FROM users WHERE id=?', (admin['id'],))['password_hash'] == legacy
    response = client.post('/api/auth/login', headers=HEADERS,
                           json={'email': admin['email'], 'password': password})
    assert response.status_code == 200 and response.json() == admin
    upgraded = db.one('SELECT password_hash FROM users WHERE id=?', (admin['id'],))['password_hash']
    assert upgraded.startswith(PASSWORD_SCHEME + '$') and verify_password(password, upgraded)
    client.cookies.set('duka_session', old_token)
    assert client.get('/api/auth/status').json()['user']['id'] == admin['id']


@pytest.mark.parametrize('text', ['=1+1', '+1+1', '-1+1', '@SUM(1)', '  =1+1', '\tname', '\rname', '\nname'])
def test_csv_escapes_untrusted_headings_and_values(text):
    result = csv_snapshot({'rows_json': json.dumps([{text: text, 'amount': -12, 'name': 'Safe'}])})
    rows = list(csv.reader(io.StringIO(result)))
    assert rows[0] == ["'" + text, 'amount', 'name']
    assert rows[1] == ["'" + text, '-12', 'Safe']


def test_existing_data_directories_become_private(tmp_path):
    root = tmp_path / 'data'
    root.mkdir(mode=0o755)
    (root / 'codex').mkdir(mode=0o755)
    sentinel = root / 'codex' / 'unchanged'
    sentinel.write_text('existing data')
    settings = Settings(data_dir=root, env_file=None)
    settings.prepare()
    for path in [root, *[root / name for name in ['codex', 'workspaces', 'cache', 'speech-cache']]]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o700
    assert sentinel.read_text() == 'existing data'


@pytest.mark.parametrize('location', ['primary', 'additional', 'calculation'])
def test_saved_reports_check_every_permission_receipt(client, admin, location):
    db = client.app.state.db
    source = client.post('/api/admin/sources', headers=HEADERS,
                         json={'name': 'Restricted fixture', 'kind': 'sqlserver'}).json()
    unit = company_unit('Allowed company', kind='table_prefix', schema='dbo', prefix='Allowed$')
    member = client.post('/api/admin/users', headers=HEADERS, json={
        'name': 'Manager', 'email': 'manager@example.com', 'password': 'long-test-password',
    }).json()
    access = DataAccess(db)
    with db.connect() as c:
        access.replace(c, member['id'], [{'source_id': source['id'], 'database': 'Business',
                                        'all_companies': False, 'companies': [unit]}])
    receipt = {'source_id': source['id'], 'database': 'Business',
               'access_stamp': access.stamp(member['id'], source['id'], 'Business')}
    provenance = receipt if location == 'primary' else {'analyses': [receipt]} if location == 'additional' else {
        '_internal': {'calculation_audit': {'provenance': {
            'plan': {'inputs': [{'kind': 'database', 'name': 'input', 'source_id': source['id']}]},
            'inputs': [{'name': 'input', **receipt}],
        }}}
    }
    identifier = uid()
    db.execute('INSERT INTO dataset_snapshots VALUES(?,?,?,?,?,?)',
               (identifier, member['id'], None, json.dumps(provenance), '[]', now()))
    scope = saved_report_scope(db, identifier, member['id'])
    authorize_saved_report(db, member['id'], scope)
    with db.connect() as c:
        access.replace(c, member['id'], [])
    with pytest.raises(SourceNotConfigured):
        authorize_saved_report(db, member['id'], scope)
    with pytest.raises(SourceNotConfigured):
        saved_report_scope(db, identifier, admin['id'])


def test_legacy_script_report_checks_current_dataset_grant(client, admin):
    db = client.app.state.db
    member = client.post('/api/admin/users', headers=HEADERS, json={
        'name': 'Manager', 'email': 'legacy@example.com', 'password': 'long-test-password',
    }).json()
    source = client.post('/api/admin/sources', headers=HEADERS,
                         json={'name': 'Legacy source', 'kind': 'sqlserver'}).json()
    dataset = client.post('/api/admin/datasets', headers=HEADERS, json={
        'source_id': source['id'], 'name': 'Sales', 'query_key': 'sales_summary',
    }).json()
    db.execute('UPDATE datasets SET enabled=1 WHERE id=?', (dataset['id'],))
    db.execute('INSERT INTO source_grants VALUES(?,?)', (source['id'], member['id']))
    db.execute('INSERT INTO dataset_grants VALUES(?,?)', (dataset['id'], member['id']))
    scope = ([], dataset['id'])
    authorize_saved_report(db, member['id'], scope)
    db.execute('DELETE FROM dataset_grants WHERE user_id=?', (member['id'],))
    with pytest.raises(SourceNotConfigured):
        authorize_saved_report(db, member['id'], scope)
