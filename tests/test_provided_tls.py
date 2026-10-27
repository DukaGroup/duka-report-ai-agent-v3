"""Company PKI fixtures exercise actual signature, trust, hostname and expiry checks."""

from datetime import datetime, timedelta, timezone
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socket
import subprocess
import threading
import time

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("provided_tls", ROOT / "deploy/provided_tls.py")
tls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tls)
DOMAIN = "hana.dukagroup.local"


def make_cert(name, key, issuer=None, issuer_key=None, ca=False, expired=False, client_only=False):
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(timezone.utc)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer.subject if issuer else subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=3))
        .not_valid_after(now + timedelta(days=-1 if expired else 30))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
    )
    if not ca:
        builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
        builder = builder.add_extension(
            x509.ExtendedKeyUsage(
                [ExtendedKeyUsageOID.CLIENT_AUTH if client_only else ExtendedKeyUsageOID.SERVER_AUTH]
            ),
            critical=False,
        )
    return builder.sign(issuer_key or key, hashes.SHA256())


@pytest.fixture(scope="module")
def pki():
    keys = [rsa.generate_private_key(public_exponent=65537, key_size=2048) for _ in range(4)]
    root = make_cert("Company Root", keys[0], ca=True)
    intermediate = make_cert("Company Issuing CA", keys[1], root, keys[0], ca=True)
    leaf = make_cert(DOMAIN, keys[2], intermediate, keys[1])
    return keys, root, intermediate, leaf


def inputs(tmp_path, pki, encoding=serialization.Encoding.DER):
    keys, root, intermediate, leaf = pki
    cert, key, chain = [tmp_path / name for name in ("hana.cer", "hana.key", "chain.p7b")]
    cert.write_bytes(tls.pem(leaf))
    key.write_bytes(
        keys[2].private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    # Deliberately unordered, with duplicate root and website cert included.
    chain.write_bytes(pkcs7.serialize_certificates([root, leaf, intermediate, root], encoding))
    return cert, key, chain


@pytest.mark.parametrize("encoding", [serialization.Encoding.DER, serialization.Encoding.PEM])
def test_p7b_order_and_root_exclusion(tmp_path, pki, encoding):
    bundle = tls.prepare_bundle(*inputs(tmp_path, pki, encoding), DOMAIN, tls.fingerprint(pki[1]).hex())
    certs = x509.load_pem_x509_certificates(bundle["fullchain.pem"])
    assert [tls.fingerprint(c) for c in certs] == [tls.fingerprint(pki[3]), tls.fingerprint(pki[2])]
    assert bundle["verification-ca.pem"] == tls.pem(pki[1])


@pytest.mark.parametrize(
    "failure",
    [
        "wrong_key",
        "wrong_domain",
        "expired",
        "client_only",
        "incomplete",
        "wrong_fingerprint",
        "invalid_signature",
        "encrypted_key",
        "invalid_p7b",
    ],
)
def test_reject_invalid_identity_or_trust(tmp_path, pki, failure):
    cert, key, chain = inputs(tmp_path, pki)
    keys, root, intermediate, leaf = pki
    domain = DOMAIN
    pin = tls.fingerprint(root).hex()
    if failure == "wrong_key":
        key.write_bytes(
            keys[3].private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
        )
    elif failure == "wrong_domain":
        domain = "other.dukagroup.local"
    elif failure in ("expired", "client_only"):
        cert.write_bytes(
            tls.pem(
                make_cert(
                    DOMAIN,
                    keys[2],
                    intermediate,
                    keys[1],
                    expired=failure == "expired",
                    client_only=failure == "client_only",
                )
            )
        )
    elif failure == "incomplete":
        chain.write_bytes(pkcs7.serialize_certificates([root], serialization.Encoding.DER))
    elif failure == "wrong_fingerprint":
        pin = "00" * 32
    elif failure == "invalid_signature":
        cert.write_bytes(tls.pem(make_cert(DOMAIN, keys[2], intermediate, keys[3])))
    elif failure == "encrypted_key":
        key.write_bytes(
            keys[2].private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.BestAvailableEncryption(b"fixture-password"),
            )
        )
    else:
        chain.write_bytes(b"invalid PKCS7")
    with pytest.raises(ValueError):
        tls.prepare_bundle(cert, key, chain, domain, pin)
    assert not (tmp_path / "fullchain.pem").exists()


