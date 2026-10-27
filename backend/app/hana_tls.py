"""HANA certificate trust stays in the backend, outside model workspaces."""

import hashlib
import os
import ssl
import tempfile
from pathlib import Path


def validate_ca(value):
    if not value:
        return value
    if "PRIVATE KEY" in value or "-----BEGIN CERTIFICATE-----" not in value:
        raise ValueError("Provide trusted CA certificates in PEM format, without private keys.")
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT).load_verify_locations(cadata=value)
    except (ssl.SSLError, ValueError):
        raise ValueError("Provide trusted CA certificates in PEM format, without private keys.") from None
    return value


def trust_store(settings, kind="hana"):
    custom = getattr(settings, kind + "_tls_ca_certificate")
    system = ssl.get_default_verify_paths().cafile
    if not custom:
        if not system:
            raise OSError("System CA bundle unavailable")
        return system
    certificate = validate_ca(custom)
    bundle = (Path(system).read_bytes() if system else b"") + b"\n" + certificate.encode() + b"\n"
    directory = settings.data_dir / "tls"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / (hashlib.sha256(bundle).hexdigest() + ".pem")
    # Same-source concurrent workers may build the same bundle. Publish only a
    # complete file, retaining private permissions and stable content identity.
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
        try:
            temporary.write(bundle)
            temporary.flush()
            os.fsync(temporary.fileno())
            os.replace(temporary.name, path)
        finally:
            Path(temporary.name).unlink(missing_ok=True)
    return str(path)
