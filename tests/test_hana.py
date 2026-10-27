from decimal import Decimal
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os

import pytest

from app.config import Settings
from app.database_tools import DatabaseQuery, compile_select
from app.hana import HanaConnector
from app.connectors import DatabaseUnavailable, QueryCatalog, SourceNotConfigured
from conftest import HEADERS
from test_database_chat import DESCRIPTIONS, query_plan, call_tool
from test_excel_reports import subscribe, wait_report
from test_server_connections import connection


def trusted_test_ca():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'HANA fixture CA')])
    now = datetime.now(timezone.utc)
    return x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=1)).not_valid_after(now+timedelta(days=30)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).sign(key,hashes.SHA256()).public_bytes(serialization.Encoding.PEM).decode()


class HanaDriver:
    def __init__(self, tenant_catalog=True, error=None):
        self.connections, self.statements = [], []
        self.tenant_catalog, self.error = tenant_catalog, error

    def connect(self, **options):
        self.connections.append(options)
        if self.error:
            raise RuntimeError(*self.error)
        return HanaSession(self, options)


class HanaSession:
    def __init__(self, driver, options):
        self.driver, self.options = driver, options
        self.closed = self.rolled_back = False
        self.rows = []

    def cursor(self):
        return self

    def execute(self, sql, parameters):
        self.driver.statements.append((sql,parameters,self.options))
        if 'SYS.M_DATABASE' in sql:
            columns, rows = ['name'], [(self.options.get('databaseName','TENANT_A'),)]
        elif 'SYS_DATABASES.M_DATABASES' in sql:
            if not self.driver.tenant_catalog:
                raise RuntimeError(258,'insufficient privilege private-host private-password')
            columns, rows = ['name'], [('TENANT_A',),('TENANT_B',)]
        elif 'SYS.TABLE_COLUMNS' in sql:
            columns = ['name','type','nullable','precision','scale']
            rows = [('Id','INTEGER','FALSE',10,0),('Amount','DECIMAL','TRUE',19,2),('Date','DATE','FALSE',None,None)]
        elif 'SYS.REFERENTIAL_CONSTRAINTS' in sql:
            columns, rows = ['column_name','referenced_schema','referenced_table','referenced_column','relationship'],[]
        elif 'AS "table_count"' in sql:
            columns, rows = ['schema_name','table_count','view_count'], [('COMPANY_A',160000,12),('COMPANY_B',100,4)]
        elif 'SYS.TABLES' in sql:
            columns, rows = ['schema_name','name','kind'], [('COMPANY_A','Sales','BASE TABLE'),('COMPANY_B','Sales','BASE TABLE')]
        else:
            columns, rows = ['revenue'], [(Decimal('123.45'),)]
        self.description = [(name,) for name in columns]
        self.rows = rows

    def fetchmany(self, size):
        result,self.rows = self.rows[:size],self.rows[size:]
        return result

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def hana(driver):
    settings = Settings(env_file=None, hana_host='private-host',hana_user='private-user',hana_password='private-password',hana_validate_certificate=True)
    return HanaConnector(settings, QueryCatalog(settings.query_dir), driver)


def test_hana_dialect_quotes_identifiers_binds_values_and_preserves_full_export():
    query = DatabaseQuery.model_validate(query_plan(filters=[{'column':'s.Id','operator':'in','values':[1,2]}],limit=5))
    sql, params, columns = compile_select(query,DESCRIPTIONS,dialect='hana')
    assert 'SUM("s"."Amount") AS "revenue"' in sql and 'LIMIT 6' in sql
    assert 'IN (?, ?)' in sql and list(params.values()) == [1,2]
    full,_,_ = compile_select(query,DESCRIPTIONS,dialect='hana',complete=True)
    assert 'LIMIT' not in full and 'TOP (' not in full
    month = DatabaseQuery.model_validate(query_plan(select=[{'column':'s.Date','alias':'Month','bucket':'month'}],group_by=['Month']))
    assert 'TO_NVARCHAR' in compile_select(month,DESCRIPTIONS,dialect='hana')[0]
    assert columns == [{'name':'revenue','type':'decimal'}]


