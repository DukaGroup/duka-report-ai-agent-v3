"""Native deployment, first-account ownership and encrypted recovery regressions."""
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess

from fastapi.testclient import TestClient
import pytest

from app.config import Settings
from app.db import Database, now
from app.deployment_security import bootstrap_path, bootstrap_token, prepare_bootstrap, production
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]


def load_deploy(name):
    spec = importlib.util.spec_from_file_location('deploy_' + name.replace('-', '_'), ROOT / 'deploy' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('origin,secure', [
    ('http://reports.example.com', True), ('https://reports.example.com', False),
    ('https://*.example.com', True), ('https://user:password@example.com', True),
    ('https://reports.example.com/path', True), ('https://reports.example.com?x=y', True),
    ('https://reports.example.com:99999', True), ('', True),
])
def test_public_settings_fail_closed(tmp_path, origin, secure):
    settings = Settings(data_dir=tmp_path / 'data', allowed_origins=(origin,), secure_cookies=secure)
    with pytest.raises(ValueError):
        settings.prepare()
    assert not settings.data_dir.exists()


def production_settings(tmp_path):
    fixture = ROOT / 'tests/fake_codex.py'
    fixture.chmod(0o755)
    return Settings(data_dir=tmp_path / 'data', frontend_dir=tmp_path / 'frontend', env_file=None,
                    codex_binary=str(fixture), voice_enabled=False, production=True, secure_cookies=True,
                    allowed_origins=('https://reports.example.test',))


def test_protected_setup_and_existing_workspace_restart(tmp_path):
    settings = production_settings(tmp_path)
    headers = {'X-Duka-Request': '1', 'Origin': settings.allowed_origins[0]}
    body = {'email': 'owner@example.test', 'name': 'Owner', 'password': 'long-test-password'}
    app = create_app(settings)
    with TestClient(app, base_url=settings.allowed_origins[0]) as client:
        token = bootstrap_token(settings)
        status = client.get('/api/auth/status')
        assert status.json()['setup_token_required'] is True
        assert token not in status.text
        for extra in [{}, {'setup_token': 'incorrect'}]:
            assert client.post('/api/auth/setup', headers=headers, json={**body, **extra}).status_code == 403
            assert app.state.db.one('SELECT count(*) AS n FROM users')['n'] == 0
        result = client.post('/api/auth/setup', headers=headers, json={**body, 'setup_token': token})
        assert result.status_code == 200
        assert 'Secure' in result.headers['set-cookie'] and 'HttpOnly' in result.headers['set-cookie']
        assert not bootstrap_path(settings).exists()
        assert client.get('/api/auth/status').json()['setup_token_required'] is False
        assert client.post('/api/auth/setup', headers=headers, json={**body, 'setup_token': token}).status_code == 409
        original = app.state.db.all('SELECT * FROM users')
        assert client.get('http://reports.example.test/api/auth/status').status_code == 426
        assert client.get('https://attacker.example.test/api/auth/status').status_code == 400
        assert client.get('http://127.0.0.1/api/health').status_code == 200
        assert client.get('/api/health').headers['Strict-Transport-Security'] == 'max-age=31536000'
    logs = json.dumps(app.state.db.all('SELECT * FROM traffic_events'))
    assert token not in logs and body['password'] not in logs
    with TestClient(create_app(settings), base_url=settings.allowed_origins[0]) as restarted:
        assert restarted.get('/api/auth/status').json()['needs_setup'] is False
        assert not bootstrap_path(settings).exists()
        assert restarted.app.state.db.all('SELECT * FROM users') == original


def test_public_origin_requires_security_even_without_explicit_production_mode(tmp_path):
    settings = replace(production_settings(tmp_path), production=False)
    settings.prepare()
    assert production(settings)
    with pytest.raises(ValueError):
        replace(settings, secure_cookies=False).prepare()


def test_setup_refuses_symlink_token(tmp_path):
    settings = production_settings(tmp_path)
    settings.prepare()
    db = Database(settings.data_dir / 'application.sqlite3')
    db.initialize()
    outside = tmp_path / 'unrelated'
    outside.write_text('unchanged')
    bootstrap_path(settings).symlink_to(outside)
    with pytest.raises(OSError):
        prepare_bootstrap(settings, db)
    assert outside.read_text() == 'unchanged'


def test_environment_migration_preserves_credentials_and_does_not_overwrite(tmp_path):
    module = load_deploy('prepare_env')
    app, data = tmp_path / 'app', tmp_path / 'data'
    app.mkdir(); data.mkdir()
    original = b"SQLSERVER_PASSWORD='fixture-${literal}#value'\nDUKA_CONNECTION_TEST_PRESENT='true'\n"
    (app / '.env').write_bytes(original)
    module.prepare(app, data)
    target = data / 'runtime.env'
    assert target.read_bytes() == original == (app / '.env').read_bytes()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    (app / '.env').write_text('changed source')
    module.prepare(app, data)
    assert target.read_bytes() == original


def test_native_preflight_matches_service_environment_and_rejects_insecure_file(tmp_path):
    data = tmp_path / 'data'; data.mkdir(mode=0o700)
    env = data / 'runtime.env'
    env.write_text('APP_ENV=development\nDATA_DIR=/nonexistent-ignored-service-override\n'
                   'ALLOWED_ORIGINS=https://reports.example.test\nSECURE_COOKIES=true\n')
    env.chmod(0o600)
    process_env = {k: v for k, v in os.environ.items() if k not in ('APP_ENV','ALLOWED_ORIGINS','SECURE_COOKIES')}
    process_env.update(ENV_FILE=str(env), DATA_DIR=str(data))
    command = [str(ROOT / 'work/venv/bin/python'), str(ROOT / 'deploy/preflight.py')]
    assert subprocess.run(command, env=process_env, capture_output=True).returncode == 0
    assert subprocess.run(command + ['--domain','reports.example.test'], env=process_env, capture_output=True).returncode == 0
    assert subprocess.run(command + ['--domain','wrong.example.test'], env=process_env, capture_output=True).returncode == 1
    env.write_text('ALLOWED_ORIGINS=http://reports.example.test\nSECURE_COOKIES=false\n')
    assert subprocess.run(command, env=process_env, capture_output=True).returncode == 1
    env.write_text('ALLOWED_ORIGINS=https://reports.example.test\nSECURE_COOKIES=true\n')
    env.chmod(0o644)
    assert subprocess.run(command, env=process_env, capture_output=True).returncode == 1


def backup_fixture(tmp_path):
    module = load_deploy('backup')
    data = tmp_path / 'data'; data.mkdir(mode=0o700)
    db = Database(data / 'application.sqlite3'); db.initialize()
    db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)', ('owner','owner@example.test','Owner','fixture-hash','devs',1,now()))
    db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)', ('member','manager@example.test','Manager','fixture-hash','manager',1,now()))
    db.execute("INSERT INTO data_sources(id,name,kind,description,enabled,status,created_at) VALUES('source','Business','sqlserver','',1,'connected',?)", (now(),))
    db.execute('INSERT INTO source_grants VALUES(?,?)', ('source','member'))
    (data / 'uploads').mkdir(); (data / 'uploads/original.txt').write_bytes(b'original business file')
    (data / 'empty').mkdir()
    helper = data / 'helper'; helper.write_text('#!/bin/sh\nexit 0\n'); helper.chmod(0o700)
    (data / 'codex/private').mkdir(parents=True); (data / 'codex/private/auth.json').write_text('fixture credential')
    env = data / 'runtime.env'; env.write_bytes(b"SQLSERVER_PASSWORD='fixture-secret-value'\n"); env.chmod(0o600)
    return module, data, db, env, tmp_path / 'workspace.duka-backup', tmp_path / 'private.backup-key'


