from dataclasses import replace
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from app.config import Settings
from app.connection_diagnostics import network_check, profile_settings, check_login
from app.env_store import prefix_for
from conftest import HEADERS


def settings(**kwargs):
    return Settings(
        env_file=None,
        sqlserver_host="private-sql",
        sqlserver_user="private-login",
        sqlserver_password="private-password",
        hana_host="private-hana",
        hana_user="private-login",
        hana_password="private-password",
        **kwargs,
    )


def test_hana_policy_is_checked_before_any_network_or_login(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("No network before policy check"))
    for field in ("hana_encrypt", "hana_validate_certificate"):
        result = network_check(replace(settings(), **{field: False}), "saphana")
        assert result["stage"] == "policy" and "Enable both" in result["message"]


def test_dns_tcp_success_and_timeout_do_not_expose_settings(monkeypatch):
    def bad_dns(*args, **kwargs):
        raise socket.gaierror("private-host private-password")

    monkeypatch.setattr(socket, "getaddrinfo", bad_dns)
    assert network_check(settings(), "sqlserver")["stage"] == "dns"
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 1433))]
    )

    class Socket:
        error = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, timeout):
            assert timeout == 3

        def connect(self, address):
            if self.error:
                raise TimeoutError("private-password")

    monkeypatch.setattr(socket, "socket", lambda *args: Socket())
    assert network_check(settings(), "sqlserver")["status"] == "ok"
    Socket.error = True
    result = network_check(settings(), "sqlserver")
    assert result["stage"] == "tcp" and result["status"] == "error"
    assert "private-" not in str(result)


def test_saved_hana_profile_preserves_false_values_and_does_not_borrow_generic_credentials():
    source = {"id": "fixture-source", "kind": "saphana", "credential_profile": "saved"}
    prefix = prefix_for(source["id"])
    values = {
        prefix + "PRESENT": "true",
        prefix + "HANA_ENCRYPT": "false",
        prefix + "HANA_VALIDATE_CERTIFICATE": "false",
        prefix + "HANA_HOST": "saved-private-host",
    }
    configured = profile_settings(settings(), source, values, {"ciphertext": "env"})
    assert configured.hana_encrypt is False and configured.hana_validate_certificate is False
    assert configured.hana_host == "saved-private-host" and not configured.hana_user
    with pytest.raises(ValueError, match="missing"):
        profile_settings(settings(), source, {}, {"ciphertext": "env"})


async def test_login_check_reports_production_policy_without_raw_driver_errors():
    result = await check_login(settings(production=True, hana_encrypt=False), "saphana")
    assert result["status"] == "error" and "Production HANA" in result["message"]
    assert "private-" not in str(result)


def test_native_diagnostic_command_reads_profiles_without_changing_grants_or_credentials(client, admin):
    source = client.post(
        "/api/admin/sources",
        headers=HEADERS,
        json={
            "name": "HANA fixture",
            "kind": "saphana",
            "HANA_HOST": "private-hana",
            "HANA_PORT": 30015,
            "HANA_USER": "private-login",
            "HANA_PASSWORD": "private-password",
            "HANA_ENCRYPT": False,
            "HANA_VALIDATE_CERTIFICATE": False,
        },
    ).json()
    db = client.app.state.db
    tables = ("users", "source_credentials", "source_grants", "data_sources")
    before = {table: db.all("SELECT * FROM " + table) for table in tables}
    settings = client.app.state.settings
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "deploy/diagnose-connections.py"), "--source-id", source["id"]],
        env={**os.environ, "ENV_FILE": str(settings.data_dir / ".env"), "DATA_DIR": str(settings.data_dir)},
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["sources"][0]["checks"][0]["stage"] == "policy"
    assert "private-" not in result.stdout and "private-" not in result.stderr
    assert before == {table: db.all("SELECT * FROM " + table) for table in tables}
