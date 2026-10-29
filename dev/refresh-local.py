#!/usr/bin/env python3
"""Refresh the existing localhost:8080 containers from this checkout.

This is for the laptop's already-running Docker workspace only. The production
server remains a native Nginx/systemd deployment. Preserve the existing volume,
environment, network, and container security settings when replacing images.
"""

import copy
import hashlib
import http.client
import os
import signal
import json
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = "duka-report-ai-agent-v3-backend-1"
FRONTEND = "duka-report-ai-agent-v3-frontend-1"
NETWORK_ALIAS = {BACKEND: "backend", FRONTEND: "frontend"}
# Set by dev/live-local.py on containers that run this checkout directly.
LIVE_LABEL = "duka.live"
LIVE_TARGETS = ("/app/app", "/usr/share/nginx/html")
LIVE_FLAGS = ("--reload", "--reload-dir", "/app/app")


def is_live(container):
    return (container["Config"].get("Labels") or {}).get(LIVE_LABEL) == "1"


def baked(container):
    """The container settings without live mode's source mounts and reload flags."""
    if not is_live(container):
        return container
    container = copy.deepcopy(container)
    config, host = container["Config"], container["HostConfig"]
    config["Labels"] = {k: v for k, v in config["Labels"].items() if k != LIVE_LABEL}
    host["Binds"] = [b for b in host.get("Binds") or [] if b.split(":")[1] not in LIVE_TARGETS]
    if config.get("Cmd") and "--reload" in config["Cmd"]:
        config["Cmd"] = [part for part in config["Cmd"] if part not in LIVE_FLAGS] + ["--workers", "1"]
    return container


def stop_live_watcher():
    pidfile = ROOT / "work/live-local/frontend-watch.pid"
    try:
        os.killpg(int(pidfile.read_text()), signal.SIGTERM)
        print("Stopped the live-mode frontend watcher.")
    except (OSError, ValueError):
        pass
    pidfile.unlink(missing_ok=True)


