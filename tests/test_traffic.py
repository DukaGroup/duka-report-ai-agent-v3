import json

from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_excel_reports import subscribe
from test_database_chat import call_tool, fixture_source, query_plan
from app.connectors import DatabaseUnavailable


def test_admin_traffic_counts_full_stream_and_excludes_credentials_payloads_and_polling(client, admin):
    subscribe(client)
    conversation = client.post("/api/conversations", headers=HEADERS, json={}).json()
    private_text = "Sensitive financial document content"
    response = client.post(f"/api/conversations/{conversation['id']}/messages", headers=HEADERS, json={"content": private_text})
    assert response.status_code == 200
    traffic = client.get("/api/admin/traffic").json()
    serialized = json.dumps(traffic)
    assert private_text not in serialized and "a-long-test-password" not in serialized
    assert client.cookies.get("duka_session") not in serialized
    directions = {event["direction"] for event in traffic["events"]}
    assert {"frontend-backend", "backend-frontend", "backend-model", "model-backend"} <= directions
    stream = next(e for e in traffic["events"] if e["action"] == "POST /api/conversations/{conversation_id}/messages" and e["direction"] == "backend-frontend")
    assert stream["bytes"] == len(response.content) and stream["duration_ms"] > 0
    assert not any("admin/traffic" in e["action"] for e in traffic["events"])
    assert not any("authUrl" in json.dumps(e) or "accessToken" in json.dumps(e) for e in traffic["events"])


def test_traffic_can_filter_paginate_and_is_admin_only(client, admin):
    for _ in range(4):
        client.get("/api/conversations")
    first = client.get("/api/admin/traffic?direction=backend-frontend&limit=2").json()
    assert len(first["events"]) == 2 and first["next_before"]
    second = client.get(f"/api/admin/traffic?direction=backend-frontend&limit=2&before={first['next_before']}").json()
    assert not ({e["id"] for e in first["events"]} & {e["id"] for e in second["events"]})
    assert client.get("/api/admin/traffic?direction=unknown").status_code == 422
    create_member(client)
    sign_in_member(client)
    assert client.get("/api/admin/traffic").status_code == 403


def test_sql_failure_and_tool_round_trip_are_visible_without_filter_values(client, admin, monkeypatch):
    source, connector = fixture_source(client)

    async def broken(query):
        raise DatabaseUnavailable("Unavailable view", code=208)

    monkeypatch.setattr(connector, "query", broken)
    call_tool(client, admin, "query_database", {"source_id": source["id"], "query": query_plan(filters=[{"column": "s.Id", "operator": "eq", "value": "private-filter"}])})
    traffic = client.get("/api/admin/traffic").json()
    assert "private-filter" not in json.dumps(traffic)
    assert any(e["direction"] == "database-backend" and e["status"] == "error" and e["detail"]["database_error_code"] == 208 for e in traffic["events"])
    assert any(e["direction"] == "backend-model" and e["action"] == "tool/query_database" and e["status"] == "error" for e in traffic["events"])


def test_traffic_retains_every_event_and_survives_recorder_recreation(client, admin):
    from app.traffic import TrafficLog

    log = client.app.state.traffic
    client.portal.call(log.flush)
    baseline = log.db.one("SELECT count(*) AS n FROM traffic_events")["n"]
    for _ in range(10025):
        log.record("model-backend", "fixture", "received")
    client.portal.call(log.flush)
    assert log.db.one("SELECT count(*) AS n FROM traffic_events")["n"] == baseline + 10025
    fresh = TrafficLog(client.app.state.db)
    assert fresh.db.one("SELECT count(*) AS n FROM traffic_events")["n"] == baseline + 10025
    assert client.get("/api/admin/traffic").json()["capacity"] is None
    for before in (-1, 9223372036854775808):
        assert client.get(f"/api/admin/traffic?before={before}").status_code == 422


