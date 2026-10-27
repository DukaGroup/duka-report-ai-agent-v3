import configparser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os
from pathlib import Path
import socket
import threading

import pytest

from app.config import Settings
from app.connectors import DatabaseUnavailable, SQLServerConnector, safe_database_error
from app.database_tls import options, warnings
from app.hana import HanaConnector, hana_error
from app.sqlserver_tls import connection_options
from conftest import HEADERS
from test_hana import HanaDriver, trusted_test_ca
from test_sqlserver import Driver


def configured(tmp_path, **changes):
    return Settings(data_dir=tmp_path, env_file=None, production=True,
                    hana_host="database.fixture.internal", hana_user="fixture", hana_password="private-password",
                    sqlserver_host="database.fixture.internal", sqlserver_user="fixture",
                    sqlserver_password="private-password", **changes)


@pytest.mark.parametrize("kind", ["saphana", "sqlserver"])
def test_default_allows_tls_without_ca_or_server_validation(tmp_path, kind):
    settings = configured(tmp_path)
    assert options(settings, kind) == {"encryption": "require", "encrypt": True,
        "validate_certificate": False, "custom_ca": False, "server_name_configured": False}
    assert "identity is not verified" in warnings(settings, kind)[0]


@pytest.mark.parametrize("kind", ["saphana", "sqlserver"])
async def test_supplied_ca_forces_verified_tls_even_when_controls_disable_it(tmp_path, kind):
    prefix = "hana_" if kind == "saphana" else "sqlserver_"
    settings = configured(tmp_path, **{prefix + "tls_ca_certificate": trusted_test_ca(),
        prefix + "validate_certificate": False, prefix + "tls_server_name": "database.fixture.internal",
        **({"hana_encrypt": False} if kind == "saphana" else {"sqlserver_encryption": "off"})})
    driver = HanaDriver() if kind == "saphana" else Driver([{"name": "Fixture", "is_default": 0}])
    connector = (HanaConnector if kind == "saphana" else SQLServerConnector)(settings, None, driver)
    await connector.check()
    tls = options(settings, kind)
    assert tls["validate_certificate"] and tls["encryption"] == "require"
    assert warnings(settings, kind) == []
    if kind == "saphana":
        assert driver.connections[-1]["sslValidateCertificate"] is True
        assert driver.connections[-1]["encrypt"] is True
        ca_path = driver.connections[-1]["sslTrustStore"]
    else:
        parser = configparser.ConfigParser()
        parser.read(os.environ["FREETDSCONF"])
        section = parser[driver.options["server"]]
        assert section["encryption"] == "require" and section["check certificate hostname"] == "yes"
        assert section["certificate hostname"] == "database.fixture.internal"
        ca_path = section["ca file"]
    assert Path(ca_path).stat().st_mode & 0o777 == 0o600
    assert getattr(settings, prefix + "tls_ca_certificate") in Path(ca_path).read_text()


@pytest.mark.parametrize("kind", ["saphana", "sqlserver"])
async def test_failed_verification_is_not_retried_with_weaker_settings(tmp_path, kind):
    prefix = "hana_" if kind == "saphana" else "sqlserver_"
    settings = configured(tmp_path, **{prefix + "validate_certificate": True})
    class FailingDriver:
        calls = 0
        def connect(self, **kwargs):
            self.calls += 1
            raise RuntimeError("certificate verify failed private-password")
    driver = FailingDriver()
    connector = (HanaConnector if kind == "saphana" else SQLServerConnector)(settings, None, driver)
    with pytest.raises(DatabaseUnavailable, match="certificate verification failed") as failure:
        await connector.check()
    assert driver.calls == 1 and "private-" not in str(failure.value)


def test_parallel_sql_sources_have_immutable_separate_aliases_and_trust(tmp_path, monkeypatch):
    monkeypatch.delenv("FREETDS", raising=False)
    monkeypatch.delenv("FREETDSCONF", raising=False)
    settings = configured(tmp_path)
    strict = replace(settings, sqlserver_validate_certificate=True)
    barrier = threading.Barrier(2)
    def resolve(settings):
        with connection_options(settings, options(settings, "sqlserver")) as alias:
            barrier.wait(timeout=5)
            parser = configparser.ConfigParser()
            parser.read(os.environ["FREETDSCONF"])
            return alias, dict(parser[alias])
    with ThreadPoolExecutor(2) as executor:
        first = executor.submit(resolve, settings)
        second = executor.submit(resolve, strict)
        unverified, verified = first.result(), second.result()
    assert unverified[0] != verified[0]
    assert unverified[1]["ca file"] == "" and unverified[1]["check certificate hostname"] == "no"
    assert verified[1]["ca file"] and verified[1]["check certificate hostname"] == "yes"
    assert (tmp_path / "tls/freetds.conf").stat().st_mode & 0o777 == 0o600
    assert "private-password" not in (tmp_path / "tls/freetds.conf").read_text()


