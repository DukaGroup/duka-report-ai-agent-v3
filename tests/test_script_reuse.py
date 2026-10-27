"""Reuse immutable code across chats, never old results or permissions."""

import copy
import io
import json

import openpyxl
import pytest

from app.provider import CodexRuntime
from app.calculations import CalculationPlan
from app.script_library import ScriptLibrary, workbook_signature
from app.script_reuse import ScriptReuse, apply_reuse, script_hash
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_excel_reports import subscribe, wait_report
from test_model_calculations import SCRIPT, invoke, setup


def reference(source_id, source, edits=()):
    return {'source_id': source_id, 'sha256': script_hash(source), 'edits': list(edits)}


def other_chat(client):
    chat = client.post('/api/conversations', headers=HEADERS, json={}).json()['id']
    thread = 'reuse-' + chat
    client.app.state.db.execute('UPDATE conversations SET provider_thread_id=? WHERE id=?', (thread, chat))
    return chat, thread


def test_cross_chat_lookup_patch_and_fresh_complete_calculation(client, admin):
    _, ledger, _, first_thread, plan = setup(client, admin)
    first = invoke(client, admin, first_thread, 'calculate_data', plan)
    chat, thread = other_chat(client)
    found = invoke(client, admin, thread, 'find_calculation_scripts', {'query': 'SAP balances cutoff'})
    candidate = found['scripts'][0]
    assert candidate['source_id'] == 'calculation:' + first['calculation_id']
    assert 'script' not in candidate and 'rows' not in json.dumps(found)
    read = invoke(client, admin, thread, 'read_calculation_script', {'source_id': candidate['source_id']})
    assert read['script'] == SCRIPT and read['inputs'] == CalculationPlan.model_validate(plan).model_dump(by_alias=True)['inputs']
    assert 'excluded-late-invoice' not in json.dumps(read)
    changed = copy.deepcopy(plan)
    changed.pop('script')
    changed['rules'] = 'Same verified scope, now use cutoff Aug26; fresh data.'
    changed['script_reuse'] = reference(candidate['source_id'], SCRIPT, [
        {'before': '2026-08-25', 'after': '2026-08-26', 'occurrences': 2}])
    ledger.rows[0]['amount'] = '1.10'
    second = invoke(client, admin, thread, 'calculate_data', changed)
    assert second['datasets'][0]['rows'][0]['balance'] == '200.98'
    assert len(ledger.calls) == 2 and first['calculation_id'] != second['calculation_id']
    saved = client.app.state.db.one('SELECT provenance_json FROM calculation_runs WHERE id=? AND conversation_id=?',
                                  (second['calculation_id'], chat))
    provenance = json.loads(saved['provenance_json'])
    assert provenance['plan']['script'] == SCRIPT.replace('2026-08-25', '2026-08-26')
    original = client.app.state.db.one('SELECT provenance_json FROM calculation_runs WHERE id=?', (first['calculation_id'],))
    assert json.loads(original['provenance_json'])['plan']['script'] == SCRIPT
    assert client.app.state.db.one("SELECT 1 FROM audit_events WHERE action='calculation.script_reused' AND target_id=?",
                                   (second['calculation_id'],))


@pytest.mark.parametrize('fault', ['hash', 'missing', 'ambiguous', 'unsafe', 'both', 'neither'])
def test_invalid_reuse_is_rejected_before_fresh_queries(client, admin, fault):
    _, ledger, _, thread, plan = setup(client, admin)
    first = invoke(client, admin, thread, 'calculate_data', plan)
    changed = copy.deepcopy(plan)
    changed.pop('script')
    changed['script_reuse'] = reference('calculation:' + first['calculation_id'], SCRIPT)
    if fault == 'hash':
        changed['script_reuse']['sha256'] = '0' * 64
    elif fault in ('missing', 'ambiguous', 'unsafe'):
        before, after = {'missing': ('absent-token', 'x'), 'ambiguous': ('2026-08-25', '2026-08-26'),
                         'unsafe': ('total = number(\'0\')', "total = open('/etc/passwd')")}[fault]
        changed['script_reuse']['edits'] = [{'before': before, 'after': after, 'occurrences': 1}]
    elif fault == 'both':
        changed['script'] = SCRIPT
    else:
        changed.pop('script_reuse')
    assert 'error' in invoke(client, admin, thread, 'calculate_data', changed)
    assert len(ledger.calls) == 1
    assert len(client.app.state.db.all('SELECT id FROM calculation_runs')) == 1


