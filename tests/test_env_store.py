import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet

from app.config import Settings
from app.env_store import EnvStore, prefix_for, read_environment
from app.source_secrets import SourceSecrets
from conftest import HEADERS
from test_source_credentials import source_input


def test_env_round_trip_preserves_literal_secrets_and_unrelated_settings(tmp_path):
    path = tmp_path / ".env"
    original = "# operator settings\nPORT=8080\nSQLSERVER_PASSWORD='untouched$#secret'\n"
    path.write_text(original)
    settings = Settings(data_dir=tmp_path, env_file=path)
    store = EnvStore(settings)
    password = "spaces ' quote \\\" ${HOME} $cash #hash\nsecond line\të"
    values = {"HANA_HOST":"fixture", "HANA_PORT":"30015", "HANA_PASSWORD":password, "HANA_DATABASE":""}
    store.put("first", values)
    store.put("second", {"HANA_PASSWORD":"another"})
    assert store.get("first") == values
    assert read_environment(path)["SQLSERVER_PASSWORD"] == "untouched$#secret"
    store.put("first", {"HANA_PASSWORD":"replaced"})
    assert password not in path.read_text() and "second line" not in path.read_text()
    assert store.get("second") == {"HANA_PASSWORD":"another"}
    store.put("first", None)
    store.put("second", None)
    assert path.read_text() == original
    assert not store.journal.exists()


def test_parallel_profiles_do_not_overwrite_each_other(tmp_path):
    settings = Settings(data_dir=tmp_path, env_file=tmp_path/".env")
    def save(index):
        EnvStore(settings).put(str(index), {"HANA_HOST":str(index), "HANA_PASSWORD":"private"+str(index)})
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(save, range(15)))
    for index in range(15):
        assert EnvStore(settings).get(str(index))["HANA_HOST"] == str(index)


def test_torn_env_write_is_recovered_before_reading_settings(tmp_path):
    path = tmp_path / ".env"
    store = EnvStore(Settings(data_dir=tmp_path, env_file=path))
    before = "PORT=8080\n"
    store.journal.write_text(json.dumps({"path":str(path),"before":before,"after_sha":hashlib.sha256(b'new complete contents').hexdigest()}))
    path.write_text("new incomplete")
    with store.locked():
        pass
    assert path.read_text() == before and not store.journal.exists()


def test_legacy_encrypted_credentials_migrate_to_project_env_without_erasing_existing_config(client, admin, tmp_path):
    source = client.post("/api/admin/sources", headers=HEADERS, json=source_input()).json()
    state = client.app.state
    key = Fernet.generate_key()
    path = state.settings.data_dir / 'source-credentials.key'
    path.write_bytes(key)
    os.chmod(path, 0o600)
    values = {k:str(v) for k,v in source_input().items() if k.startswith('SQLSERVER_')}
    ciphertext = Fernet(key).encrypt(json.dumps({'source_id':source['id'],'values':values}).encode()).decode()
    state.db.execute('UPDATE source_credentials SET ciphertext=? WHERE source_id=?',(ciphertext,source['id']))
    env = tmp_path/'.env'
    env.write_text('# preserved\nPORT=8080\n')
    state.settings.env_file = env
    migrated = SourceSecrets(state.settings,state.db)
    assert migrated.load(source['id']) == values
    assert env.read_text().startswith('# preserved\nPORT=8080\n')
    assert prefix_for(source['id'])+'SQLSERVER_PASSWORD=' in env.read_text()
    assert state.db.one('SELECT ciphertext FROM source_credentials WHERE source_id=?',(source['id'],))['ciphertext']=='env'
    assert migrated.load(source['id']) == values
