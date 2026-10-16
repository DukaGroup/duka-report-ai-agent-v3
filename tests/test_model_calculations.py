"""Complete-data execution, model-chosen semantics, captured exports and both provider adapters."""

import copy
import io
import json
from decimal import Decimal
from dataclasses import replace

import openpyxl
import pytest
from jsonschema import Draft202012Validator

from app.calculation_script import run_script, validate_script
from app.calculations import validate_output
from app.claude_provider import ClaudeRuntime
from app.provider import BASE_INSTRUCTIONS, REPORT_TOOLS
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_database_chat import FixtureDatabase, fixture_source
from test_excel_reports import subscribe, wait_report


SCRIPT = """def calculate(tables):
    eligible = []
    total = number('0')
    seen = set()
    for row in tables['ledger']:
        key = (row['client'], row['document'])
        require(key not in seen)
        seen.add(key)
        if row['client'] != '400' or row['account'] == 'LOAN_VERIFIED':
            continue
        if date_of(row['posting']) > '2026-08-25':
            continue
        if row['kind'] == 'invoice' and date_of(row['entry']) > '2026-08-25':
            continue
        amount = number(row['amount'])
        total += amount
        eligible.append({'document': row['document'], 'currency': 'ALL', 'balance': amount})
    return {'datasets': [
        {'name': 'Balances', 'columns': [{'name': 'currency', 'type': 'text'}, {'name': 'balance', 'type': 'decimal'}],
         'rows': [{'currency': 'ALL', 'balance': total}]},
        {'name': 'Eligible documents', 'columns': [{'name': 'document', 'type': 'text'}, {'name': 'currency', 'type': 'text'}, {'name': 'balance', 'type': 'decimal'}], 'rows': eligible}],
        'notes': ['Fixture rule: invoice entry cutoff only; no rule change to match a reference.']}
"""


class Ledger(FixtureDatabase):
    def __init__(self, settings, catalog):
        super().__init__(settings, catalog)
        self.rows = [{'client': '400', 'document': str(i), 'account': 'TRADE', 'kind': 'invoice',
                      'posting': '20260825', 'entry': '20260825', 'amount': '0.10'} for i in range(600)]
        self.rows += [
            {**self.rows[0], 'document': 'later-payment', 'kind': 'payment', 'entry': '20260826', 'amount': '-10.02'},
            {**self.rows[0], 'document': 'excluded-late-invoice', 'entry': '20260826', 'amount': '150'},
            {**self.rows[0], 'document': 'excluded-loan', 'account': 'LOAN_VERIFIED', 'amount': '9000'},
            {**self.rows[0], 'document': 'excluded-client', 'client': '500', 'amount': '10000'},
        ]

    async def describe(self, schema, table):
        return {'columns': [{'name': k, 'type': 'decimal' if k == 'amount' else 'nvarchar'} for k in self.rows[0]]}

    def _run_full(self, sql, parameters):
        assert 'TOP' not in sql and 'LIMIT' not in sql
        self.calls.append((sql, parameters))
        return copy.deepcopy(self.rows)


def setup(client, admin):
    source, _ = fixture_source(client)
    state = client.app.state
    ledger = Ledger(state.settings, state.connectors.catalog)
    state.connectors.register(source['id'], ledger)
    chat = client.post('/api/conversations', headers=HEADERS, json={}).json()['id']
    thread = 'calculation-' + chat
    state.db.execute('UPDATE conversations SET provider_thread_id=? WHERE id=?', (thread, chat))
    query = {'tables': [{'schema': 'dbo', 'name': 'Ledger', 'alias': 't'}],
             'select': [{'column': 't.' + c, 'alias': c} for c in ledger.rows[0]], 'limit': 1}
    plan = {'inputs': [{'kind': 'database', 'name': 'ledger', 'source_id': source['id'], 'database': 'Fixture', 'query': query}],
            'rules': 'SAP 400 only; accounting date <= Aug25; exclude late invoices only and verified loan account. Include later-entered payments. Signed local amounts ALL.',
            'script': SCRIPT}
    return source, ledger, chat, thread, plan