def test_admin_can_open_message_payloads_but_auth_credentials_and_tokens_never_appear(client, admin):
    from app.config import Settings
    log=client.app.state.traffic
    log.protect_settings(Settings(env_file=None,sqlserver_host='secret-host',sqlserver_user='secret-login',sqlserver_password='secret-db-password'))
    subscribe(client)
    chat=client.post('/api/conversations',headers=HEADERS,json={}).json()
    text='Analyze revenue. secret-db-password SQLSERVER_PASSWORD=secret-db-password'
    client.post(f"/api/conversations/{chat['id']}/messages",headers=HEADERS,json={'content':text})
    events=client.get('/api/admin/traffic').json()['events']
    sent=next(e for e in events if e['direction']=='frontend-backend' and e['action']=='POST /api/conversations/{conversation_id}/messages' and e['has_payload'])
    detail=client.get(f"/api/admin/traffic/{sent['id']}").json()
    assert 'Analyze revenue.' in detail['payload']['content']
    assert 'secret-db-password' not in json.dumps(detail) and '[REDACTED]' in json.dumps(detail)
    assert 'payload' not in sent
    auth=[e for e in events if '/auth/' in e['action'] or '/subscription' in e['action']]
    for event in auth:
        value=client.get(f"/api/admin/traffic/{event['id']}").json()
        assert 'a-long-test-password' not in json.dumps(value) and 'TEST-CODE' not in json.dumps(value)
    create_member(client)
    sign_in_member(client)
    assert client.get(f"/api/admin/traffic/{sent['id']}").status_code==403


def test_payloads_are_redacted_bounded_and_not_recursively_logged(client, admin):
    log=client.app.state.traffic
    log.record('model-backend','payload-fixture','received',payload={'access_token':'private-token','nested':json.dumps({'password':'private-password','text':'visible'}),'rows':[{'text':'x'*30000} for _ in range(150)]})
    events=client.get('/api/admin/traffic').json()['events']
    event=next(e for e in events if e['action']=='payload-fixture')
    detail=client.get(f"/api/admin/traffic/{event['id']}").json()
    assert detail['payload_truncated']
    assert 'private-token' not in json.dumps(detail) and 'private-password' not in json.dumps(detail)
    row=client.app.state.db.one('SELECT payload_json FROM traffic_events WHERE id=?',(event['id'],))
    assert len(row['payload_json'].encode()) <= 65536
    after=client.get('/api/admin/traffic').json()['events']
    assert not any('admin/traffic' in e['action'] for e in after)


def test_sql_filters_and_model_tool_results_are_available_in_admin_payloads(client, admin):
    source,connector=fixture_source(client)
    call_tool(client,admin,'query_database',{'source_id':source['id'],'query':query_plan(filters=[{'column':'s.Id','operator':'eq','value':'requested-filter'}])})
    events=client.get('/api/admin/traffic').json()['events']
    event=next(e for e in events if e['direction']=='model-backend' and e['action']=='tool/query_database')
    detail=client.get(f"/api/admin/traffic/{event['id']}").json()
    assert detail['payload']['arguments']['query']['filters'][0]['value']=='requested-filter'


def test_auth_rpc_responses_and_embedded_credentials_are_redacted(client, admin):
    log=client.app.state.traffic
    log.protocol('backend-model',{'id':123,'method':'account/login/start','params':{}},50,'fixture',admin['id'])
    log.protocol('model-backend',{'id':123,'result':{'authUrl':'https://example.invalid/?secret=never-visible','userCode':'never-visible-code'}},100,'fixture',admin['id'])
    log.record('model-backend','credential-fixture','received',payload={'text':'password="never-visible-password"\n-----BEGIN PRIVATE KEY-----\nnever-visible-key\n-----END PRIVATE KEY-----'})
    events=client.get('/api/admin/traffic').json()['events']
    details=[client.get(f"/api/admin/traffic/{e['id']}").json() for e in events if e['action'] in ('rpc/response','credential-fixture')]
    assert details and 'never-visible' not in json.dumps(details)