def test_root_can_directly_issue_leaf_and_leaf_can_be_der(tmp_path, pki):
    keys, root, _, _ = pki
    cert, key, chain = inputs(tmp_path, pki)
    leaf = make_cert(DOMAIN, keys[2], root, keys[0])
    cert.write_bytes(leaf.public_bytes(serialization.Encoding.DER))
    chain.write_bytes(tls.pem(root))
    bundle = tls.prepare_bundle(cert, key, chain, DOMAIN, tls.fingerprint(root).hex())
    assert bundle["fullchain.pem"] == tls.pem(leaf)


@pytest.mark.parametrize("include_root", [True, False])
def test_only_three_files_with_system_trust_and_optional_root_in_p7b(tmp_path, pki, monkeypatch, include_root):
    cert, key, chain = inputs(tmp_path, pki)
    root, intermediate = pki[1:3]
    chain.write_bytes(
        pkcs7.serialize_certificates([intermediate] + ([root] if include_root else []), serialization.Encoding.DER)
    )
    trust = tmp_path / "system-trust.pem"
    trust.write_bytes(tls.pem(root))
    monkeypatch.setenv("SSL_CERT_FILE", str(trust))
    bundle = tls.prepare_bundle(cert, key, chain, DOMAIN)
    assert set(bundle) == {"fullchain.pem", "privkey.pem"}
    assert bundle["fullchain.pem"] == tls.pem(pki[3]) + tls.pem(intermediate)


def test_chain_root_is_not_implicitly_trusted_and_can_be_inspected(tmp_path, pki, monkeypatch):
    paths = inputs(tmp_path, pki)
    monkeypatch.setenv("SSL_CERT_FILE", "/dev/null")
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path / "no-system-roots"))
    with pytest.raises(ValueError, match="confirm a root fingerprint"):
        tls.prepare_bundle(*paths, DOMAIN)
    description = tls.inspect_chain(paths[2])
    assert tls.fingerprint(pki[1]).hex().upper() in description
    assert description.count("SHA256:") == 1


@pytest.mark.parametrize("pin", ["invalid", "0" * 64])
def test_pinned_root_must_be_confirmed_and_present(tmp_path, pki, pin):
    with pytest.raises(ValueError, match="fingerprint"):
        tls.prepare_bundle(*inputs(tmp_path, pki), DOMAIN, pin)


def test_inspection_reports_missing_root_and_pin_cannot_trust_intermediate(tmp_path, pki):
    cert, key, chain = inputs(tmp_path, pki)
    chain.write_bytes(pkcs7.serialize_certificates([pki[2]], serialization.Encoding.DER))
    assert "No self-signed root" in tls.inspect_chain(chain)
    with pytest.raises(ValueError, match="self-signed CA"):
        tls.prepare_bundle(cert, key, chain, DOMAIN, tls.fingerprint(pki[2]).hex())


