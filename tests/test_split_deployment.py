"""Opt-in checks against an isolated production-configured Docker workspace.

Set DEPLOYMENT_TEST_URL and DEPLOYMENT_TEST_BACKEND; never point these tests at
a real workspace: they create a disposable test owner, conversation and upload.
"""

import json
import os
import subprocess
import time
from http.cookies import SimpleCookie

import httpx
import pytest

URL = os.getenv("DEPLOYMENT_TEST_URL")
BACKEND = os.getenv("DEPLOYMENT_TEST_BACKEND")
DOMAIN = "reports.example.test"
pytestmark = pytest.mark.skipif(not URL or not BACKEND, reason="Isolated split-deployment fixture is not running.")


def docker(*args):
    return subprocess.run(["docker", *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def owner():
    headers = {"Host": DOMAIN, "Origin": "https://" + DOMAIN, "X-Duka-Request": "1", "X-Forwarded-Proto": "https"}
    client = httpx.Client(base_url=URL, headers=headers, timeout=30)
    status = client.get("/api/auth/status")
    assert status.status_code == 200
    credentials = {"email": "deployment@example.test", "password": "deployment-fixture-password"}
    if status.json()["needs_setup"]:
        token = docker("exec", BACKEND, "cat", "/data/workspace-setup.token")
        response = client.post("/api/auth/setup", json={"name": "Deployment fixture", "setup_token": token, **credentials})
    else:
        response = client.post("/api/auth/login", json=credentials)
    assert response.status_code == 200
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    # HTTP transport simulates the host TLS terminator through X-Forwarded-Proto.
    # Send this fixture's Secure cookie explicitly over its local test connection.
    client.headers["Cookie"] = "duka_session=" + cookie["duka_session"].value
    yield client, response
    client.close()


def test_frontend_serves_spa_assets_and_notification_worker_without_backend_files():
    with httpx.Client(base_url=URL) as client:
        for path in ("/", "/conversations/example"):
            response = client.get(path)
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert response.headers["x-frame-options"] == "DENY"
            assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        for path in ("/assets/missing.js", "/brand/missing.png", "/.env", "/.git/config"):
            assert client.get(path).status_code == 404
        worker = client.get("/notification-worker.js")
        assert worker.status_code == 200 and "javascript" in worker.headers["content-type"]
        assert worker.headers["service-worker-allowed"] == "/" and worker.headers["cache-control"] == "no-cache"
        manifest = client.get("/manifest.webmanifest")
        assert manifest.status_code == 200 and "manifest+json" in manifest.headers["content-type"]
        assert "SQLite format" not in client.get("/application.sqlite3").text


def test_https_host_and_origin_boundaries_survive_the_proxy(owner):
    client, response = owner
    for flag in ("Secure", "HttpOnly", "SameSite=strict"):
        assert flag in response.headers["set-cookie"]
    assert client.get("/api/auth/status").json()["user"]["email"] == "deployment@example.test"
    assert client.get("/api/auth/status").headers["cache-control"] == "no-store"
    assert client.get("/api/auth/status").headers["strict-transport-security"] == "max-age=31536000"
    assert client.get("/api/auth/status", headers={"X-Forwarded-Proto": "http"}).status_code == 426
    assert client.get("/api/auth/status", headers={"Host": "attacker.example.test"}).status_code == 400
    assert client.post("/api/conversations", json={}, headers={"Origin": "https://attacker.example.test"}).status_code == 403
    unknown = client.get("/api/missing")
    assert unknown.status_code == 404 and "application/json" in unknown.headers["content-type"]


def test_authenticated_upload_and_download_use_the_backend_volume(owner):
    client, _ = owner
    conversation = client.post("/api/conversations", json={})
    assert conversation.status_code == 201
    content = b"Isolated deployment attachment\n"
    response = client.post(f"/api/conversations/{conversation.json()['id']}/attachments",
                           files={"file": ("deployment.txt", content, "text/plain")})
    assert response.status_code == 201
    path = "/api/attachments/" + response.json()["id"] + "/download"
    download = client.get(path)
    assert download.status_code == 200 and download.content == content
    with httpx.Client(base_url=URL, headers={"Host": DOMAIN, "X-Forwarded-Proto": "https"}) as anonymous:
        assert anonymous.get(path).status_code == 401


def test_auth_body_limit_is_preserved_through_nginx(owner):
    client, _ = owner
    response = client.post("/api/auth/login", content=b'{"padding":"' + b"x" * 17000 + b'"}',
                           headers={"Content-Type": "application/json"})
    assert response.status_code == 413 and response.headers["cache-control"] == "no-store"


def test_real_client_address_reaches_the_persistent_login_limiter(owner):
    client, _ = owner
    script = """import sqlite3,hashlib
c=sqlite3.connect('file:/data/application.sqlite3?mode=ro',uri=True)
key=hashlib.sha256(b'login:ip:203.0.113.50').hexdigest()
row=c.execute('SELECT attempts FROM auth_attempts WHERE key_hash=?',(key,)).fetchone()
print(row[0] if row else 0)
"""
    before = int(docker("exec", BACKEND, "python", "-c", script))
    response = client.post("/api/auth/login", headers={"X-Forwarded-For": "203.0.113.50"},
                           json={"email": "absent@example.test", "password": "wrong"})
    assert response.status_code == 401
    assert int(docker("exec", BACKEND, "python", "-c", script)) == before + 1


def test_frontend_has_no_private_mount_and_backend_has_no_published_port():
    frontend = os.getenv("DEPLOYMENT_TEST_FRONTEND", BACKEND.replace("backend", "frontend"))
    mounts = json.loads(docker("inspect", "-f", "{{json .Mounts}}", frontend))
    assert not any(item["Destination"] in ("/data", "/run/duka.env") for item in mounts)
    ports = json.loads(docker("inspect", "-f", "{{json .NetworkSettings.Ports}}", BACKEND))
    assert not any(ports.values())
    assert docker("exec", BACKEND, "sh", "-c", "test ! -d /app/frontend && echo isolated") == "isolated"


def test_an_untrusted_network_peer_cannot_claim_https_forwarding():
    network = os.getenv("DEPLOYMENT_TEST_NETWORK")
    assert network
    script = """import urllib.request,urllib.error
r=urllib.request.Request('http://frontend:8080/api/auth/status',headers={
 'Host':'reports.example.test','X-Forwarded-Proto':'https','X-Forwarded-For':'203.0.113.10'})
try:
 print(urllib.request.urlopen(r,timeout=10).status)
except urllib.error.HTTPError as e:
 print(e.code)
"""
    image = os.getenv("DUKA_BACKEND_IMAGE", "duka-report-agent-backend:local")
    assert docker("run", "--rm", "--network", network, "--entrypoint", "python", image, "-c", script) == "426"


def test_streaming_response_arrives_before_the_final_event():
    probe = os.getenv("DEPLOYMENT_TEST_STREAM_URL")
    if not probe:
        pytest.skip("Isolated streaming backend probe is not running.")
    started = time.monotonic()
    with httpx.Client(base_url=probe, timeout=10) as client:
        with client.stream("GET", "/api/stream") as response:
            assert response.status_code == 200
            lines = response.iter_lines()
            assert json.loads(next(lines))["type"] == "delta"
            assert time.monotonic() - started < 1.5
            assert json.loads(next(lines))["type"] == "done"
            assert time.monotonic() - started >= 1.8