def invoke(client, user, thread, tool, arguments):
    response = client.portal.call(client.app.state.manager.tool_call, user['id'],
        {'namespace': 'duka_reporting', 'threadId': thread, 'tool': tool, 'arguments': arguments})
    return json.loads(response['contentItems'][0]['text'])


def test_complete_input_decimal_arithmetic_and_model_rules_override_fixed_all_entry_cutoff(client, admin):
    _, ledger, chat, thread, plan = setup(client, admin)
    result = invoke(client, admin, thread, 'calculate_data', plan)
    assert 'error' not in result, result
    assert result['inputs'][0]['row_count'] == 604  # query limit=1 does not limit execution
    assert result['datasets'][0]['rows'] == [{'currency': 'ALL', 'balance': '49.98'}]
    assert result['datasets'][1]['result_rows'] == 601 and result['datasets'][1]['truncated']
    assert all('full_result_summary' not in d for d in result['datasets'])
    # Totals are the script's explicit dataset; the backend does not sum columns.
    assert client.app.state.db.all('SELECT * FROM reports') == []
    assert client.app.state.db.all('SELECT * FROM dataset_snapshots') == []
    strict = copy.deepcopy(plan)
    strict['script'] = SCRIPT.replace("row['kind'] == 'invoice' and date_of(row['entry'])", "date_of(row['entry'])")
    strict['rules'] = 'All transactions entered through Aug25; separate diagnostic calculation.'
    alternative = invoke(client, admin, thread, 'calculate_data', strict)
    assert alternative['datasets'][0]['rows'][0]['balance'] == '60.00'
    assert alternative['calculation_id'] != result['calculation_id']
    assert len(ledger.calls) == 2
    assert client.app.state.db.one('SELECT count(*) AS n FROM calculation_runs WHERE conversation_id=?', (chat,))['n'] == 2


def test_export_uses_exact_captured_outputs_does_not_requery_or_include_excluded_raw_inputs(client, admin):
    subscribe(client)
    _, ledger, chat, thread, plan = setup(client, admin)
    result = invoke(client, admin, thread, 'calculate_data', plan)
    ledger.rows[0]['amount'] = '999999'  # simulate changed live source
    created = invoke(client, admin, thread, 'create_calculation_report', {
        'calculation_id': result['calculation_id'], 'calculation_datasets': ['Balances', 'Eligible documents'],
        'title': 'Requested cutoff', 'instructions': 'Only captured eligible documents and balances.',
    })
    assert 'error' not in created, created
    report = wait_report(client, created['report_id'])
    assert report['status'] == 'completed', report
    assert len(ledger.calls) == 1
    data = client.get(f"/api/reports/{created['report_id']}/export/json").json()
    assert '_internal' not in json.dumps(data)
    assert 'excluded-late-invoice' not in json.dumps(data)
    response = client.get(f"/api/reports/{created['report_id']}/export/xlsx")
    workbook = openpyxl.load_workbook(io.BytesIO(response.content), data_only=True)
    values = [str(cell.value) for sheet in workbook for row in sheet for cell in row if cell.value is not None]
    assert 'later-payment' in values and 'excluded-loan' not in values and 'excluded-client' not in values
    assert any(Decimal(v) == Decimal('49.98') for v in values if v.replace('.', '', 1).replace('-', '', 1).isdigit())
    client.delete(f'/api/conversations/{chat}', headers=HEADERS)
    assert client.get(f"/api/reports/{created['report_id']}/export/xlsx").status_code == 200
    snapshot = client.app.state.db.one('SELECT provenance_json FROM dataset_snapshots WHERE id=?', (report['snapshot_id'],))
    assert 'excluded-loan' in snapshot['provenance_json']  # private reproducible audit survives chat deletion


