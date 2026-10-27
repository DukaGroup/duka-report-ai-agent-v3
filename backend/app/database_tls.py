"""Database TLS choices are source-scoped and identical in dev and production.

Supplying trust material always enables verification. Never retry a failed
verified connection with verification or encryption disabled.
"""

from .hana_tls import validate_ca


def options(settings, kind):
    hana = kind == "saphana"
    prefix = "hana_" if hana else "sqlserver_"
    ca = getattr(settings, prefix + "tls_ca_certificate")
    validate_ca(ca)
    verify = bool(ca) or getattr(settings, prefix + "validate_certificate")
    encryption = ("require" if settings.hana_encrypt else "off") if hana else settings.sqlserver_encryption
    if encryption not in ("require", "request", "off"):
        raise ValueError("SQLSERVER_ENCRYPTION must be require, request, or off.")
    # Verification cannot take place over plaintext or opportunistic TLS.
    if verify:
        encryption = "require"
    return {"encryption": encryption, "encrypt": encryption != "off", "validate_certificate": verify,
            "custom_ca": bool(ca), "server_name_configured": bool(getattr(settings, prefix + "tls_server_name"))}


def warnings(settings, kind):
    tls = options(settings, kind)
    if tls["encryption"] == "off":
        return ["Database TLS is disabled. The connection may expose credentials and data on the network."]
    messages = []
    if tls["encryption"] == "request":
        messages.append("Database TLS is optional. The connection may be unencrypted if the server does not support TLS.")
    if not tls["validate_certificate"]:
        messages.append("Database certificate verification is disabled. The server identity is not verified.")
    return messages


def connection_error(message, database):
    """Only report requirements the driver actually describes; omit raw details."""
    text = message.lower().replace("_", " ")
    if ((any(value in text for value in ("certificate required", "certificate is required", "bad certificate")) and "client" in text)
            or "alert certificate required" in text or "peer did not return a certificate" in text):
        return f"{database} requires a client certificate. Ask the DBA for its authentication requirements; client-certificate login is not supported by this connector. A trusted CA certificate alone is not a client certificate."
    if any(value in text for value in ("encryption required", "encryption is required", "requires encryption", "requires tls", "requires ssl", "tls required", "tls is required", "ssl required", "ssl is required", "only secure connections")):
        return f"{database} requires TLS encryption. Enable TLS for this source and test again."
    if "certificate" in text and any(value in text for value in ("hostname", "does not match", "name mismatch")):
        return f"{database} certificate hostname mismatch. Use the DNS name on the certificate or configure the verified TLS server name."
    if "certificate" in text and "expired" in text:
        return f"The {database} server certificate has expired. Ask the DBA to renew it."
    if any(value in text for value in ("certificate verify", "certificate validation", "self signed", "self-signed", "unknown ca", "unknown issuer", "unable to get local issuer")):
        return f"{database} certificate verification failed. Add the trusted public CA certificate for this source, or configure system trust. Check its DNS name and validity."
    if any(value in text for value in ("certificate", "ssl", "tls", "encryption")):
        return f"{database} TLS negotiation failed. Check this source's TLS mode with the DBA; add a trusted certificate if verification is enabled."
    return None
