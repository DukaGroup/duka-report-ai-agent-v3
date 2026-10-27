# Docker deployment: separate frontend and backend

Run from the repository root on Linux x86-64. Docker Compose builds two independent images:

```text
Browser → HTTPS proxy (production) → frontend:8080 → /api/* → backend:8080
                                    website                  Python API / models
                                                             /data → workspace-data
                                                             /run/duka.env → private .env
```

The frontend publishes only `127.0.0.1:${PORT:-8080}`. The backend publishes no host port. Both containers run without root privileges, with read-only filesystems, dropped capabilities and private temporary storage. The frontend has no mount of `.env`, the database, uploads, reports or provider credentials. Browser requests use relative `/api` URLs; no frontend secret or cross-origin login configuration is needed.

## Start or update

On first installation only, create `.env` from `.env.example`; never overwrite an existing configuration. Set production origins/cookies before exposing the service remotely.

```bash
# Only on a fresh checkout with no existing .env:
cp -n .env.example .env
bash scripts/allow-env-write.sh
bash deploy/docker/deploy.sh
```

The script builds, starts and waits for healthy services. When upgrading from the previous `app` container, it checks that the original named data volume matches, refuses to interrupt active chats/reports, and keeps the old container for rollback until both new services are healthy. A failed first migration stops the replacements and restarts the old container. It never removes a volume or overwrites workspace records. Keep the same Compose project name/directory, or explicitly retain its original `COMPOSE_PROJECT_NAME`.

Open `http://localhost:8080` locally. Production uses the HTTPS address below.

```bash
# Update only the frontend; an existing backend is not rebuilt.
bash deploy/docker/deploy.sh frontend
# Update only the backend after active work finishes.
bash deploy/docker/deploy.sh backend
# Inspect services and their separate logs.
docker compose ps
docker compose logs --tail=100 frontend
docker compose logs --tail=100 backend
# Read-only API health check through the frontend.
curl --fail http://127.0.0.1:8080/api/health
```

The frontend resolves the backend by service name, including after container replacement. API requests disable proxy buffering so chat streaming, uploads and report downloads retain their existing behavior. HTML and the notification worker revalidate; content-hashed assets may be cached for one year.

## Configuration and storage

`compose.yaml` passes backend settings explicitly. `.env` remains mounted writable into the backend for admin-saved connection profiles. `DUKA_ENV_FILE` can select another private file path, for example in an isolated test deployment. Keep its ownership/ACL compatible with backend UID 10001. `DUKA_FRONTEND_IMAGE` and `DUKA_BACKEND_IMAGE` can select independently tagged images; defaults are `duka-report-agent-frontend:local` and `duka-report-agent-backend:local`.

The `workspace-data` volume key is unchanged. Existing users, sessions, grants, SQLite snapshots, uploads, Excel reports, model histories and notification keys stay in that backend volume. Frontend rebuilds do not touch it. Keep the volume and private environment when moving hosts; use [backup/recovery](backup-and-restore.md) for the archive format. The native backup wrapper operates on systemd, so Docker operators must stop the backend and run the backup tool against the actual volume/environment through their own host backup procedure. No new automatic backup schedule is installed.

## Production HTTPS and proxy trust

Use an HTTPS reverse proxy on the same host in front of the loopback frontend port. `deploy/docker/nginx-https.conf` is the Docker-specific host Nginx example; set the real domain, certificate paths and published port. Its HTTP listener redirects to HTTPS. Configure matching `ALLOWED_ORIGINS=https://YOUR_DOMAIN`, `APP_ENV=production` and `SECURE_COOKIES=true`. Keep database TLS verification enabled.

The host TLS proxy must **overwrite** `X-Forwarded-For` with the real client address and `X-Forwarded-Proto` with `https`, as the example does. The frontend trusts those headers only from its Docker bridge gateway, discovered on startup; `HOST_PROXY_IP` may override that address in the frontend service for a different trusted proxy topology. It replaces forwarded headers before calling the backend. Uvicorn trusts that dedicated Compose network because the backend has no published host port. Do not attach untrusted containers to the application network or expose the backend directly. For multiple hosts or a different ingress network, explicitly review this trust boundary.

## Optional private DNS

Default networking inherits Docker/host DNS and permits backend access to ChatGPT/Claude and authorized external databases. If company database hostnames require explicit VPN/LAN resolvers, configure both `DOCKER_DNS_*` values, then use the same Compose files on every operation:

```bash
COMPOSE_FILE=compose.yaml:deploy/compose-dns.yaml bash deploy/docker/deploy.sh
docker compose -f compose.yaml -f deploy/compose-dns.yaml logs backend
```

The override affects the backend only. Office-only resolvers must be reachable from the deployment network; otherwise provider sign-in and web search can fail.
