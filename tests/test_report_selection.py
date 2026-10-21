from pathlib import Path

import pytest

from app.db import now
from conftest import HEADERS
from test_application import create_member


def report(client, user_id, identifier, *, trash=False, status='completed', snapshot=None):
    db=client.app.state.db
    snapshot=snapshot or identifier+'-snapshot'
    db.execute("INSERT OR IGNORE INTO dataset_snapshots VALUES(?,?,NULL,'{}','[]',?)",(snapshot,user_id,now()))
    db.execute("INSERT INTO reports(id,user_id,template_id,snapshot_id,title,instructions,status,created_at,deleted_at) VALUES(?,?,'executive',?,?,'',?,?,?)",(identifier,user_id,snapshot,identifier,status,now(),now() if trash else None))
    folder=client.app.state.settings.data_dir/'reports';folder.mkdir(exist_ok=True)
    path=folder/(identifier+'.xlsx');path.write_bytes(identifier.encode())
    return path,snapshot


def delete(client,ids,permanent=False):
    return client.post('/api/reports/bulk-delete',headers=HEADERS,json={'report_ids':ids,'permanent':permanent})


def test_soft_delete_changes_only_selected_reports_and_can_be_restored(client,admin):
    for id in ['one','two','keep']:report(client,admin['id'],id)
    assert client.post('/api/reports/bulk-delete',json={'report_ids':['one']}).status_code==403
    response=delete(client,['one','two','one'])
    assert response.status_code==200 and response.json()['deleted_count']==2
    assert [r['id'] for r in client.get('/api/reports').json()]==['keep']
    assert {r['id'] for r in client.get('/api/reports?deleted=true').json()}=={'one','two'}
    assert client.post('/api/reports/one/restore',headers=HEADERS).status_code==200
    assert client.get('/api/reports/one').status_code==200


@pytest.mark.parametrize('unavailable',['foreign','missing','already-trashed','running'])
def test_invalid_soft_selection_never_partially_deletes(client,admin,unavailable):
    report(client,admin['id'],'keep')
    if unavailable=='foreign':
        other=create_member(client)
        report(client,other['id'],'foreign')
    elif unavailable=='already-trashed':report(client,admin['id'],unavailable,trash=True)
    elif unavailable=='running':report(client,admin['id'],unavailable,status='running')
    assert delete(client,['keep',unavailable]).status_code==(409 if unavailable=='running' else 404)
    assert client.get('/api/reports/keep').status_code==200


def test_purge_selection_retains_unselected_reports_files_and_shared_snapshots(client,admin):
    gone,shared=report(client,admin['id'],'gone',trash=True)
    kept,_=report(client,admin['id'],'kept',trash=True,snapshot=shared)
    live,_=report(client,admin['id'],'live')
    response=delete(client,['gone'],True)
    assert response.status_code==200 and response.json()['deleted_count']==1
    assert not gone.exists() and kept.read_bytes()==b'kept' and live.exists()
    assert client.app.state.db.one('SELECT id FROM dataset_snapshots WHERE id=?',(shared,))
    assert [r['id'] for r in client.get('/api/reports?deleted=true').json()]==['kept']
    assert client.post('/api/reports/kept/restore',headers=HEADERS).status_code==200


@pytest.mark.parametrize('unavailable',['foreign','missing','not-trashed','running'])
def test_invalid_purge_selection_never_removes_owned_files(client,admin,unavailable):
    kept,_=report(client,admin['id'],'keep',trash=True)
    if unavailable=='foreign':
        other=create_member(client);report(client,other['id'],'foreign',trash=True)
    elif unavailable=='not-trashed':report(client,admin['id'],unavailable)
    elif unavailable=='running':report(client,admin['id'],unavailable,trash=True,status='running')
    assert delete(client,['keep',unavailable],True).status_code==(409 if unavailable=='running' else 404)
    assert kept.exists() and client.app.state.db.one("SELECT id FROM reports WHERE id='keep'")


def test_purge_storage_error_preserves_every_selected_report_and_snapshot(client,admin,monkeypatch):
    first,snap1=report(client,admin['id'],'first',trash=True)
    second,snap2=report(client,admin['id'],'second',trash=True)
    unlink=Path.unlink
    def fail(path,*args,**kwargs):
        if path==second:raise PermissionError('private filesystem path')
        return unlink(path,*args,**kwargs)
    monkeypatch.setattr(Path,'unlink',fail)
    response=delete(client,['first','second'],True)
    assert response.status_code==503 and 'private filesystem path' not in response.text
    assert len(client.get('/api/reports?deleted=true').json())==2
    for snapshot in [snap1,snap2]:assert client.app.state.db.one('SELECT id FROM dataset_snapshots WHERE id=?',(snapshot,))


@pytest.mark.parametrize('ids',[[],['../bad'],['x'*129]])
def test_malformed_selections_are_rejected(client,admin,ids):
    report(client,admin['id'],'keep',trash=True)
    assert delete(client,ids,True).status_code==422
    assert client.app.state.db.one("SELECT id FROM reports WHERE id='keep'")