def test_staging_keeps_private_files_outside_webroot_and_nginx_parses(tmp_path, pki):
    bundle = tls.prepare_bundle(*inputs(tmp_path, pki), DOMAIN, tls.fingerprint(pki[1]).hex())
    output = tmp_path / "private-release"
    output.mkdir()
    tls.stage(bundle, output, DOMAIN, ROOT / "deploy/nginx-https.conf")
    assert output.stat().st_mode & 0o777 == 0o700
    for name in (*bundle, "site.conf"):
        assert (output / name).stat().st_mode & 0o777 == 0o600
    config = (output / "site.conf").read_text()
    assert "letsencrypt" not in config and "reports.example.com" not in config
    assert f"ssl_certificate {output}/fullchain.pem;" in config
    assert "root /var/www/duka-agent/app/frontend/dist;" in config
    nginx = shutil.which("nginx")
    if not nginx:
        pytest.skip("Nginx needed to validate the rendered configuration.")
    top = tmp_path / "nginx.conf"
    top.write_text(
        f"pid {tmp_path}/nginx.pid; error_log stderr; events {{}} http {{ access_log off; "
        f"client_body_temp_path {tmp_path}/body; proxy_temp_path {tmp_path}/proxy; "
        f"fastcgi_temp_path {tmp_path}/fastcgi; uwsgi_temp_path {tmp_path}/uwsgi; "
        f"scgi_temp_path {tmp_path}/scgi; include {output}/site.conf; }}"
    )
    result = subprocess.run(
        [nginx, "-t", "-e", "stderr", "-p", str(tmp_path), "-c", str(top)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    with pytest.raises(ValueError):
        tls.stage(bundle, output, DOMAIN, ROOT / "deploy/nginx-https.conf")


def test_live_https_serves_frontend_and_proxies_backend_with_real_ca_verification(tmp_path, pki):
    nginx, curl = shutil.which("nginx"), shutil.which("curl")
    if not nginx or not curl:
        pytest.skip("Nginx and curl required for the live native HTTPS test.")
    bundle = tls.prepare_bundle(*inputs(tmp_path, pki), DOMAIN, tls.fingerprint(pki[1]).hex())
    output = tmp_path / "release"
    output.mkdir()
    tls.stage(bundle, output, DOMAIN, ROOT / "deploy/nginx-https.conf")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("Hana fixture frontend")
    forwarded = []

    class Backend(BaseHTTPRequestHandler):
        def do_GET(self):
            forwarded.append(dict(self.headers))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"healthy"}')

        def log_message(self, *args):
            pass

    backend = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    worker = threading.Thread(target=backend.serve_forever, daemon=True)
    worker.start()
    with socket.socket() as one, socket.socket() as two:
        one.bind(("127.0.0.1", 0))
        two.bind(("127.0.0.1", 0))
        http_port, https_port = one.getsockname()[1], two.getsockname()[1]
    site = (output / "site.conf").read_text()
    site = site.replace("listen 80;", f"listen 127.0.0.1:{http_port};")
    site = site.replace("listen 443 ssl;", f"listen 127.0.0.1:{https_port} ssl;")
    site = site.replace("root /var/www/duka-agent/app/frontend/dist;", f"root {web};")
    site = site.replace("http://127.0.0.1:8080", f"http://127.0.0.1:{backend.server_port}")
    (output / "site.conf").write_text(site)
    top = tmp_path / "nginx.conf"
    top.write_text(
        f"daemon off; master_process off; pid {tmp_path}/pid; error_log stderr; events {{}} "
        f"http {{ access_log off; client_body_temp_path {tmp_path}/body; "
        f"proxy_temp_path {tmp_path}/proxy; fastcgi_temp_path {tmp_path}/fastcgi; "
        f"uwsgi_temp_path {tmp_path}/uwsgi; scgi_temp_path {tmp_path}/scgi; include {output}/site.conf; }}"
    )
    process = subprocess.Popen(
        [nginx, "-e", "stderr", "-p", str(tmp_path), "-c", str(top)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(100):
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", https_port)) == 0:
                    break
            if process.poll() is not None:
                pytest.fail(process.stderr.read())
            time.sleep(0.02)
        command = [
            curl,
            "--noproxy",
            "*",
            "--silent",
            "--show-error",
            "--fail",
            "--max-time",
            "5",
            "--cacert",
            str(output / "verification-ca.pem"),
            "--resolve",
            f"{DOMAIN}:{https_port}:127.0.0.1",
        ]
        url = f"https://{DOMAIN}:{https_port}"
        page = subprocess.run(command + [url + "/conversations/fixture"], capture_output=True, text=True)
        assert page.returncode == 0 and page.stdout == "Hana fixture frontend", page.stderr
        health = subprocess.run(command + [url + "/api/health"], capture_output=True, text=True)
        assert health.returncode == 0 and health.stdout == '{"status":"healthy"}', health.stderr
        assert forwarded[0]["X-Forwarded-Proto"] == "https"
        assert forwarded[0]["X-Forwarded-For"] == "127.0.0.1"
        assert forwarded[0]["Host"] == DOMAIN
        untrusted = subprocess.run(
            [
                curl,
                "--noproxy",
                "*",
                "--silent",
                "--max-time",
                "5",
                "--resolve",
                f"{DOMAIN}:{https_port}:127.0.0.1",
                url,
            ],
            capture_output=True,
        )
        assert untrusted.returncode == 60  # Actual TLS failure without the company root.
    finally:
        process.terminate()
        process.communicate(timeout=5)
        backend.shutdown()
        backend.server_close()
        worker.join(timeout=5)


@pytest.mark.parametrize("failure", ["validation", "nginx", "reload", "health", "success"])
def test_installer_rollback_preserves_old_site_and_certificates(tmp_path, failure):
    # Relocate system paths to an isolated fixture. Run the real shell control flow.
    app = tmp_path / "app"
    (app / "frontend/dist").mkdir(parents=True)
    (app / ".venv/bin").mkdir(parents=True)
    (app / "frontend/dist/index.html").write_text("fixture frontend")
    etc = tmp_path / "nginx"
    (etc / "sites-available").mkdir(parents=True)
    (etc / "sites-enabled").mkdir()
    old = etc / "sites-available/duka-agent"
    old.write_text("old working configuration")
    enabled = etc / "sites-enabled/duka-agent"
    enabled.symlink_to(old)
    certs = etc / "tls" / DOMAIN
    certs.mkdir(parents=True)
    old_release = certs / "old"
    old_release.mkdir()
    (old_release / "privkey.pem").write_text("old fixture key")
    source = (ROOT / "deploy/setup-provided-https.sh").read_text()
    source = source.replace("/var/www/duka-agent/app", str(app)).replace("/etc/nginx", str(etc))
    source = source.replace("if [[ $EUID != 0 ]]", "if false").replace("sudo -u duka env", "env")
    script = tmp_path / "installer.sh"
    script.write_text(source)
    runner = app / ".venv/bin/python"
    runner.write_text("""#!/bin/bash
if [[ "$1" == */preflight.py ]]; then exit 0; fi
if [[ "$TLS_TEST_FAILURE" == validation ]]; then exit 1; fi
while (($#)); do
  if [[ "$1" == --output-dir ]]; then printf 'new config' > "$2/site.conf"; exit 0; fi
  shift
done
exit 1
""")
    runner.chmod(0o755)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    commands = {
        "nginx": '#!/bin/bash\n[[ "$TLS_TEST_FAILURE" != nginx ]]\n',
        "systemctl": '#!/bin/bash\nif [[ "$TLS_TEST_FAILURE" == reload && "$1" == reload ]]; then exit 1; fi\nexit 0\n',
        "curl": '#!/bin/bash\n[[ "$TLS_TEST_FAILURE" != health ]]\n',
    }
    for name, content in commands.items():
        executable = binaries / name
        executable.write_text(content)
        executable.chmod(0o755)
    fixture = tmp_path / "input"
    fixture.write_text("fixture")
    args = [item for flag in ("--certificate", "--key", "--chain") for item in (flag, str(fixture))]
    environment = {**os.environ, "PATH": str(binaries) + ":" + os.environ["PATH"], "TLS_TEST_FAILURE": failure}
    result = subprocess.run(["bash", str(script), *args], env=environment, capture_output=True, text=True)
    assert (result.returncode == 0) == (failure == "success"), result.stderr
    assert (old_release / "privkey.pem").read_text() == "old fixture key"
    if failure == "success":
        assert old.read_text() == "new config"
        assert len(list(certs.glob("release.*"))) == 1
    else:
        assert old.read_text() == "old working configuration" and enabled.is_symlink()
        assert enabled.resolve() == old
        assert not list(certs.glob("release.*"))