def test_calculations_enforce_user_conversation_and_source_grants(client, admin):
    source, _, _, thread, plan = setup(client, admin)
    result = invoke(client, admin, thread, 'calculate_data', plan)
    other = client.post('/api/conversations', headers=HEADERS, json={}).json()['id']
    client.app.state.db.execute('UPDATE conversations SET provider_thread_id=? WHERE id=?', ('other', other))
    denied = invoke(client, admin, 'other', 'create_calculation_report', {
        'title': 'Other chat', 'instructions': '', 'calculation_id': result['calculation_id'], 'calculation_datasets': ['Balances']})
    assert 'not found' in denied['error']
    member = create_member(client)
    sign_in_member(client)
    assert 'error' in invoke(client, member, thread, 'calculate_data', plan)
    new = client.post('/api/conversations', headers=HEADERS, json={}).json()['id']
    client.app.state.db.execute('UPDATE conversations SET provider_thread_id=? WHERE id=?', ('member', new))
    assert 'error' in invoke(client, member, 'member', 'calculate_data', plan)
    client.app.state.db.execute('UPDATE data_sources SET enabled=0 WHERE id=?', (source['id'],))
    denied = invoke(client, admin, thread, 'create_calculation_report', {
        'title': 'Revoked', 'instructions': '', 'calculation_id': result['calculation_id'], 'calculation_datasets': ['Balances']})
    assert 'error' in denied


@pytest.mark.parametrize('script', [
    'import os\ndef calculate(tables):\n return os.environ',
    "def calculate(tables):\n return open('/etc/passwd').read()",
    'def calculate(tables):\n return tables.__class__',
    "def calculate(tables):\n return eval('1+1')",
    'def calculate(tables):\n return calculate(tables)',
    'def calculate(tables):\n number=1\n return number',
    'def calculate(tables):\n return 0.1 + 0.2',
])
def test_unsafe_or_inexact_script_is_rejected_before_querying(script):
    with pytest.raises(ValueError):
        validate_script(script)


def test_generic_helpers_handle_dates_nulls_duplicate_checks_rounding_and_precision():
    result = run_script("def calculate(tables):\n    require(date_of('20260825') == '2026-08-25')\n    require(date_of('00000000') is None)\n    return number('1234567890123456789.01') + number('0.02')", {})
    assert str(result) == '1234567890123456789.03'
    assert run_script("def calculate(tables):\n    return date_of('2026-08-25T23:30:00+02:00')", {}) == '2026-08-25'
    assert run_script("def calculate(tables):\n    return divide(1, 3, 2)", {}) == Decimal('.33')
    with pytest.raises(Exception):
        run_script("def calculate(tables):\n    return number(1) / number(3)", {})
    with pytest.raises(ValueError):
        run_script("def calculate(tables):\n    require(False)", {})
    with pytest.raises(ValueError):
        run_script("def calculate(tables):\n    return number(None)", {})


def test_input_truncation_size_limits_and_failed_calculation_never_save_partial_results(client, admin, monkeypatch):
    _, ledger, _, thread, plan = setup(client, admin)
    client.app.state.settings.report_max_rows = 603
    result = invoke(client, admin, thread, 'calculate_data', plan)
    assert 'limits' in result['error']
    assert client.app.state.db.all('SELECT * FROM calculation_runs') == []
    client.app.state.settings.report_max_rows = 10000
    plan['script'] = SCRIPT.replace("key not in seen", "False")
    assert 'error' in invoke(client, admin, thread, 'calculate_data', plan)
    assert client.app.state.db.all('SELECT * FROM calculation_runs') == []
    async def incomplete(query):
        return {'rows': ledger.rows[:1], 'columns': [], 'truncated': True}
    monkeypatch.setattr(ledger, 'report_query', incomplete)
    plan['script'] = SCRIPT
    assert 'incomplete' in invoke(client, admin, thread, 'calculate_data', plan)['error']


def test_upload_and_database_can_be_compared_in_one_calculation(client, admin):
    _, _, chat, thread, plan = setup(client, admin)
    uploaded = client.post(f'/api/conversations/{chat}/attachments', headers=HEADERS,
        files={'file': ('reference.csv', b'currency,balance\nALL,49.98\n', 'text/csv')})
    assert uploaded.status_code == 201, uploaded.text
    attachment = uploaded.json()
    plan['inputs'].append({'name': 'reference', 'kind': 'attachment', 'attachment_id': attachment['id'], 'table_id': attachment['tables'][0]['id']})
    plan['script'] = SCRIPT.replace("'balance': total}", "'balance': total - number(tables['reference'][0]['balance'])}")
    result = invoke(client, admin, thread, 'calculate_data', plan)
    assert 'error' not in result, result
    assert result['datasets'][0]['rows'][0]['balance'] == '0.00'
    assert [i['row_count'] for i in result['inputs']] == [604, 1]


