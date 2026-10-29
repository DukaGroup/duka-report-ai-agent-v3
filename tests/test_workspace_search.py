import json
from app.db import now
from app.progress import public_step
from test_conversation_trash import populated
from test_application import create_member, sign_in_member
from test_report_selection import report


def test_search_finds_own_messages_reports_and_admin_events_without_profiles(client,admin):
    cid=populated(client,'Quarterly needleword and 100% literal')
    db=client.app.state.db
    report(client,admin['id'],'needleword-report')
    db.execute("UPDATE reports SET instructions='needleword instructions' WHERE id='needleword-report'")
    client.app.state.traffic.record('model-backend','needleword-event','received')
    client.portal.call(client.app.state.traffic.flush)
    response=client.get('/api/search?q=needleword')
    assert response.status_code==200,response.text
    kinds={item['kind'] for item in response.json()['results']}
    assert {'conversation','report','traffic'} <= kinds
    assert any(item['id']==cid for item in response.json()['results'])
    assert client.get('/api/search?q=%').json()['results']==[]
    assert client.get('/api/search?q='+('a'*201)).status_code==422
    assert client.get('/api/search').json()=={'results':[]}


def test_search_cannot_leak_other_users_or_admin_only_events(client,admin):
    cid=populated(client,'private-search-fixture')
    report(client,admin['id'],'private-search-fixture-report')
    db=client.app.state.db
    db.execute("INSERT INTO data_sources(id,name,kind,description,status,created_at) VALUES('private-source','private-search-fixture','sqlserver','','not_configured',?)",(now(),))
    client.app.state.system_logs.record('error','database','private-search-fixture','private-search-fixture failed')
    client.portal.call(client.app.state.system_logs.flush)
    client.app.state.traffic.record('model-backend','private-search-fixture','error')
    client.portal.call(client.app.state.traffic.flush)
    assert {'source','log','traffic'} <= {item['kind'] for item in client.get('/api/search?q=private-search-fixture').json()['results']}
    create_member(client)
    sign_in_member(client)
    assert client.get('/api/search?q=private-search-fixture').json()['results']==[]
    assert client.get('/api/admin/traffic?q=private-search-fixture').status_code==403
    own=populated(client,'private-search-fixture')
    assert client.get('/api/search?q=private-search-fixture').json()['results'][0]['id']==own
    assert cid!=own


def test_traffic_search_finds_old_payloads_with_literal_wildcards_and_paging(client,admin):
    log=client.app.state.traffic
    for i in range(8):
        log.record('model-backend','search-fixture','received',payload={'text':f'100% literal needleword {i}'})
    first=client.get('/api/admin/traffic?q=100%25&limit=3').json()
    assert len(first['events'])==3
    second=client.get(f"/api/admin/traffic?q=100%25&limit=3&before={first['next_before']}").json()
    assert len(second['events'])==3
    assert not {e['id'] for e in first['events']} & {e['id'] for e in second['events']}
    assert client.get('/api/admin/traffic?q=missing-term').json()['events']==[]


def test_report_search_finds_content_and_hides_revoked_private_contents(client,admin):
    db=client.app.state.db
    report(client,admin['id'],'content-report')
    db.execute("UPDATE reports SET content_json=? WHERE id='content-report'",(json.dumps({'summary':'profit-search-needle'}),))
    assert [r['id'] for r in client.get('/api/reports?q=profit-search-needle').json()]==['content-report']
    assert client.get('/api/reports?q=missing-term').json()==[]
    member=create_member(client)
    db.execute("INSERT INTO data_sources(id,name,kind,description,status,enabled,created_at) VALUES('s-private','Private','sqlserver','','connected',1,?)",(now(),))
    db.execute("INSERT INTO source_grants VALUES(?,?)",('s-private',member['id']))
    from app.data_access import DataAccess
    stamp=DataAccess(db).stamp(member['id'],'s-private',None)
    report(client,member['id'],'member-report')
    db.execute("UPDATE dataset_snapshots SET provenance_json=? WHERE id='member-report-snapshot'",
        (json.dumps({'source_id':'s-private','access_stamp':stamp}),))
    db.execute("UPDATE reports SET content_json=? WHERE id='member-report'",
        (json.dumps({'summary':'private-profit-needle'}),))
    sign_in_member(client)
    assert [r['id'] for r in client.get('/api/reports?q=private-profit-needle').json()]==['member-report']
    assert [r['id'] for r in client.get('/api/search?q=private-profit-needle').json()['results']]==['member-report']
    db.execute("DELETE FROM source_grants WHERE user_id=? AND source_id=?",(member['id'],'s-private'))
    assert client.get('/api/reports?q=private-profit-needle').json()==[]
    assert client.get('/api/search?q=private-profit-needle').json()['results']==[]


def test_public_progress_never_exposes_private_reasoning_or_tool_inputs(client,admin):
    assert public_step({'type':'activity','activity':'reasoning','text':'private-reasoning'})=={'kind':'activity','label':'Arsyetim'}
    assert public_step({'type':'delta','text':'private-reasoning'}) is None
    cid=populated(client)
    db=client.app.state.db
    mid='assistant-fixture'
    db.execute('INSERT INTO messages VALUES(?,?,?,?,?,?)',(mid,cid,'assistant','Done','completed',now()))
    db.execute('INSERT INTO chat_runs VALUES(?,?,?,?,?,?,?)',(mid,cid,admin['id'],'{}','completed',1,now()))
    for event in [{'type':'activity','activity':'reasoning','text':'private-reasoning'}, {'type':'tool','name':'query_database','arguments':{'password':'private-password'}}, {'type':'done','status':'completed'}]:
        client.app.state.chat_jobs.record(mid,event)
    result=client.get('/api/conversations/'+cid).json()
    steps=next(m for m in result['messages'] if m['id']==mid)['steps']
    assert len(steps)==3 and steps[1]['label']=='Lexim i të dhënave'
    assert 'private-' not in json.dumps(steps)