def docker(*args, input_text=None):
    result = subprocess.run(
        ["docker", *args], input=input_text, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise RuntimeError(f"Docker command failed: {args[0]} (exit {result.returncode}).")
    return result.stdout


def inspect(name):
    try:
        return json.loads(docker("inspect", name))[0]
    except RuntimeError:
        return None


class DockerConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect("/var/run/docker.sock")


def create_like(old, name, image):
    # Config.Env and private bind mounts travel directly to the local Docker
    # socket. They never enter argv, build contexts, logs, or a temporary file.
    config = dict(old["Config"])
    config["Image"] = image
    config["HostConfig"] = old["HostConfig"]
    network = old["HostConfig"]["NetworkMode"]
    config["NetworkingConfig"] = {
        "EndpointsConfig": {network: {"Aliases": [NETWORK_ALIAS[name]]}}
    }
    connection = DockerConnection("localhost")
    connection.request(
        "POST", f"/v1.41/containers/create?name={name}",
        json.dumps(config), {"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    response.read()
    connection.close()
    if response.status != 201:
        raise RuntimeError(f"Docker could not recreate {name} (HTTP {response.status}).")


def active_work():
    code = """import json,sqlite3
c=sqlite3.connect('file:/data/application.sqlite3?mode=ro',uri=True)
print(json.dumps({
 'chats':c.execute("SELECT count(*) FROM chat_runs WHERE status IN ('queued','running','paused')").fetchone()[0],
 'reports':c.execute("SELECT count(*) FROM reports WHERE status IN ('queued','running')").fetchone()[0],
}))"""
    return json.loads(docker("exec", BACKEND, "python", "-c", code))


def backup_workspace(label):
    code = """import os,sqlite3,sys
target='/data/admin-backups/local-refresh-'+sys.argv[1]+'.sqlite3'
if os.path.exists(target): raise SystemExit('Backup name already exists')
source=sqlite3.connect('/data/application.sqlite3',timeout=30)
source.execute('VACUUM INTO ?', (target,))
check=sqlite3.connect('file:'+target+'?mode=ro',uri=True)
if check.execute('PRAGMA integrity_check').fetchone()[0] != 'ok': raise SystemExit('Backup integrity check failed')
os.chmod(target,0o600)
print(target)"""
    return docker("exec", BACKEND, "python", "-c", code, label).strip()


def build_images(label):
    docker("--version")
    subprocess.run(["npm", "--prefix", "frontend", "run", "build"], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    with tempfile.TemporaryDirectory(prefix="hana-local-build-") as temporary:
        folder = Path(temporary)
        backend = folder / "backend"
        backend.mkdir()
        shutil.copytree(ROOT / "backend/app", backend / "app",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (backend / "Dockerfile").write_text(
            "FROM duka-report-agent-backend:local\n"
            "COPY --chown=app:app app/ /app/app/\n"
        )
        frontend = folder / "frontend"
        frontend.mkdir()
        shutil.copytree(ROOT / "frontend/dist", frontend / "dist")
        (frontend / "Dockerfile").write_text(
            "FROM duka-report-agent-frontend:local\n"
            "COPY --chown=101:root dist/ /usr/share/nginx/html/\n"
        )
        backend_image = f"duka-report-agent-backend:checkout-{label}"
        frontend_image = f"duka-report-agent-frontend:checkout-{label}"
        docker("build", "--pull=false", "-q", "-t", backend_image, str(backend))
        docker("build", "--pull=false", "-q", "-t", frontend_image, str(frontend))
    return backend_image, frontend_image


def backend_ready():
    check = "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/health',timeout=2)"
    for _ in range(60):
        result = subprocess.run(["docker", "exec", BACKEND, "python", "-c", check],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return True
        time.sleep(1)
    return False


def frontend_ready():
    expected = hashlib.sha256((ROOT / "frontend/dist/index.html").read_bytes()).digest()
    for _ in range(30):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=2) as result:
                served = hashlib.sha256(result.read()).digest()
            with urllib.request.urlopen("http://127.0.0.1:8080/api/health", timeout=2) as result:
                healthy = result.status == 200
            if served == expected and healthy:
                return True
        except OSError:
            pass
        time.sleep(1)
    return False


def rollback(backups):
    for name in (FRONTEND, BACKEND):
        if name in backups and inspect(name):
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    for name in (BACKEND, FRONTEND):
        old = backups.get(name)
        if old and inspect(old):
            docker("rename", old, name)
        if inspect(name):
            docker("start", name)


def main():
    old = {name: inspect(name) for name in (BACKEND, FRONTEND)}
    if any(item is None or not item["State"]["Running"] for item in old.values()):
        raise RuntimeError("The existing local Hana backend and frontend must both be running.")
    if any(active_work().values()):
        raise RuntimeError("Wait for local chats and reports to finish before refreshing.")
    stop_live_watcher()
    old = {name: baked(item) for name, item in old.items()}
    label = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    print("Building the current frontend and backend source for localhost:8080...", flush=True)
    backend_image, frontend_image = build_images(label)
    print("Creating a verified SQLite backup in the existing private Docker volume...", flush=True)
    backup = backup_workspace(label)
    if any(active_work().values()):
        raise RuntimeError("A local chat or report started during the build. Refresh again after it finishes.")
    backups = {}
    try:
        docker("stop", "--time", "30", FRONTEND)
        docker("stop", "--time", "30", BACKEND)
        for name in (BACKEND, FRONTEND):
            backup_name = name + "-rollback-" + label
            docker("rename", name, backup_name)
            backups[name] = backup_name
        create_like(old[BACKEND], BACKEND, backend_image)
        docker("start", BACKEND)
        if not backend_ready():
            raise RuntimeError("The updated backend did not become healthy.")
        create_like(old[FRONTEND], FRONTEND, frontend_image)
        docker("start", FRONTEND)
        if not frontend_ready():
            raise RuntimeError("The updated frontend or API did not become healthy.")
    except BaseException:
        rollback(backups)
        raise
    print("Updated http://localhost:8080. Refresh the browser to see this checkout.")
    print("Private backup:", backup)
    print("Stopped rollback containers:", *backups.values())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Local refresh interrupted; previous containers restored if the swap had started.")
        raise SystemExit(130)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print("Local refresh failed:", str(exc))
        raise SystemExit(1)