async def test_hana_driver_uses_hana_options_and_discovers_all_tenants_and_schemas():
    driver = HanaDriver()
    database = hana(driver)
    result = await database.databases()
    assert [d['name'] for d in result['databases']] == ['TENANT_A','TENANT_B']
    selected = await database.in_database('TENANT_B')
    tables = await selected.tables()
    assert {t['schema_name'] for t in tables['tables']} == {'COMPANY_A','COMPANY_B'}
    result = await selected.report_query(query_plan(tables=[{'schema':'COMPANY_A','name':'Sales','alias':'s'}],filters=[{'column':'s.Id','operator':'eq','value':"x'; DROP TABLE Sales; --"}]))
    assert result['rows'] == [{'revenue':'123.45'}] and not result['truncated']
    sql,params,_ = driver.statements[-1]
    assert "DROP TABLE" not in sql and params == ("x'; DROP TABLE Sales; --",)
    options = driver.connections[-1]
    assert options['databaseName']=='TENANT_B' and options['port']==30015
    assert options['autocommit'] is False and options['encrypt'] is True and options['sslValidateCertificate'] is True
    assert 'server' not in options and 'tds_version' not in options
    assert options['sslCryptoProvider'] == 'openssl' and os.path.isfile(options['sslTrustStore'])


async def test_hana_sales_discovery_filters_in_database_and_keeps_every_matching_company_page(monkeypatch):
    database = hana(HanaDriver())
    roles = ['OINV','INV1','ORIN','RIN1']
    matches = [{'schema_name':f'COMPANY_{i:03d}','name':name} for i in range(51) for name in roles]
    queries = []
    def lookup(sql, params):
        queries.append((sql,params))
        assert 'WHERE TABLE_NAME IN (?,?,?,?)' in sql
        assert list(params.values())[:4] == roles
        rows = [r for r in matches if 'company' not in params or r['schema_name']==params['company']]
        return rows[params['offset']:params['offset']+params['size']]
    async def describe(schema, table):
        return {'columns':[{'name':'DocEntry','type':'int'}]}
    async def no_full_catalog(**kwargs):
        raise AssertionError('Sales discovery must not page through unrelated tables.')
    monkeypatch.setattr(database,'_run',lookup)
    monkeypatch.setattr(database,'tables',no_full_catalog)
    monkeypatch.setattr(database,'describe',describe)
    result = await database.sales_catalog()
    assert len(result['companies']) == 51 and all(len(c['tables']) == 4 for c in result['companies'])
    assert len(queries) == 2 and queries[1][1]['offset'] == 200
    assert all(t['columns']==[{'name':'DocEntry','type':'int'}] for c in result['companies'] for t in c['tables'].values())
    result = await database.sales_catalog(company='COMPANY_050')
    assert [c['company'] for c in result['companies']] == ['COMPANY_050']
    assert 'COMPANY_050' not in queries[-1][0] and queries[-1][1]['company']=='COMPANY_050'
    queries.clear()
    result = await database.sales_catalog(company="unmatched'; DROP TABLE Sales; --")
    assert result['companies'] == [] and len(queries) == 1
    assert 'DROP TABLE' not in queries[0][0]