class UnrelatedSchema(FixtureDatabase):
    """Different engines and field names; no SAP tables or accounting routine."""

    def __init__(self, settings, catalog, dialect, database, rows):
        super().__init__(replace(settings, hana_database=database, sqlserver_database=database), catalog)
        self.dialect, self.database, self.rows = dialect, database, rows

    async def in_database(self, database):
        assert database == self.database
        return self

    async def describe(self, schema, table):
        return {'columns': [{'name': k, 'type': 'nvarchar'} for k in self.rows[0]]}

    def _run_full(self, sql, parameters):
        self.calls.append((sql, parameters))
        assert ('[' in sql) == (self.dialect == 'sqlserver')
        assert ' TOP ' not in sql and ' LIMIT ' not in sql
        return copy.deepcopy(self.rows)


def test_model_code_combines_unrelated_sqlserver_and_hana_schemas_and_controls_all_rules(client, admin):
    _, _, _, thread, _ = setup(client, admin)
    state = client.app.state
    sql_rows = [{'posted_on': '2026-01-31', 'entered_at': '2026-01-31T10:00:00',
                 'debit': '0.10', 'credit': '0', 'unit': 'EUR', 'key': str(i)} for i in range(600)]
    sql_rows.append({**sql_rows[0], 'key': 'late-invoice', 'debit': '10', 'entered_at': '2026-02-01'})
    hana_rows = [
        {'documentDay': '20260131', 'recordDay': '20260201', 'signedValue': '-2.25', 'ccy': 'EUR', 'reference': 'late-credit'},
        {'documentDay': '20260130', 'recordDay': '20260131', 'signedValue': '5', 'ccy': 'USD', 'reference': 'other-currency'},
    ]
    inputs, databases = [], []
    for kind, name, database, schema, table, rows in (
        ('sqlserver', 'warehouse', 'FinanceArchive', 'custom', 'InvoiceEvents', sql_rows),
        ('hana', 'journal', 'TENANT_Z', 'BESPOKE', 'EntryHistory', hana_rows),
    ):
        source, _ = fixture_source(client)
        if kind == 'hana':
            state.db.execute("UPDATE data_sources SET kind='saphana' WHERE id=?", (source['id'],))
        connector = UnrelatedSchema(state.settings, state.connectors.catalog, kind, database, rows)
        state.connectors.register(source['id'], connector)
        databases.append(connector)
        inputs.append({'kind': 'database', 'name': name, 'source_id': source['id'], 'database': database,
            'query': {'tables': [{'schema': schema, 'name': table, 'alias': 'e'}],
                      'select': [{'column': 'e.' + key} for key in rows[0]], 'limit': 1}})
    script = """def calculate(tables):
    normalized = []
    for row in tables['warehouse']:
        normalized.append({'posting': date_of(row['posted_on']), 'entry': date_of(row['entered_at']),
                           'amount': number(row['debit']) - number(row['credit']),
                           'currency': row['unit'], 'key': 'warehouse:' + row['key']})
    for row in tables['journal']:
        normalized.append({'posting': date_of(row['documentDay']), 'entry': date_of(row['recordDay']),
                           'amount': number(row['signedValue']), 'currency': row['ccy'],
                           'key': 'journal:' + row['reference']})
    totals = {}
    seen = set()
    for row in normalized:
        require(row['key'] not in seen)
        seen.add(row['key'])
        if row['posting'] > '2026-01-31' or row['entry'] > '2026-01-31':
            continue
        unit = row['currency']
        totals[unit] = totals.get(unit, number('0')) + row['amount']
    return {'datasets': [{'name': 'Summary', 'columns': [{'name': 'currency', 'type': 'text'},
             {'name': 'net', 'type': 'decimal'}],
             'rows': [{'currency': unit, 'net': value} for unit, value in totals.items()]}],
             'notes': ['Rules are entirely in this model-authored script.']}
"""
    plan = {'inputs': inputs, 'rules': 'Both actual dates through January31; retain currencies separately.', 'script': script}
    strict = invoke(client, admin, thread, 'calculate_data', plan)
    assert 'error' not in strict, strict
    assert strict['datasets'][0]['rows'] == [{'currency': 'EUR', 'net': '60.00'}, {'currency': 'USD', 'net': '5'}]
    assert [x['row_count'] for x in strict['inputs']] == [601, 2]
    # The backend receives the same rows, but different model code chooses a
    # different rule. It must not impose the former cutoff or an SAP definition.
    plan['script'] = script.replace("row['entry'] > '2026-01-31'", "(row['entry'] > '2026-01-31' and row['amount'] >= number('0'))")
    plan['rules'] = 'Separate requested diagnostic: allow later-entered credits.'
    changed = invoke(client, admin, thread, 'calculate_data', plan)
    assert changed['datasets'][0]['rows'] == [{'currency': 'EUR', 'net': '57.75'}, {'currency': 'USD', 'net': '5'}]
    assert all(len(db.calls) == 2 for db in databases)
    assert state.db.all('SELECT * FROM reports') == []


