import pytest

from conftest import HEADERS
from test_hana import trusted_test_ca


def connection_fixture(client, kind, origin):
    prefix = 'HANA' if kind == 'saphana' else 'SQLSERVER'
    values = {prefix+'_HOST':'fixture-host',prefix+'_PORT':30015 if kind=='saphana' else 1444,
              prefix+'_USER':'fixture-login',prefix+'_PASSWORD':'fixture-password',prefix+'_DATABASE':'fixture-database'}
    if kind == 'saphana':
        values.update(HANA_ENCRYPT=True,HANA_VALIDATE_CERTIFICATE=True,
                      HANA_TLS_CA_CERTIFICATE=trusted_test_ca(),HANA_TLS_SERVER_NAME='hana.fixture.internal')
    created = client.post('/api/admin/sources',headers=HEADERS,json={'name':'Fixture source','kind':kind,**values})
    assert created.status_code == 201,created.text
    source=created.json();state=client.app.state
    if origin == 'environment':
        path=state.settings.data_dir/'.env'
        with path.open('a') as file:
            for key,value in values.items():
                value=str(value).lower() if isinstance(value,bool) else str(value)
                file.write(key+"='"+value+"'\n")
        state.settings.env_file=path
        state.db.execute('UPDATE data_sources SET credential_profile=? WHERE id=?',(prefix,source['id']))
    return source,prefix,values


def settings(registry,identifier,prefix):
    effective=registry.source_settings(identifier)
    return {key:value for key,value in vars(effective).items() if key.startswith(prefix.lower()+'_')}


@pytest.mark.parametrize('kind',['sqlserver','saphana'])
@pytest.mark.parametrize('origin',['saved','environment'])
@pytest.mark.parametrize('field,value',[('HOST','changed-host'),('PORT',1544),('USER','changed-user'),('PASSWORD','changed-password'),('DATABASE','changed-database')])
def test_one_field_patch_keeps_every_other_connection_value(client,admin,kind,origin,field,value):
    source,prefix,values=connection_fixture(client,kind,origin)
    registry=client.app.state.connectors
    before=settings(registry,source['id'],prefix)
    # A partial API request may omit metadata too. Blanks in every other connection field mean retain.
    patch={key:'' for key in values if key not in ('HANA_ENCRYPT','HANA_VALIDATE_CERTIFICATE')}
    patch[prefix+'_'+field]=value
    response=client.patch('/api/admin/sources/'+source['id'],headers=HEADERS,json=patch)
    assert response.status_code==200,response.text
    expected={**before,prefix.lower()+'_'+field.lower():str(value) if field=='PORT' else value}
    assert settings(registry,source['id'],prefix)==expected
    for secret in ['fixture-password','fixture-login','changed-password','changed-user','changed-host']:
        assert secret not in response.text
    assert response.json()['name']=='Fixture source'


@pytest.mark.parametrize('kind',['sqlserver','saphana'])
@pytest.mark.parametrize('origin',['saved','environment'])
def test_blank_patch_is_noop_and_explicit_discovery_is_the_only_database_clear(client,admin,kind,origin):
    source,prefix,values=connection_fixture(client,kind,origin);state=client.app.state
    before=settings(state.connectors,source['id'],prefix)
    env=state.connectors.secrets.environment.path;content=env.read_bytes()
    response=client.patch('/api/admin/sources/'+source['id'],headers=HEADERS,json={key:'' for key in values if key not in ('HANA_ENCRYPT','HANA_VALIDATE_CERTIFICATE')})
    # Boolean controls are not blank text fields.
    assert response.status_code==200,response.text
    assert settings(state.connectors,source['id'],prefix)==before
    assert env.read_bytes()==content
    response=client.patch('/api/admin/sources/'+source['id'],headers=HEADERS,json={'discover_databases':True})
    assert response.status_code==200,response.text
    assert settings(state.connectors,source['id'],prefix)=={**before,prefix.lower()+'_database':''}


def test_hana_tls_false_is_an_explicit_update_not_a_blank_value(client,admin):
    source,prefix,_=connection_fixture(client,'saphana','environment');registry=client.app.state.connectors
    before=settings(registry,source['id'],prefix)
    response=client.patch('/api/admin/sources/'+source['id'],headers=HEADERS,json={'HANA_VALIDATE_CERTIFICATE':False,'HANA_TLS_CA_CERTIFICATE':'','HANA_TLS_SERVER_NAME':''})
    assert response.status_code==200,response.text
    assert settings(registry,source['id'],prefix)=={**before,'hana_validate_certificate':False}


def test_incomplete_existing_source_cannot_borrow_another_sources_credentials(client,admin):
    connection_fixture(client,'sqlserver','environment')
    created=client.post('/api/admin/sources',headers=HEADERS,json={'name':'Empty source','kind':'sqlserver'}).json()
    response=client.patch('/api/admin/sources/'+created['id'],headers=HEADERS,json={'SQLSERVER_HOST':'one-field-only'})
    assert response.status_code==422
    assert 'fixture-password' not in response.text
    assert client.app.state.db.one('SELECT credential_profile FROM data_sources WHERE id=?',(created['id'],))['credential_profile']=='saved'


def test_unknown_blank_connection_fields_are_not_silently_accepted(client,admin):
    source,_,_=connection_fixture(client,'sqlserver','saved')
    response=client.patch('/api/admin/sources/'+source['id'],headers=HEADERS,json={'SQLSERVER_MISSPELLED_FIELD':''})
    assert response.status_code==422