def test_encrypted_backup_restores_members_grants_credentials_and_files(tmp_path):
    module, data, db, env, archive, key = backup_fixture(tmp_path)
    original_users = db.all('SELECT * FROM users'); original_grants = db.all('SELECT * FROM source_grants')
    module.create_backup(data, env, archive, key)
    assert stat.S_IMODE(archive.stat().st_mode) == stat.S_IMODE(key.stat().st_mode) == 0o600
    assert b'fixture-secret-value' not in archive.read_bytes()
    assert b'fixture credential' not in archive.read_bytes()
    target = tmp_path / 'recovered'
    module.verify_or_restore(archive, key, target)
    restored = Database(target / 'data/application.sqlite3')
    assert restored.all('SELECT * FROM users') == original_users
    assert restored.all('SELECT * FROM source_grants') == original_grants
    assert (target / 'config/runtime.env').read_bytes() == env.read_bytes()
    assert (target / 'data/codex/private/auth.json').read_bytes() == (data / 'codex/private/auth.json').read_bytes()
    assert (target / 'data/uploads/original.txt').read_bytes() == (data / 'uploads/original.txt').read_bytes()
    assert stat.S_IMODE((target / 'data').stat().st_mode) == 0o700
    assert (target / 'data/empty').is_dir()
    assert stat.S_IMODE((target / 'data/helper').stat().st_mode) == 0o700
    with pytest.raises(ValueError):
        module.verify_or_restore(archive, key, data)
    assert db.all('SELECT * FROM users') == original_users and db.all('SELECT * FROM source_grants') == original_grants