def test_hana_schema_overview_and_scoped_table_search_are_authorized_bound_metadata_tools(client, admin):
    source=client.post('/api/admin/sources',headers=HEADERS,json=hana_input()).json()
    database=client.app.state.connectors.resolve_connector(source['id'])
    driver=HanaDriver()
    database.driver=driver
    result=call_tool(client,admin,'list_schemas',{'source_id':source['id'],'database':'TENANT_B','limit':1})
    assert result['schemas']==[{'schema_name':'COMPANY_A','table_count':160000,'view_count':12}]
    assert result['next_offset']==1 and result['database']=='TENANT_B'
    attack="COMPANY_A'; DROP TABLE Sales; --"
    call_tool(client,admin,'list_tables',{'source_id':source['id'],'database':'TENANT_B','schema':attack,'name_contains':'Sales'})
    sql,params,_=driver.statements[-1]
    assert 'DROP TABLE' not in sql and params==('Sales',attack,101,0)
    from test_application import create_member
    member=create_member(client)
    before=len(driver.statements)
    denied=call_tool(client,member,'list_schemas',{'source_id':source['id'],'database':'TENANT_B'})
    assert 'error' in denied and len(driver.statements)==before


async def test_hana_trusted_custom_ca_is_materialized_privately_with_verification_enabled(tmp_path):
    from app.hana_tls import trust_store
    driver = HanaDriver()
    database = hana(driver)
    certificate = trusted_test_ca()
    database.settings = replace(database.settings, data_dir=tmp_path, hana_tls_ca_certificate=certificate, hana_tls_server_name='hana.fixture.internal')
    await database.check()
    options = driver.connections[-1]
    assert options['encrypt'] and options['sslValidateCertificate']
    assert options['sslHostNameInCertificate'] == 'hana.fixture.internal'
    from pathlib import Path
    path = Path(options['sslTrustStore'])
    assert path.parent == tmp_path/'tls' and path.stat().st_mode & 0o777 == 0o600
    assert certificate in path.read_text()
    assert trust_store(database.settings) == str(path)
    assert not list(path.parent.glob('tmp*'))


def test_hana_ca_and_identity_survive_env_storage_and_are_not_returned_to_browser(client, admin):
    certificate = trusted_test_ca()
    response = client.post('/api/admin/sources',headers=HEADERS,json=hana_input(HANA_TLS_CA_CERTIFICATE=certificate,HANA_TLS_SERVER_NAME='hana.fixture.internal'))
    assert response.status_code == 201, response.text
    source = response.json()
    assert source['tls']['custom_ca'] and source['tls']['server_name_configured']
    assert 'BEGIN CERTIFICATE' not in response.text and 'hana.fixture.internal' not in response.text
    registry = client.app.state.connectors
    before = registry.resolve_connector(source['id'])
    stored = registry.secrets.load(source['id'])
    assert stored['HANA_TLS_CA_CERTIFICATE'] == certificate
    assert before.settings.hana_tls_server_name == 'hana.fixture.internal'
    replacement = trusted_test_ca()
    registry.secrets.encrypt(source['id'],{**stored,'HANA_TLS_CA_CERTIFICATE':replacement})
    after = registry.resolve_connector(source['id'])
    assert after is not before and after.settings.hana_tls_ca_certificate == replacement


def test_hana_rejects_invalid_ca_private_keys_and_invalid_server_names_without_echoing_inputs(client, admin):
    for fields in ({'HANA_TLS_CA_CERTIFICATE':'-----BEGIN PRIVATE KEY-----\nprivate-material'}, {'HANA_TLS_CA_CERTIFICATE':'not-a-certificate'}, {'HANA_TLS_SERVER_NAME':'https://hana.fixture.internal:443/path'}):
        response = client.post('/api/admin/sources',headers=HEADERS,json=hana_input(**fields))
        assert response.status_code == 422
        assert 'private-material' not in response.text and 'private-password' not in response.text
        assert 'https://' not in response.text


async def test_hana_tenant_only_endpoint_discloses_catalog_limit_and_cloud_does_not_send_database_name():
    driver = HanaDriver(tenant_catalog=False)
    database = hana(driver)
    database.settings = replace(database.settings,hana_port='443')
    result = await database.databases()
    assert [d['name'] for d in result['databases']]==['TENANT_A'] and result['warnings']
    assert not result['catalog_complete']
    selected = await database.in_database('TENANT_A')
    await selected.check()
    assert all('databaseName' not in options for options in driver.connections)


