"""Immutable per-connection FreeTDS aliases, without sharing trust between sources."""

from contextlib import contextmanager
import configparser
import fcntl
import hashlib
import io
import json
import os
import re
import tempfile
import threading

from .hana_tls import trust_store


_condition = threading.Condition()
_active_path = None
_active_count = 0


@contextmanager
def connection_options(settings, tls):
    """Keep FreeTDS' process-wide config stable during concurrent DB logins.

    A normal server has one DATA_DIR: its logins remain concurrent. Separate
    app instances in one process wait until the other config is no longer read.
    Alias sections are content-addressed, retained and atomically published.
    """
    global _active_path, _active_count
    host = settings.sqlserver_host
    identity = settings.sqlserver_tls_server_name or host
    if any(not re.fullmatch(r"[A-Za-z0-9_.:\-]+", value) for value in (host, identity)):
        raise ValueError("Use a database DNS name or IP address without a scheme, port suffix or path.")
    directory = settings.data_dir / "tls"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / "freetds.conf"
    path_name = str(path.resolve())
    # Database CA fields use the same validation/cache as HANA; no private keys.
    ca_path = trust_store(settings, "sqlserver") if tls["validate_certificate"] else ""
    section = {"host": host, "port": str(int(settings.sqlserver_port)), "tds version": "7.4",
               "encryption": tls["encryption"], "ca file": ca_path,
               "check certificate hostname": "yes" if tls["validate_certificate"] else "no",
               "certificate hostname": identity}
    # Paths are backend-controlled; never permit config-line injection.
    if any(any(c in value for c in "\r\n\x00;#[]") for value in section.values()):
        raise ValueError("Database TLS configuration contains an invalid value.")
    alias = "duka_" + hashlib.sha256(json.dumps(section, sort_keys=True).encode()).hexdigest()
    with _condition:
        while _active_count and _active_path != path_name:
            _condition.wait()
        if os.getenv("TDSDUMP") or os.getenv("TDSDUMPCONFIG"):
            raise ValueError("Disable TDSDUMP and TDSDUMPCONFIG before connecting to databases.")
        with open(directory / "freetds.lock", "a", opener=lambda p, f: os.open(p, f, 0o600)) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            parser = configparser.ConfigParser(interpolation=None)
            if path.exists():
                parser.read(path)
            if not parser.has_section(alias):
                parser[alias] = section
                content = io.StringIO()
                parser.write(content)
                with tempfile.NamedTemporaryFile(dir=directory, delete=False) as target:
                    temporary = target.name
                    try:
                        target.write(content.getvalue().encode())
                        target.flush()
                        os.fsync(target.fileno())
                        os.replace(temporary, path)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
        # FREETDS is a legacy synonym: use the same file if it was set.
        os.environ["FREETDSCONF"] = path_name
        os.environ["FREETDS"] = path_name
        _active_path = path_name
        _active_count += 1
    try:
        yield alias
    finally:
        with _condition:
            _active_count -= 1
            _condition.notify_all()
