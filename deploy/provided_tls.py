"""Validate company TLS files and stage an ordered native Nginx certificate bundle."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7


DEFAULT_DOMAIN = "hana.dukagroup.local"


def certificates(path, bundle=False):
    content = path.read_bytes()
    if bundle:
        for loader in (pkcs7.load_pem_pkcs7_certificates, pkcs7.load_der_pkcs7_certificates):
            try:
                result = loader(content)
                if result:
                    return result
            except ValueError:
                pass
    try:
        return x509.load_pem_x509_certificates(content)
    except ValueError:
        return [x509.load_der_x509_certificate(content)]


def pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM)


def fingerprint(cert):
    return cert.fingerprint(hashes.SHA256())


def public_key(key):
    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def validate_domain(domain):
    if len(domain) > 253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
        raise ValueError("Use a lowercase DNS domain without a scheme, port or path.")


def prepare_bundle(certificate, key, chain, ca, domain):
    validate_domain(domain)
    leaves, roots = certificates(certificate), certificates(ca)
    if len(leaves) != 1 or len(roots) != 1:
        raise ValueError("Provide one website certificate and one independently trusted root CA certificate.")
    leaf, root = leaves[0], roots[0]
    try:
        names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        if not names.get_values_for_type(x509.DNSName):
            raise ValueError("The website certificate must have a DNS Subject Alternative Name.")
    except x509.ExtensionNotFound:
        raise ValueError("The website certificate must have a Subject Alternative Name for the domain.") from None
    try:
        if leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("The website certificate must not be a CA certificate.")
    except x509.ExtensionNotFound:
        pass  # The extension is optional on end-entity certificates.
    try:
        if not root.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise ValueError("The trusted root must be a CA certificate.")
    except x509.ExtensionNotFound:
        raise ValueError("CA basic constraints are required on the trusted root.") from None
    try:
        root.verify_directly_issued_by(root)
    except (ValueError, TypeError, InvalidSignature):
        raise ValueError("Supply the self-signed root CA, not an intermediate certificate.") from None
    raw_key = key.read_bytes()
    try:
        private_key = serialization.load_pem_private_key(raw_key, password=None)
    except (ValueError, TypeError):
        raise ValueError("Use a valid unencrypted PEM private key for unattended Nginx startup.") from None
    if public_key(private_key.public_key()) != public_key(leaf.public_key()):
        raise ValueError("The private key does not match the website certificate.")
    pool = {fingerprint(c): c for c in certificates(chain, bundle=True) + [root]}
    ordered, seen, current = [], {fingerprint(leaf)}, leaf
    while fingerprint(current) != fingerprint(root):
        issuers = []
        for ident, candidate in pool.items():
            if ident in seen or candidate.subject != current.issuer:
                continue
            try:
                current.verify_directly_issued_by(candidate)
                issuers.append(candidate)
            except (ValueError, TypeError, InvalidSignature):
                pass
        if len(issuers) != 1:
            raise ValueError(
                "The chain is incomplete or ambiguous; request the correct chain from your CA administrator."
            )
        current = issuers[0]
        seen.add(fingerprint(current))
        if fingerprint(current) != fingerprint(root):
            ordered.append(current)
    intermediates = b"".join(pem(c) for c in ordered)
    with tempfile.TemporaryDirectory(prefix="hana-tls-check-") as folder:
        staging = Path(folder)
        (staging / "leaf.pem").write_bytes(pem(leaf))
        (staging / "root.pem").write_bytes(pem(root))
        (staging / "intermediates.pem").write_bytes(intermediates)
        command = [
            "openssl",
            "verify",
            "-no-CApath",
            "-no-CAstore",
            "-CAfile",
            str(staging / "root.pem"),
            "-purpose",
            "sslserver",
            "-verify_hostname",
            domain,
            "-auth_level",
            "2",
        ]
        if ordered:
            command += ["-untrusted", str(staging / "intermediates.pem")]
        result = subprocess.run(command + [str(staging / "leaf.pem")], capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise ValueError(
                "Certificate verification failed (domain, expiry, chain or server-auth purpose).\n"
                + result.stderr.strip()
            )
    return {"fullchain.pem": pem(leaf) + intermediates, "privkey.pem": raw_key, "trusted-root.crt": pem(root)}


def stage(bundle, output, domain, template):
    # This directory is created by the root-owned installer, outside the web root.
    if output.is_symlink() or not output.is_dir() or any(output.iterdir()):
        raise ValueError("The output directory must be an empty regular directory.")
    if not re.fullmatch(r"/[a-zA-Z0-9/_\-.]+", str(output)):
        raise ValueError("Use a simple absolute output path without whitespace or Nginx syntax.")
    output.chmod(0o700)
    for name, content in bundle.items():
        with os.fdopen(
            os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), "wb"
        ) as target:
            target.write(content)
    config = template.read_text().replace("__DUKA_DOMAIN__", domain).replace("__DUKA_TLS_DIR__", str(output))
    (output / "site.conf").write_text(config)
    (output / "site.conf").chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", default=DEFAULT_DOMAIN)
    for name in ("certificate", "key", "chain", "ca", "output-dir"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        bundle = prepare_bundle(args.certificate, args.key, args.chain, args.ca, args.domain)
        stage(bundle, args.output_dir, args.domain, Path(__file__).with_name("nginx-https.conf"))
    except (OSError, ValueError, UnsupportedAlgorithm, subprocess.SubprocessError) as error:
        parser.exit(1, f"TLS setup refused: {error}\n")
    print(f"Certificate, key, chain and hostname verified for {args.domain}.")


if __name__ == "__main__":
    main()