async def test_hana_errors_are_specific_and_never_return_credentials():
    for code,text,expected in [(10,'authentication failed private-password','authentication failed'),(-10709,'TLS certificate private-password','TLS'),(258,'insufficient privilege private-password','denied access')]:
        with pytest.raises(DatabaseUnavailable) as failure:
            await hana(HanaDriver(error=(code,text))).check()
        assert expected in str(failure.value) and 'private-' not in str(failure.value)


async def test_hana_cloud_rejects_configured_tenant_mismatch_instead_of_mislabeling_results():
    database = hana(HanaDriver())
    database.settings = replace(database.settings, hana_port='443', hana_database='TENANT_B')
    with pytest.raises(SourceNotConfigured, match='did not select the requested tenant'):
        await database.check()


def hana_input(**changes):
    return {'name':'HANA','kind':'saphana','HANA_HOST':'private-host','HANA_PORT':30015,'HANA_USER':'private-user','HANA_PASSWORD':'private-password', **changes}


def test_hana_connection_api_env_storage_discovery_and_excel_use_the_correct_engine(client,admin):
    subscribe(client)
    response = client.post('/api/admin/sources',headers=HEADERS,json=hana_input())
    assert response.status_code==201,response.text
    source = response.json()
    assert source['database_scope']=='all' and source['connection_fields']['HANA_HOST']
    assert 'private-' not in response.text
    database = client.app.state.connectors.resolve_connector(source['id'])
    assert isinstance(database,HanaConnector)
    database.driver=HanaDriver()
    assert len(call_tool(client,admin,'discover_databases',{})['sources'][0]['databases'])==2
    request={'title':'HANA sales','source_id':source['id'],'database':'TENANT_B','query':query_plan(tables=[{'schema':'COMPANY_A','name':'Sales','alias':'s'}])}
    report=client.post('/api/reports',headers=HEADERS,json=request).json()
    assert wait_report(client,report['id'])['status']=='completed'
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code==200
    env=client.app.state.connectors.secrets.environment.path.read_text()
    assert source['env_prefix']+'HANA_PASSWORD=' in env and 'private-password' in env
    database.driver.tenant_catalog = False
    inventory = call_tool(client,admin,'discover_databases',{})
    assert not inventory['catalog_complete'] and inventory['sources'][0]['warnings']


def test_existing_wrong_sqlserver_type_can_switch_to_hana_without_resubmitting_secrets(client,admin):
    source=client.post('/api/admin/sources',headers=HEADERS,json=connection()).json()
    path='/api/admin/sources/'+source['id']
    assert client.patch(path,headers=HEADERS,json={'name':source['name'],'kind':'saphana'}).status_code==422
    response=client.patch(path,headers=HEADERS,json={'name':source['name'],'kind':'saphana','HANA_PORT':30015})
    assert response.status_code==200,response.text
    assert response.json()['kind']=='saphana' and response.json()['database_scope']=='all'
    database=client.app.state.connectors.resolve_connector(source['id'])
    assert isinstance(database,HanaConnector) and database.settings.hana_password=='private#test-password'
    assert database.settings.hana_host=='Finance server.internal'
    assert not database.settings.sqlserver_password


def test_malformed_hana_environment_is_shown_as_a_safe_source_error(client, admin, tmp_path):
    path = tmp_path / '.env'
    path.write_text('HANA_HOST=fixture\nHANA_USER=fixture\nHANA_PASSWORD=private-password\nHANA_ENCRYPT=invalid\n')
    client.app.state.settings.env_file = path
    response = client.post('/api/admin/sources', headers=HEADERS, json={'name':'HANA environment','kind':'saphana'})
    assert response.status_code == 201, response.text
    assert response.json()['status'] == 'error'
    assert '.env configuration could not be read' in response.json()['last_error']
    assert 'private-password' not in response.text
    listed = client.get('/api/admin/sources')
    assert listed.status_code == 200 and listed.json()[0]['status'] == 'error'