def test_library_enforces_owner_trash_archives_and_revoked_source(client, admin):
    source, _, chat, thread, plan = setup(client, admin)
    result = invoke(client, admin, thread, 'calculate_data', plan)
    identifier = result['calculation_id']
    source_id = 'calculation:' + identifier
    library = ScriptLibrary(client.app.state.db)
    assert library.find_calculations(admin['id'], 'SAP')['scripts']
    member = create_member(client)
    assert library.find_calculations(member['id'], 'SAP')['scripts'] == []
    with pytest.raises(ValueError, match='not found'):
        library.calculation(member['id'], source_id)
    client.app.state.db.execute("INSERT INTO conversation_branches VALUES('fixture-branch',?,'fixture-message','{}','now')", (chat,))
    client.app.state.db.execute("INSERT INTO archived_calculations VALUES(?,?)", (identifier, 'fixture-branch'))
    assert library.find_calculations(admin['id'], 'SAP')['scripts'] == []
    client.app.state.db.execute('DELETE FROM archived_calculations')
    client.delete(f'/api/conversations/{chat}', headers=HEADERS)
    assert library.find_calculations(admin['id'], 'SAP')['scripts'] == []
    client.post(f'/api/conversations/{chat}/restore', headers=HEADERS)
    client.app.state.db.execute('UPDATE data_sources SET enabled=0 WHERE id=?', (source['id'],))
    assert library.find_calculations(admin['id'], 'SAP')['scripts'] == []
    assert 'error' in invoke(client, admin, thread, 'read_calculation_script', {'source_id': source_id})


def test_saved_report_remains_script_source_after_original_chat_is_purged(client, admin, monkeypatch):
    subscribe(client)
    prompts = layout_runtime(monkeypatch)
    _, _, chat, thread, plan = setup(client, admin)
    calculation = invoke(client, admin, thread, 'calculate_data', plan)
    report = invoke(client, admin, thread, 'create_calculation_report', {
        'calculation_id': calculation['calculation_id'], 'calculation_datasets': ['Balances'],
        'title': 'SAP balances', 'instructions': 'Captured eligible balances only'})
    assert wait_report(client, report['report_id'])['status'] == 'completed'
    prompt_calculation = prompts[0]['provenance']['calculation']
    assert 'script' not in prompt_calculation and prompt_calculation['rules'] == plan['rules']
    client.delete(f'/api/conversations/{chat}', headers=HEADERS)
    purged = client.post('/api/conversations/bulk-delete', headers=HEADERS, json={'conversation_ids': [chat], 'permanent': True})
    assert purged.status_code == 200, purged.text
    assert not client.app.state.db.all('SELECT id FROM calculation_runs')
    _, new_thread = other_chat(client)
    found = invoke(client, admin, new_thread, 'find_calculation_scripts', {'query': 'SAP balances'})
    assert found['scripts'][0]['source_id'] == 'report:' + report['report_id']
    read = invoke(client, admin, new_thread, 'read_calculation_script', {'source_id': found['scripts'][0]['source_id']})
    assert read['script'] == SCRIPT
    client.delete('/api/reports/' + report['report_id'], headers=HEADERS)
    assert invoke(client, admin, new_thread, 'find_calculation_scripts', {'query': 'SAP balances'})['scripts'] == []