@pytest.mark.parametrize("host", ["db\nca file = evil", "db;dump file=evil", "db/path", "https://db"])
def test_sql_alias_rejects_configuration_injection_before_driver(tmp_path, host):
    settings = configured(tmp_path, sqlserver_tls_server_name=host)
    driver = Driver()
    with pytest.raises(Exception, match="TLS configuration is invalid"):
        SQLServerConnector(settings, None, driver)._connect()
    assert driver.options is None


@pytest.mark.parametrize("kind", ["saphana", "sqlserver"])
def test_form_and_saved_profiles_keep_source_scoped_certificate_choices(client, admin, kind):
    prefix = "HANA" if kind == "saphana" else "SQLSERVER"
    ca = trusted_test_ca()
    payload = {"name": "Fixture", "kind": kind, prefix + "_HOST": "db.fixture.internal",
               prefix + "_USER": "fixture", prefix + "_PASSWORD": "private-password",
               prefix + "_VALIDATE_CERTIFICATE": False, prefix + "_TLS_CA_CERTIFICATE": ca}
    response = client.post("/api/admin/sources", json=payload, headers=HEADERS)
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["tls"]["validate_certificate"] and source["tls"]["custom_ca"]
    assert ca not in response.text and "private-password" not in response.text
    stored = client.app.state.connectors.secrets.load(source["id"])
    assert stored[prefix + "_VALIDATE_CERTIFICATE"] == "false"
    assert stored[prefix + "_TLS_CA_CERTIFICATE"] == ca
    for value in ("not a cert", "-----BEGIN PRIVATE KEY-----\nprivate"):
        assert client.patch("/api/admin/sources/" + source["id"],
            json={prefix + "_TLS_CA_CERTIFICATE": value}, headers=HEADERS).status_code == 422


def test_sql_environment_tls_options_are_read_from_the_exact_named_profile(tmp_path):
    path = tmp_path / "runtime.env"
    path.write_text("SQLSERVER_HOST=other\nSQLSERVER_VALIDATE_CERTIFICATE=true\n"
        "TEAM_SQLSERVER_HOST=fixture\nTEAM_SQLSERVER_ENCRYPTION=request\nTEAM_SQLSERVER_VALIDATE_CERTIFICATE=false\n")
    settings = Settings(env_file=path)
    generic = settings.database_environment()
    named = settings.database_environment("TEAM_SQLSERVER")
    assert generic.sqlserver_validate_certificate is True
    assert named.sqlserver_host == "fixture" and named.sqlserver_encryption == "request"
    assert named.sqlserver_validate_certificate is False and not named.sqlserver_user


@pytest.mark.parametrize("error", [safe_database_error, hana_error])
@pytest.mark.parametrize("message,expected", [
    ("TLS is required private-password", "requires TLS encryption"),
    ("server requires SSL private-password", "requires TLS encryption"),
    ("tlsv13 alert certificate required private-password", "requires a client certificate"),
    ("CERTIFICATE_VERIFY_FAILED private-password", "certificate verification failed"),
    ("client certificate is required private-password", "requires a client certificate"),
    ("certificate verify failed private-password", "certificate verification failed"),
    ("certificate expired private-password", "certificate has expired"),
    ("certificate hostname mismatch private-password", "certificate hostname mismatch"),
    ("SSL handshake failed private-password", "TLS negotiation failed"),
])
def test_endpoint_errors_are_actionable_without_disclosing_driver_details(error, message, expected):
    result = error(RuntimeError(message))
    assert expected in result and "private-" not in result


def test_real_freetds_reads_generated_alias_and_reaches_only_local_fixture(tmp_path, monkeypatch):
    """A real native driver must resolve our alias, rather than DNS-resolve it."""
    pymssql = pytest.importorskip("pymssql")
    monkeypatch.delenv("TDSDUMP", raising=False)
    monkeypatch.delenv("TDSDUMPCONFIG", raising=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(5)
        received = []
        def serve():
            with listener.accept()[0] as peer:
                peer.settimeout(3)
                received.append(peer.recv(4096))
        settings = replace(configured(tmp_path), sqlserver_host="127.0.0.1",
                           sqlserver_port=str(listener.getsockname()[1]), sqlserver_timeout=2)
        with ThreadPoolExecutor(1) as executor:
            server = executor.submit(serve)
            with pytest.raises(pymssql.Error):
                SQLServerConnector(settings, None)._connect()
            server.result(timeout=6)
        # PRELOGIN (0x12) reaches the fixture's host/ephemeral SQL port.
        assert received and received[0][0] == 0x12