@pytest.mark.parametrize('failure', ['corruption', 'wrong_key'])
def test_backup_authentication_fails_before_restore(tmp_path, failure):
    module, data, db, env, archive, key = backup_fixture(tmp_path)
    module.create_backup(data, env, archive, key)
    if failure == 'corruption':
        raw = bytearray(archive.read_bytes()); raw[len(raw) // 2] ^= 1; archive.write_bytes(raw)
    else:
        key.write_bytes(os.urandom(32))
    target = tmp_path / 'recovered'
    with pytest.raises(Exception):
        module.verify_or_restore(archive, key, target)
    assert not target.exists()
    assert db.one('SELECT count(*) AS n FROM users')['n'] == 2


def test_backup_rejects_external_links_and_keeps_existing_backup(tmp_path):
    module, data, db, env, archive, key = backup_fixture(tmp_path)
    outside = tmp_path / 'outside'; outside.write_text('unrelated file')
    (data / 'external').symlink_to(outside)
    with pytest.raises(ValueError):
        module.create_backup(data, env, archive, key)
    assert not archive.exists() and outside.read_text() == 'unrelated file'
    (data / 'external').unlink()
    module.create_backup(data, env, archive, key)
    before = archive.read_bytes()
    with pytest.raises(ValueError):
        module.create_backup(data, env, archive, key)
    assert archive.read_bytes() == before


def test_git_guard_rejects_forced_private_files_and_tokens(tmp_path, monkeypatch, capsys):
    module = load_deploy('check-tracked-secrets')
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / '.env').write_text('SQLSERVER_PASSWORD=fixture-value')
    subprocess.run(['git','-C',str(tmp_path),'add','-f','.env'],check=True)
    assert module.check()
    assert 'fixture-value' not in capsys.readouterr().err
    subprocess.run(['git','-C',str(tmp_path),'rm','--cached','-q','.env'],check=True)
    (tmp_path / 'configuration.txt').write_text('sk-proj-' + 'x' * 40)
    subprocess.run(['git','-C',str(tmp_path),'add','configuration.txt'],check=True)
    assert module.check()