def test_old_tool_catalog_can_find_read_and_reuse_without_creating_reports(client, admin):
    source, ledger, _, thread, plan = setup(client, admin)
    first = invoke(client, admin, thread, 'calculate_data', plan)
    wrapper = {'source_id': source['id'], 'query': plan['inputs'][0]['query'], 'title': 'Lookup',
               'instructions': 'FIND_CALCULATION_SCRIPTS\n' + json.dumps({'query': 'SAP balances'})}
    found = invoke(client, admin, thread, 'create_database_report', wrapper)
    candidate = found['scripts'][0]
    wrapper['instructions'] = 'READ_CALCULATION_SCRIPT\n' + json.dumps({'source_id': candidate['source_id']})
    assert invoke(client, admin, thread, 'create_database_report', wrapper)['script'] == SCRIPT
    reused = {**plan, 'script': None, 'script_reuse': reference('calculation:' + first['calculation_id'], SCRIPT)}
    wrapper['instructions'] = 'CALCULATE_DATA\n' + json.dumps(reused)
    assert 'calculation_id' in invoke(client, admin, thread, 'create_database_report', wrapper)
    assert len(ledger.calls) == 2
    assert client.app.state.db.all('SELECT * FROM reports') == []


def test_active_worker_journals_original_script_access_without_treating_artifact_id_as_database(client, admin):
    subscribe(client)
    source, _, chat, thread, plan = setup(client, admin)
    calculation = invoke(client, admin, thread, 'calculate_data', plan)
    manager = client.app.state.manager
    runtime = client.portal.call(manager.acquire_worker, admin['id'], 'chat', chat, None)
    try:
        native = client.portal.call(runtime.thread, None, None)
        client.app.state.db.execute('UPDATE conversations SET provider_thread_id=? WHERE id=?', (native, chat))
        found = invoke(client, admin, native, 'find_calculation_scripts', {'query': 'SAP balances'})
        assert found['scripts']
        read = invoke(client, admin, native, 'read_calculation_script', {'source_id': 'calculation:' + calculation['calculation_id']})
        assert read['script'] == SCRIPT and '_script_permission_checks' not in read
        journal = client.app.state.db.all('SELECT request_json,response_json FROM model_tool_journal WHERE scope_id=?', (chat,))
        assert len(journal) == 2
        for event in journal:
            checks = json.loads(event['request_json'])['_permission_checks']
            assert checks and checks[0][0] == source['id']
            assert '_script_permission_checks' not in json.loads(event['response_json'])
    finally:
        client.portal.call(manager.release_worker, admin['id'], 'chat', chat)


LAYOUT = "def build(report):\n    s = report.sheet('Analiza')\n    s.title('Gusht 2026')\n    s.metric(0, 'revenue', 'Të ardhurat', currency='ALL')\n    s.table(0)\n"


def layout_runtime(monkeypatch, edit=None):
    original, prompts = CodexRuntime.stream, []

    async def scripted(self, thread_id, content, model=None, output_schema=None, **kwargs):
        payload = json.loads(content) if output_schema else None
        if payload is not None:
            prompts.append(payload)
        async for event in original(self, thread_id, content, model, output_schema, **kwargs):
            if output_schema and event['type'] == 'done' and 'workbook_script_api' in payload and 'title' in payload:
                doc = json.loads(event['text'])
                candidate = payload.get('reusable_workbook_script')
                if candidate:
                    doc['workbook']['python_script'] = None
                    doc['workbook']['script_reuse'] = reference(candidate['source_id'], candidate['script'], [edit] if edit else [])
                else:
                    doc['workbook']['python_script'] = LAYOUT
                event = {**event, 'text': json.dumps(doc)}
            yield event

    monkeypatch.setattr(CodexRuntime, 'stream', scripted)
    return prompts


def generate(client, rows, title='Sales', **options):
    created = client.post('/api/reports', headers=HEADERS, json={'title': title, 'rows': rows, **options})
    assert created.status_code == 201, created.text
    result = wait_report(client, created.json()['id'])
    assert result['status'] == 'completed', result
    return result


