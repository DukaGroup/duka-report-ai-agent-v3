#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

duka_target="${1:-all}"
case "$duka_target" in
    all) duka_services=(frontend backend) ;;
    frontend) duka_services=(frontend) ;;
    backend) duka_services=(backend) ;;
    *) echo 'Usage: bash deploy/docker/deploy.sh [all|frontend|backend]' >&2; exit 2 ;;
esac

# COMPOSE_FILE may include the optional DNS override. Never print resolved
# Compose configuration: it contains the private backend environment.
docker compose config --quiet
duka_project="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
duka_legacy="$(docker ps -aq --filter "label=com.docker.compose.project=$duka_project" --filter 'label=com.docker.compose.service=app')"
duka_backend="$(docker compose ps -q backend)"
duka_check_idle() {
    local duka_container duka_active
    for duka_container in $duka_legacy $duka_backend; do
        if [[ "$(docker inspect -f '{{.State.Running}}' "$duka_container")" != true ]]; then
            continue
        fi
        if [[ "$duka_target" == frontend && -z "$duka_legacy" ]]; then
            continue
        fi
        duka_active="$(docker exec "$duka_container" python -c "import sqlite3; c=sqlite3.connect('file:/data/application.sqlite3?mode=ro',uri=True); print(c.execute(\"SELECT count(*) FROM chat_runs WHERE status IN ('queued','running','paused')\").fetchone()[0]+c.execute(\"SELECT count(*) FROM reports WHERE status IN ('queued','running')\").fetchone()[0])")"
        if [[ "$duka_active" != 0 ]]; then
            echo 'Finish or stop active chats/reports before replacing the backend.' >&2
            exit 1
        fi
    done
}
duka_check_idle

duka_wait_api() {
    local duka_attempt
    if [[ -z "$(docker compose ps -q frontend)" ]]; then
        return 0  # Backend-only installation was already checked by Compose.
    fi
    for duka_attempt in {1..30}; do
        if docker compose exec -T frontend wget -q -O /dev/null http://127.0.0.1:8080/api/health; then
            return 0
        fi
        sleep 1
    done
    echo 'The frontend cannot reach the backend API.' >&2
    return 1
}

if [[ -n "$duka_legacy" ]]; then
    duka_volume="$(docker compose config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["volumes"]["workspace-data"]["name"])')"
    for duka_container in $duka_legacy; do
        duka_existing="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}' "$duka_container")"
        if [[ "$duka_existing" != "$duka_volume" ]]; then
            echo 'The existing data volume does not match this Compose project. Keep the original project name.' >&2
            exit 1
        fi
    done
    # The first migration needs both replacement services, even for a requested
    # frontend-only update. Retain the stopped old container until health passes.
    duka_services=(frontend backend)
fi

docker compose build "${duka_services[@]}"
# A build may take minutes; check again immediately before replacing services.
duka_check_idle
if [[ -n "$duka_legacy" ]]; then
    docker stop $duka_legacy
fi
if ! { docker compose up -d --wait --wait-timeout 120 "${duka_services[@]}" && duka_wait_api; }; then
    if [[ -n "$duka_legacy" ]]; then
        docker compose stop frontend backend
        docker start $duka_legacy
        echo 'Split deployment failed; the previous app container was restarted with its original data volume.' >&2
    fi
    exit 1
fi
if [[ -n "$duka_legacy" ]]; then
    # No -v: the persistent volume is retained and now belongs to backend.
    docker rm $duka_legacy
fi
docker compose ps
