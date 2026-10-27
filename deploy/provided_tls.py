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


def root_certificate(cert):
    try:
        if not cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            return False
        cert.verify_directly_issued_by(cert)
        return True
    except (x509.ExtensionNotFound, ValueError, TypeError, InvalidSignature):
        return False


def inspect_chain(path):
    roots = [c for c in certificates(path, bundle=True) if root_certificate(c)]
    unique = {fingerprint(c): c for c in roots}
    if not unique:
        return "No self-signed root CA is included. Verification must use a CA already trusted by the server."
    return "\n".join(
        f"Root: {c.subject.rfc4514_string()}\nSHA256: {ident.hex().upper()}" for ident, c in unique.items()
    )


def prepare_bundle(certificate, key, chain, domain, trust_root_sha256=None):
    validate_domain(domain)
    leaves = certificates(certificate)
    if len(leaves) != 1:
        raise ValueError("Provide one website certificate in hana.cer.")
    leaf = leaves[0]
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
    raw_key = key.read_bytes()
    try:
        private_key = serialization.load_pem_private_key(raw_key, password=None)
    except (ValueError, TypeError):
        raise ValueError("Use a valid unencrypted PEM private key for unattended Nginx startup.") from None
    if public_key(private_key.public_key()) != public_key(leaf.public_key()):
        raise ValueError("The private key does not match the website certificate.")
    pool = {fingerprint(c): c for c in certificates(chain, bundle=True)}
    trusted_root = None
    if trust_root_sha256:
        pin = trust_root_sha256.replace(":", "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", pin):
            raise ValueError("Use the SHA256 root fingerprint confirmed independently with IT (64 hex digits).")
        trusted_root = pool.get(bytes.fromhex(pin))
        if trusted_root is None or not root_certificate(trusted_root):
            raise ValueError("The confirmed root fingerprint does not match a self-signed CA in chain.p7b.")
    ordered, seen, current = [], {fingerprint(leaf)}, leaf
    while not root_certificate(current):
        issuers = []
        for ident, candidate in pool.items():
            if ident in seen or candidate.subject != current.issuer:
                continue
            try:
                current.verify_directly_issued_by(candidate)
                issuers.append(candidate)
            except (ValueError, TypeError, InvalidSignature):
                pass
        if not issuers:
            break  # The trust store may contain the remaining issuer/root.
        if len(issuers) != 1:
            raise ValueError(
                "The chain is incomplete or ambiguous; request the correct chain from your CA administrator."
            )
        current = issuers[0]
        seen.add(fingerprint(current))
        if not root_certificate(current):
            ordered.append(current)
    intermediates = b"".join(pem(c) for c in ordered)
    with tempfile.TemporaryDirectory(prefix="hana-tls-check-") as folder:
        staging = Path(folder)
        (staging / "leaf.pem").write_bytes(pem(leaf))
        (staging / "intermediates.pem").write_bytes(intermediates)
        command = [
            "openssl",
            "verify",
            "-purpose",
            "sslserver",
            "-verify_hostname",
            domain,
            "-auth_level",
            "2",
        ]
        if trusted_root is not None:
            (staging / "root.pem").write_bytes(pem(trusted_root))
            command += ["-no-CApath", "-no-CAstore", "-CAfile", str(staging / "root.pem")]
        if ordered:
            command += ["-untrusted", str(staging / "intermediates.pem")]
        result = subprocess.run(command + [str(staging / "leaf.pem")], capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise ValueError(
                "Certificate verification failed (domain, expiry, chain or server-auth purpose).\n"
                + result.stderr.strip()
                + "\nIf the CA is not already trusted, confirm a root fingerprint with IT and use --trust-root-sha256.\n"
                + inspect_chain(chain)
            )
    bundle = {"fullchain.pem": pem(leaf) + intermediates, "privkey.pem": raw_key}
    if trusted_root is not None:
        bundle["verification-ca.pem"] = pem(trusted_root)
    return bundle


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
    parser.add_argument(
        "--inspect-chain", type=Path, help="Print root fingerprints without trusting or installing them."
    )
    parser.add_argument(
        "--trust-root-sha256", help="Independently confirmed fingerprint of a root included in chain.p7b."
    )
    for name in ("certificate", "key", "chain", "output-dir"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    try:
        if args.inspect_chain:
            print(inspect_chain(args.inspect_chain))
            return
        if not all((args.certificate, args.key, args.chain, args.output_dir)):
            parser.error("--certificate, --key, --chain and --output-dir are required for staging.")
        bundle = prepare_bundle(args.certificate, args.key, args.chain, args.domain, args.trust_root_sha256)
        stage(bundle, args.output_dir, args.domain, Path(__file__).with_name("nginx-https.conf"))
    except (OSError, ValueError, UnsupportedAlgorithm, subprocess.SubprocessError) as error:
        parser.exit(1, f"TLS setup refused: {error}\n")
    print(f"Certificate, key, chain and hostname verified for {args.domain}.")


if __name__ == "__main__":
    main()
