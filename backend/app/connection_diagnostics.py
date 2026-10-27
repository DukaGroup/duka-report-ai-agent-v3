"""Source-scoped connection checks; never return passwords or raw driver errors."""

from dataclasses import replace
import socket

from .connectors import QueryCatalog, SQLServerConnector, SourceNotConfigured
from .env_store import prefix_for
from .hana import HanaConnector


def profile_settings(settings, source, values, saved):
    profile = source["credential_profile"]
    base = replace(
        settings,
        sqlserver_host="",
        sqlserver_user="",
        sqlserver_password="",
        sqlserver_database="",
        sqlserver_port="1433",
        hana_host="",
        hana_user="",
        hana_password="",
        hana_database="",
        hana_port="30015",
        hana_encrypt=True,
        hana_validate_certificate=True,
        hana_tls_ca_certificate="",
        hana_tls_server_name="",
    )
    if profile == "legacy":
        raise ValueError("Start the upgraded backend to complete profile migration first.")
    if profile == "saved":
        prefix = prefix_for(source["id"])
        if not saved or saved["ciphertext"] != "env" or values.get(prefix + "PRESENT") != "true":
            raise ValueError(
                "The saved connection profile is missing. Configure this source in Hana or restore runtime.env."
            )
        updates = {
            key[len(prefix) :].lower(): value or ""
            for key, value in values.items()
            if key.startswith(prefix) and key != prefix + "PRESENT"
        }
        for key in ("hana_encrypt", "hana_validate_certificate"):
            if key in updates:
                if updates[key] not in ("true", "false"):
                    raise ValueError("Invalid HANA TLS option.")
                updates[key] = updates[key] == "true"
        if "sqlserver_timeout" in updates:
            updates["sqlserver_timeout"] = int(updates["sqlserver_timeout"])
        return replace(base, **updates)
    configured = base.hana_environment() if source["kind"] == "saphana" else base.database_environment(profile)
    if configured is None:
        raise ValueError("The environment profile is missing from runtime.env.")
    return configured


def network_check(settings, kind):
    prefix = "hana_" if kind == "saphana" else "sqlserver_"
    missing = [name for name in ("host", "port", "user", "password") if not getattr(settings, prefix + name)]
    if missing:
        return {"stage": "configuration", "status": "error", "message": "Missing fields: " + ", ".join(missing)}
    if kind == "saphana" and (not settings.hana_encrypt or not settings.hana_validate_certificate):
        return {
            "stage": "policy",
            "status": "error",
            "message": "Enable both HANA encryption and certificate validation in this saved source profile.",
        }
    if kind == "sqlserver" and settings.sqlserver_encryption != "require":
        return {"stage": "policy", "status": "error", "message": "Set SQLSERVER_ENCRYPTION=require."}
    host = getattr(settings, prefix + "host")
    try:
        port = int(getattr(settings, prefix + "port"))
        if not 1 <= port <= 65535:
            raise ValueError()
    except (TypeError, ValueError):
        return {"stage": "configuration", "status": "error", "message": "The SQL port must be 1–65535."}
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return {
            "stage": "dns",
            "status": "error",
            "message": "The server cannot resolve the database hostname. Check company DNS/VPN.",
        }
    errors = []
    # Bound work across multihomed hosts; no arbitrary URL, shell command or query.
    for family, socktype, protocol, _, address in addresses[:3]:
        try:
            with socket.socket(family, socktype, protocol) as connection:
                connection.settimeout(3)
                connection.connect(address)
            return {
                "stage": "tcp",
                "status": "ok",
                "message": "The database TCP endpoint is reachable. TLS/login remain separate checks.",
            }
        except OSError as error:
            errors.append(error.errno)
    return {
        "stage": "tcp",
        "status": "error",
        "message": "Database TCP connection failed. Check this server’s VPN/route, database listener and firewall source-IP rule.",
        "socket_error_codes": errors,
    }


async def check_login(settings, kind):
    connector = (HanaConnector if kind == "saphana" else SQLServerConnector)(
        replace(settings, sqlserver_timeout=5), QueryCatalog(settings.query_dir)
    )
    try:
        await connector.check()
        return {"stage": "database", "status": "ok", "message": "TLS/login and connection check succeeded."}
    except SourceNotConfigured as error:
        return {
            "stage": "database",
            "status": "error",
            "message": str(error),
            "database_error_code": getattr(error, "code", None),
        }
