#!/usr/bin/env python3
"""Live mode for the laptop's localhost:8080 Docker workspace.

After running this once, code changes show up with a normal browser refresh:
- the backend container runs this checkout's backend/app and restarts itself
  when a Python file changes;
- the frontend container serves frontend/dist, which a background Vite watcher
  rebuilds whenever a frontend file changes.

The workspace volume, .env and container security settings are kept. Changes
to Python/npm dependencies, Dockerfiles or nginx still need dev/refresh-local.py.

  dev/live-local.py          enable live mode (or restart the watcher)
  dev/live-local.py --stop   stop the frontend watcher
  dev/refresh-local.py       go back to baked images (also leaves live mode)
"""

import copy
import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("refresh_local", ROOT / "dev/refresh-local.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)

BACKEND, FRONTEND = refresh.BACKEND, refresh.FRONTEND
STATE = ROOT / "work/live-local"
PIDFILE = STATE / "frontend-watch.pid"
LOGFILE = STATE / "frontend-watch.log"


def live_backend(old):
    config = copy.deepcopy(old)
    command = [part for part in config["Config"]["Cmd"] if part not in ("--workers", "1")]
    config["Config"]["Cmd"] = command + ["--reload", "--reload-dir", "/app/app"]
    config["Config"]["Labels"] = {**(config["Config"].get("Labels") or {}), refresh.LIVE_LABEL: "1"}
    config["HostConfig"]["Binds"] = [*(config["HostConfig"].get("Binds") or []), f"{ROOT}/backend/app:/app/app:ro"]
    return config


def live_frontend(old):
    config = copy.deepcopy(old)
    config["Config"]["Labels"] = {**(config["Config"].get("Labels") or {}), refresh.LIVE_LABEL: "1"}
    config["HostConfig"]["Binds"] = [
        *(config["HostConfig"].get("Binds") or []), f"{ROOT}/frontend/dist:/usr/share/nginx/html:ro"
    ]
    return config


def watcher_pid():
    try:
        pid = int(PIDFILE.read_text())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def stop_watcher():
    pid = watcher_pid()
    if pid:
        os.killpg(pid, signal.SIGTERM)
        print("Stopped the frontend watcher.")
    PIDFILE.unlink(missing_ok=True)


def start_watcher():
    stop_watcher()
    STATE.mkdir(parents=True, exist_ok=True)
    log = LOGFILE.open("w")
    # Keep old hashed assets so a page loaded mid-rebuild still works.
    process = subprocess.Popen(
        ["npm", "exec", "--", "vite", "build", "--watch"],
        cwd=ROOT / "frontend", stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        env={**os.environ, "DUKA_LIVE_WATCH": "1"},
    )
    PIDFILE.write_text(str(process.pid))
    print(f"Frontend watcher running (log: {LOGFILE}).")


def enable():
    old = {name: refresh.inspect(name) for name in (BACKEND, FRONTEND)}
    if any(item is None or not item["State"]["Running"] for item in old.values()):
        raise RuntimeError("The existing local Hana backend and frontend must both be running.")
    if all(refresh.is_live(item) for item in old.values()):
        print("Live mode is already on.")
        start_watcher()
        return
    if any(refresh.active_work().values()):
        raise RuntimeError("Wait for local chats and reports to finish before switching to live mode.")
    print("Building the frontend once...", flush=True)
    subprocess.run(["npm", "--prefix", "frontend", "run", "build"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    label = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    print("Creating a verified SQLite backup in the existing private Docker volume...", flush=True)
    backup = refresh.backup_workspace(label)
    backups = {}
    try:
        refresh.docker("stop", "--time", "30", FRONTEND)
        refresh.docker("stop", "--time", "30", BACKEND)
        for name in (BACKEND, FRONTEND):
            backups[name] = name + "-rollback-" + label
            refresh.docker("rename", name, backups[name])
        refresh.create_like(live_backend(old[BACKEND]), BACKEND, old[BACKEND]["Config"]["Image"])
        refresh.docker("start", BACKEND)
        if not refresh.backend_ready():
            raise RuntimeError("The live backend did not become healthy.")
        refresh.create_like(live_frontend(old[FRONTEND]), FRONTEND, old[FRONTEND]["Config"]["Image"])
        refresh.docker("start", FRONTEND)
        if not refresh.frontend_ready():
            raise RuntimeError("The live frontend or API did not become healthy.")
    except BaseException:
        refresh.rollback(backups)
        raise
    start_watcher()
    print("Live mode is on for http://localhost:8080 — edit code, then just refresh the browser.")
    print("Private backup:", backup)
    print("Stopped rollback containers:", *backups.values())


if __name__ == "__main__":
    try:
        stop_watcher() if "--stop" in sys.argv[1:] else enable()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        print("Live mode failed:", str(exc))
        raise SystemExit(1)
