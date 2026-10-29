#!/usr/bin/env bash
# Native development only: Python reload + Vite HMR, no production installer.
set -euo pipefail
DUKA_DEV_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DUKA_DEV_ROOT"
DUKA_DEV_PYTHON="${DUKA_DEV_PYTHON:-$DUKA_DEV_ROOT/.venv/bin/python}"
if [[ ! -x "$DUKA_DEV_PYTHON" && -x "$DUKA_DEV_ROOT/work/venv/bin/python" ]]; then
  DUKA_DEV_PYTHON="$DUKA_DEV_ROOT/work/venv/bin/python"
fi
[[ -x "$DUKA_DEV_PYTHON" ]] || { echo 'Create .venv and install backend/requirements-dev.txt first.' >&2; exit 1; }
[[ -d frontend/node_modules ]] || { echo 'Run npm --prefix frontend ci first.' >&2; exit 1; }
export APP_ENV=development SECURE_COOKIES=false
export ALLOWED_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
export DATA_DIR="${DATA_DIR:-$DUKA_DEV_ROOT/data}"
export ENV_FILE="${ENV_FILE:-$DUKA_DEV_ROOT/.env}"
export CODEX_BINARY="${CODEX_BINARY:-$DUKA_DEV_ROOT/work/codex/node_modules/.bin/codex}"
export DUKA_DEV_BACKEND_PORT="${DUKA_DEV_BACKEND_PORT:-8081}"
export VITE_BACKEND_URL="http://127.0.0.1:$DUKA_DEV_BACKEND_PORT"
# Refuse conflicts instead of silently serving an older backend or alternate port.
"$DUKA_DEV_PYTHON" - <<'PY'
import os, socket
for port in (int(os.environ['DUKA_DEV_BACKEND_PORT']),5173):
 with socket.socket() as sock:
  try:sock.bind(('127.0.0.1',port))
  except OSError:raise SystemExit(f'Port {port} is occupied. Stop the existing local service before starting native development.')
PY
printf 'Native development: http://localhost:5173\nWorkspace: %s\n' "$DATA_DIR"
"$DUKA_DEV_PYTHON" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$DUKA_DEV_BACKEND_PORT" --reload --reload-dir backend &
DUKA_DEV_BACKEND_PID=$!
cleanup() { kill "$DUKA_DEV_BACKEND_PID" "${DUKA_DEV_FRONTEND_PID:-}" 2>/dev/null || true; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort &
DUKA_DEV_FRONTEND_PID=$!
wait -n "$DUKA_DEV_BACKEND_PID" "$DUKA_DEV_FRONTEND_PID"