def test_native_nginx_https_configuration_parses(tmp_path):
    nginx, openssl = shutil.which('nginx'), shutil.which('openssl')
    if not nginx or not openssl:
        pytest.skip('Nginx and OpenSSL are needed for native configuration validation.')
    certificate, key = tmp_path / 'test.crt', tmp_path / 'test.key'
    subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-days','1',
                    '-subj','/CN=reports.example.test','-keyout',str(key),'-out',str(certificate)],
                   check=True, capture_output=True)
    site = (ROOT / 'deploy/nginx-https.conf').read_text()
    site = site.replace('/etc/letsencrypt/live/reports.example.com/fullchain.pem',str(certificate))
    site = site.replace('/etc/letsencrypt/live/reports.example.com/privkey.pem',str(key))
    (tmp_path / 'site.conf').write_text(site)
    config = tmp_path / 'nginx.conf'
    config.write_text(f'pid {tmp_path}/nginx.pid; error_log stderr; events {{}} http {{ access_log off; '
                      f'client_body_temp_path {tmp_path}/body; proxy_temp_path {tmp_path}/proxy; '
                      f'fastcgi_temp_path {tmp_path}/fastcgi; uwsgi_temp_path {tmp_path}/uwsgi; scgi_temp_path {tmp_path}/scgi; '
                      f'include {tmp_path}/site.conf; }}')
    result = subprocess.run([nginx,'-t','-e','stderr','-p',str(tmp_path),'-c',str(config)],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_backup_wrapper_restarts_service_on_backup_failure(tmp_path):
    app = tmp_path / 'app'; (app / 'deploy').mkdir(parents=True); (app / '.venv/bin').mkdir(parents=True)
    shutil.copy(ROOT / 'deploy/backup.sh', app / 'deploy/backup.sh')
    executable = app / '.venv/bin/python'; executable.write_text('#!/bin/sh\nexit 1\n'); executable.chmod(0o755)
    binaries = tmp_path / 'bin'; binaries.mkdir(); log = tmp_path / 'service-calls'
    systemctl = binaries / 'systemctl'
    systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "$SERVICE_TEST_LOG"\nexit 0\n'); systemctl.chmod(0o755)
    environment = {**os.environ, 'PATH':str(binaries)+':'+os.environ['PATH'],'SERVICE_TEST_LOG':str(log)}
    result = subprocess.run(['bash',str(app / 'deploy/backup.sh'),str(tmp_path / 'backups')],env=environment,capture_output=True)
    assert result.returncode != 0
    assert log.read_text().splitlines() == ['is-active','stop','start']


@pytest.mark.parametrize('dialect,permission,expected', [
    ('sqlserver','SELECT','read_only_inventory'), ('sqlserver','INSERT','requires_dba'),
    ('sqlserver','CONTROL SERVER','requires_dba'), ('hana','SELECT','read_only_inventory'),
    ('hana','USER ADMIN','requires_dba'), ('hana','EXECUTE','requires_dba'),
])
def test_operator_privilege_checks_are_read_only_and_conservative(dialect, permission, expected):
    module = load_deploy('check_database_permissions')
    class Connector:
        def _run_full(self, query, parameters):
            assert query.lstrip().startswith('SELECT') and parameters == {}
            if "IS_SRVROLEMEMBER" in query:
                return [{'is_admin': 0}]
            return [{'permission_name': permission}]
    connector = Connector(); connector.dialect = dialect
    assert module.inspect(connector)['status'] == expected


def test_production_connectors_refuse_weakened_transport_before_connecting(tmp_path):
    from app.connectors import SQLServerConnector, SourceNotConfigured
    from app.hana import HanaConnector
    settings = replace(production_settings(tmp_path), sqlserver_host='fixture',sqlserver_user='fixture',
                       sqlserver_password='fixture',sqlserver_encryption='off',hana_encrypt=False)
    class Driver:
        def connect(self, **kwargs):
            raise AssertionError('Insecure connection must not be attempted')
    for connector in [SQLServerConnector(settings, None, Driver()), HanaConnector(settings, None, Driver())]:
        with pytest.raises(SourceNotConfigured, match='Production'):
            connector._connect()