async def test_claude_mcp_uses_the_same_complete_data_execution_and_export_catalog(client, admin, monkeypatch):
    import claude_agent_sdk as sdk
    _, _, _, thread, plan = setup(client, admin)
    captured = []
    def server(**kwargs):
        captured.extend(kwargs['tools'])
        return {'type': 'sdk', 'name': kwargs['name'], 'instance': None}
    monkeypatch.setattr(sdk, 'create_sdk_mcp_server', server)
    runtime = ClaudeRuntime(client.app.state.settings, admin['id'], client.app.state.manager.tool_call)
    runtime.tool_server(thread, 'fixture-turn')
    tools = {t.name: t for t in captured}
    assert {'calculate_data', 'create_calculation_report'} <= tools.keys()
    definition = next(t for t in REPORT_TOOLS[0]['tools'] if t['name'] == 'calculate_data')
    assert tools['calculate_data'].input_schema == definition['inputSchema']
    response = await tools['calculate_data'].handler(plan)
    assert response['isError'] is False
    result = json.loads(response['content'][0]['text'])
    assert result['datasets'][0]['rows'][0]['balance'] == '49.98'
    assert runtime.options().system_prompt == BASE_INSTRUCTIONS


def test_old_codex_catalog_can_calculate_and_export_without_changing_thread_identity(client, admin):
    subscribe(client)
    source, ledger, _, thread, plan = setup(client, admin)
    wrapper = {'source_id': source['id'], 'query': plan['inputs'][0]['query'], 'database': 'Fixture',
               'title': 'Calculation', 'template_id': 'executive', 'instructions': 'CALCULATE_DATA\n' + json.dumps(plan)}
    result = invoke(client, admin, thread, 'create_database_report', wrapper)
    assert result['datasets'][0]['rows'][0]['balance'] == '49.98'
    assert client.app.state.db.all('SELECT * FROM reports') == []
    wrapper['instructions'] = 'EXPORT_CALCULATION\n' + json.dumps({'calculation_id': result['calculation_id'], 'calculation_datasets': ['Balances']})
    exported = invoke(client, admin, thread, 'create_database_report', wrapper)
    assert wait_report(client, exported['report_id'])['status'] == 'completed'
    assert len(ledger.calls) == 1
    assert client.app.state.db.one('SELECT id FROM conversations WHERE provider_thread_id=?', (thread,))


def test_native_schemas_and_output_shapes_are_strict():
    for definition in REPORT_TOOLS[0]['tools']:
        Draft202012Validator.check_schema(definition['inputSchema'])
    assert 'supplies no accounting calculator' in BASE_INSTRUCTIONS
    assert {'calculate_balances', 'create_balance_report'}.isdisjoint(t['name'] for t in REPORT_TOOLS[0]['tools'])
    with pytest.raises(ValueError):
        validate_output({'datasets': [{'name': 'Bad', 'columns': [{'name': 'x', 'type': 'decimal'}], 'rows': [{'x': 'NaN'}]}], 'notes': []}, 100, 10000)