def test_workbook_receives_one_compatible_script_patches_and_validates_fresh_rows(client, admin, monkeypatch):
    subscribe(client)
    prompts = layout_runtime(monkeypatch, {'before': 'Gusht 2026', 'after': 'Shtator 2026', 'occurrences': 1})
    first = generate(client, [{'revenue': 42}])
    second = generate(client, [{'revenue': 84}])
    assert prompts[0]['reusable_workbook_script'] is None
    assert prompts[1]['reusable_workbook_script']['source_id'] == 'report:' + first['id']
    assert 'rows' not in prompts[1]['reusable_workbook_script']
    workbook = second['document']['workbook']
    assert workbook['script_reuse'] is None
    assert workbook['python_script'] == LAYOUT.replace('Gusht 2026', 'Shtator 2026')
    assert first['document']['workbook']['python_script'] == LAYOUT
    excel = client.get(f"/api/reports/{second['id']}/export/xlsx").content
    book = openpyxl.load_workbook(io.BytesIO(excel), data_only=True)
    values = [c.value for row in book['Analiza'] for c in row]
    assert 'Shtator 2026' in values and 84 in values and 42 not in values
    assert client.app.state.db.one("SELECT 1 FROM audit_events WHERE action='report.script_reused' AND target_id=?", (second['id'],))


def test_workbook_library_filters_changed_schema_deleted_reports_and_other_users(client, admin, monkeypatch):
    subscribe(client)
    prompts = layout_runtime(monkeypatch)
    first = generate(client, [{'revenue': 42}])
    # Additional fields retain all data, and must not match the prior layout contract.
    generate(client, [{'revenue': 44, 'cost': 22}])
    assert prompts[-1]['reusable_workbook_script'] is None
    client.delete(f"/api/reports/{first['id']}", headers=HEADERS)
    generate(client, [{'revenue': 84}])
    assert prompts[-1]['reusable_workbook_script'] is None
    user = create_member(client)
    sign_in_member(client)
    report = {'id': 'new', 'template_id': 'executive', 'title': 'Sales', 'instructions': ''}
    assert ScriptLibrary(client.app.state.db).workbook_candidate(user['id'], report, {'columns': [{'name': 'revenue', 'type': 'number'}]}) is None


def test_bad_workbook_patch_uses_existing_repair_path_and_only_publishes_validated_excel(client, admin, monkeypatch):
    subscribe(client)
    prompts = layout_runtime(monkeypatch, {'before': 'nonexistent statement', 'after': '', 'occurrences': 1})
    generate(client, [{'revenue': 42}])
    report = generate(client, [{'revenue': 84}])
    assert len(prompts) == 3 and 'validation_error' in prompts[-1]
    assert 'match exactly' in prompts[-1]['validation_error']
    assert report['document']['workbook']['script_reuse'] is None
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 200


def test_workbook_signature_preserves_dataset_order_types_and_reference():
    base = {'columns': [{'name': 'revenue', 'type': 'decimal'}], 'analyses': [{'columns': [{'name': 'cost', 'type': 'decimal'}]}]}
    assert workbook_signature(base) != workbook_signature({'columns': base['analyses'][0]['columns'], 'analyses': [{'columns': base['columns']}]})
    assert workbook_signature(base) != workbook_signature({**base, 'format_reference': {'sheet_layouts': []}})
    assert workbook_signature(base) != workbook_signature({**base, 'columns': [{'name': 'revenue', 'type': 'text'}]})


def test_exact_patch_counts_and_utf8_size_limit():
    reuse = ScriptReuse.model_validate(reference('report:one', 'a a', [{'before': 'a', 'after': 'b', 'occurrences': 2}]))
    assert apply_reuse('a a', reuse) == 'b b'
    oversized = ScriptReuse.model_validate(reference('report:one', 'a', [{'before': 'a', 'after': 'ë' * 40000}]))
    with pytest.raises(ValueError):
        apply_reuse('a', oversized)
