# Deploy Duka Report Agent on a VPS without Docker

This guide runs the current application directly on **Ubuntu 24.04 LTS, x86-64**, using Python 3.12, Node 24, a systemd service, Nginx and HTTPS. No Docker daemon is needed on the target VPS. Commands are for a normal SSH deployment user with `sudo`, unless marked **local computer**.

Run commands in order and stop when any command fails; do not continue after a failed checksum, build, backup or configuration test.

Replace `reports.example.com`, `VPS_IP`, `YOUR_DEPLOY_COMMIT` and local paths before running commands. This is a production build, not the Vite development server.

## 1. Prepare the VPS and DNS

For modest use, start with 4 vCPUs, 16 GB RAM and at least 100 GB SSD. These are sizing estimates, not benchmarked guarantees. Large datasets, four concurrent workbook jobs and several native model processes can require more RAM; plan additional capacity and monitor growth.

Use an x86-64 VM and a kernel supporting **Landlock ABI 3+ and seccomp**. The app's calculation/workbook sandbox currently rejects unsupported platforms. Ubuntu 24.04's normal kernel is a suitable baseline; step 7 tests the actual environment. An ARM or restricted container-based VPS is not a compatible substitute.

Point the domain's DNS `A` record at the VPS IPv4 address. Only create an `AAAA` record if IPv6 works on this server.

```bash
ssh YOUR_SSH_USER@VPS_IP
sudo apt-get update
sudo apt-get install -y \
  ca-certificates curl git rsync xz-utils libgomp1 libstdc++6 \
  python3.12 python3.12-venv python3-pip \
  nginx certbot python3-certbot-nginx ufw
uname -m
uname -r
python3.12 --version
```

The architecture must be `x86_64`. Finish any required OS/kernel update and reboot before proceeding. Ubuntu 24.04 provides [Python 3.12 virtual environments](https://packages.ubuntu.com/noble/python3.12-venv); other distributions may need different package names or a separate Python installation.

Allow SSH and HTTPS/HTTP in the VPS provider firewall and the host firewall. If SSH uses a custom port, allow it before enabling UFW.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Do not open port 8080 publicly. The VPS needs outbound HTTPS/DNS for subscriptions and packages, plus authorized private/VPN routes to the actual SQL Server/HANA endpoints. Use the correct database ports and DNS resolvers for your environment.

## 2. Install Node 24 from the official distribution

The repository's Docker build uses Node 24. Use the same major version here. This example pins **24.22.0**, listed by the [official Node 24 release directory](https://nodejs.org/download/release/latest-v24.x/) when this guide was written. Review later 24.x security updates before upgrading; do not automatically jump to another major version.

Run this on a fresh server without an existing conflicting `/opt/node24` installation:

```bash
NODE_VERSION=v24.22.0
NODE_DOWNLOAD_DIR=$(mktemp -d)
cd "$NODE_DOWNLOAD_DIR"
curl -fsSLO "https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-x64.tar.xz"
curl -fsSLO "https://nodejs.org/dist/$NODE_VERSION/SHASUMS256.txt"
awk -v archive="node-$NODE_VERSION-linux-x64.tar.xz" '$2 == archive { print }' \
  SHASUMS256.txt | sha256sum --check --strict -
sudo install -d -m 0755 /opt/node24
sudo tar -xJf "node-$NODE_VERSION-linux-x64.tar.xz" --strip-components=1 -C /opt/node24
sudo ln -s /opt/node24/bin/node /usr/local/bin/node
sudo ln -s /opt/node24/bin/npm /usr/local/bin/npm
sudo ln -s /opt/node24/bin/npx /usr/local/bin/npx
node --version
npm --version
```

Proceed only after the checksum succeeds. If these symlinks already exist, inspect the current installation first rather than overwriting unrelated Node tools. Keep the `/opt/node24` path available to the systemd service after updates.

## 3. Create the service account and directory layout

Use separate accounts for deploying code and running the service:

```bash
sudo useradd --system --user-group --home-dir /var/lib/duka-agent --shell /usr/sbin/nologin duka
sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" /opt/duka-agent
sudo install -d -m 0700 -o duka -g duka /var/lib/duka-agent
sudo install -d -m 0750 -o root -g duka /etc/duka-agent
```

If the account already exists, inspect and reuse it rather than creating it again.

| Path | Contents | Ownership/access |
| --- | --- | --- |
| `/opt/duka-agent/app` | Application, frontend build and Python virtual environment | Deployment user; service can read/execute, not modify code |
| `/opt/duka-agent/codex` | Pinned Codex CLI installation | Deployment user; readable/executable by service |
| `/var/lib/duka-agent` | SQLite/WAL, users, grants, uploads, reports, keys, provider credentials/native histories and caches | `duka:duka`, private |
| `/etc/duka-agent/runtime.env` | Process settings and filesystem paths | `root:root`, mode 600; systemd reads it |
| `/etc/duka-agent/connections.env` | Backend-managed database credentials/profiles | `duka:duka`, mode 600; app must be able to write it |

The data directory is independent of the Git checkout, so code updates do not replace users, grants or subscription sessions.

## 4. Transfer the intended source version

Choose one method.

### Option A: Git

Commit and push the changes you intend to deploy first. A clone does not include the laptop's uncommitted work.

```bash
git clone https://github.com/pellumbmaraj/duka-report-ai-agent-v3.git /opt/duka-agent/app
cd /opt/duka-agent/app
git checkout --detach YOUR_DEPLOY_COMMIT
```

Use normal Git authentication for a private repository; do not embed a credential in the URL.

### Option B: Copy the working tree

On the VPS:

```bash
mkdir -p /opt/duka-agent/app
```

On the **local computer**, from the actual project directory:

```bash
rsync -av \
  --exclude='.git/' --exclude='.env' --exclude='.venv/' \
  --exclude='work/' --exclude='data/' --exclude='outputs/' \
  --exclude='node_modules/' --exclude='frontend/dist/' \
  --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.ruff_cache/' \
  ./ YOUR_SSH_USER@VPS_IP:/opt/duka-agent/app/
```

Keep code directories traversable by `duka` and source/build files readable. Private runtime data belongs in the paths from step 3, not in the code tree.

## 5. Install pinned dependencies and build the frontend

On the VPS, as the deployment user:

```bash
cd /opt/duka-agent/app
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r backend/requirements.txt
npm install --prefix /opt/duka-agent/codex --save-exact @openai/codex@0.162.1
npm --prefix frontend ci
npm --prefix frontend run build
```

`backend/requirements.txt` applies `backend/constraints.txt`. It installs the pinned Claude Agent SDK **0.2.168**, including its bundled CLI. A separate global Claude CLI, SQL Server ODBC driver and API key are not required. SQL Server uses `pymssql`; HANA uses `hdbcli`.

The UI has no recording controls, so this guide disables transcription. If you deliberately enable the optional legacy transcription service, install its pinned dependencies first:

```bash
.venv/bin/python -m pip install -r backend/requirements-voice.txt
```

Confirm the binaries are usable by the service account:

```bash
sudo -u duka /usr/local/bin/node --version
sudo -u duka /opt/duka-agent/codex/node_modules/.bin/codex --version
sudo -u duka /opt/duka-agent/app/.venv/bin/python -c \
  "import fastapi, uvicorn, pymssql, hdbcli, claude_agent_sdk; print('Python imports OK')"
sudo -u duka /opt/duka-agent/app/.venv/bin/python -c \
  "from pathlib import Path; import subprocess, claude_agent_sdk; subprocess.run([str(Path(claude_agent_sdk.__file__).parent / '_bundled' / 'claude'), '--version'], check=True)"
```

Never run the application service as root. Provider login will be performed through the app, not through the deployment user's separate CLI home.

## 6. Create separate runtime and connection configuration

Create `/etc/duka-agent/runtime.env`:

```bash
sudo tee /etc/duka-agent/runtime.env > /dev/null <<'EOF_RUNTIME'
DATA_DIR=/var/lib/duka-agent
FRONTEND_DIR=/opt/duka-agent/app/frontend/dist
REPORT_QUERY_DIR=/opt/duka-agent/app/backend/queries
ENV_FILE=/etc/duka-agent/connections.env
CODEX_BINARY=/opt/duka-agent/codex/node_modules/.bin/codex
ALLOWED_ORIGINS=https://reports.example.com
SECURE_COOKIES=true
SESSION_HOURS=24
VOICE_ENABLED=false
TURN_TIMEOUT_SECONDS=0
MAX_CODEX_RUNTIMES=4
MAX_CODEX_WORKERS=4
REPORT_MAX_ROWS=1000000
REPORT_MAX_BYTES=250000000
WORKBOOK_SCRIPT_TIMEOUT_SECONDS=300
WORKBOOK_SCRIPT_MEMORY_MB=4096
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
XDG_CACHE_HOME=/var/lib/duka-agent/cache
HF_HOME=/var/lib/duka-agent/speech-cache/huggingface
HF_XET_CACHE=/var/lib/duka-agent/speech-cache/xet
EOF_RUNTIME
sudo chown root:root /etc/duka-agent/runtime.env
sudo chmod 600 /etc/duka-agent/runtime.env
```

Replace the example domain. This file contains systemd-compatible process settings. Keep database secrets in the separate literal dotenv file below. The `ENV_FILE` variable tells the application where to read/write database profiles; it does **not** automatically load global process settings from that file.

For a **fresh installation only**:

```bash
if sudo test -e /etc/duka-agent/connections.env; then
  printf '%s\n' 'Existing connection file retained; do not replace its profiles.'
else
  sudo install -o duka -g duka -m 0600 /opt/duka-agent/app/.env.example /etc/duka-agent/connections.env
fi
```

If migrating, install the original project `.env` here instead, as described in step 11. Preserve every `DUKA_CONNECTION_...` binding and the matching data directory.

The backend writes connection changes in place. Do not make `connections.env` root-owned/read-only, and do not make it a symlink. Do not run the Docker ACL helper on this native installation; UID 10001 is a container-specific setting.

Do not `source connections.env`, copy its contents into `EnvironmentFile=`, or export all its keys. Backend dotenv parsing preserves literal passwords and multiline CA certificates. Configure database connections in the Devs Settings screen; keep TLS validation enabled and use the proper CA/server name when required.

`TURN_TIMEOUT_SECONDS=0` disables the model investigation wall-clock limit. The separate workbook-script timeout stays bounded to 300 seconds. Concurrency and memory values are per-process/job settings; tune them against actual VPS memory and load.

## 7. Check workbook isolation before starting the service

This credential-free check runs a child process under the service account, applies the real sandbox, and exits:

```bash
sudo -u duka env PYTHONPATH=/opt/duka-agent/app/backend \
  /opt/duka-agent/app/.venv/bin/python - <<'PY'
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(dir='/var/lib/duka-agent') as directory:
    subprocess.run([
        sys.executable, '-c',
        'from app.script_sandbox import isolate; import sys; '
        'isolate(sys.argv[1]); print("Workbook sandbox OK")', directory,
    ], check=True)
PY
```

If it fails, resolve the VPS/kernel compatibility issue. Do not bypass Landlock/seccomp. The model's native built-in shell, filesystem and agent tools remain disabled independently of this workbook sandbox.

## 8. Install the systemd service

Create `/etc/systemd/system/duka-agent.service`:

```bash
sudo tee /etc/systemd/system/duka-agent.service > /dev/null <<'EOF_SERVICE'
[Unit]
Description=Duka Report Agent
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=duka
Group=duka
WorkingDirectory=/opt/duka-agent/app
EnvironmentFile=/etc/duka-agent/runtime.env
Environment=PATH=/opt/duka-agent/app/.venv/bin:/opt/node24/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/duka-agent/app/.venv/bin/uvicorn app.main:app --app-dir /opt/duka-agent/app/backend --host 127.0.0.1 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --timeout-graceful-shutdown 20
Restart=on-failure
RestartSec=5
TimeoutStopSec=90
KillMode=control-group
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/duka-agent /etc/duka-agent/connections.env

[Install]
WantedBy=multi-user.target
EOF_SERVICE
sudo systemd-analyze verify /etc/systemd/system/duka-agent.service
sudo systemctl daemon-reload
```

Use **one Uvicorn worker and one service instance**. Native worker leases, per-chat cancellation and report scheduling are currently coordinated within one backend process; do not add Gunicorn worker pools or multiple replicas sharing this SQLite database.

The unit permits writes only to the private data directory, the managed connection file and its private temporary directory. Do not add `MemoryDenyWriteExecute=true` or an untested syscall filter: Node/native CLIs and the application's own sandbox setup must continue to work. The unit's normal operation is described by the [systemd service reference](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html).

If migrating, restore the existing workspace using step 11 **before the first service startup**. Otherwise:

```bash
sudo systemctl enable --now duka-agent
sudo systemctl status duka-agent --no-pager
sudo journalctl -u duka-agent -n 100 --no-pager
curl --fail http://127.0.0.1:8080/api/health
```

## 9. Configure Nginx and HTTPS

Create `/etc/nginx/sites-available/duka-agent`:

```bash
sudo tee /etc/nginx/sites-available/duka-agent > /dev/null <<'EOF_NGINX'
server {
    listen 80;
    server_name reports.example.com;
    client_max_body_size 64m;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        proxy_connect_timeout 15s;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF_NGINX
sudo ln -s /etc/nginx/sites-available/duka-agent /etc/nginx/sites-enabled/duka-agent
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
sudo certbot --nginx -d reports.example.com --redirect
sudo certbot renew --dry-run
curl --fail https://reports.example.com/api/health
```

Replace the domain before enabling the site. If it already exists, edit the existing configuration instead of making the symlink again. Complete Certbot's registration prompts yourself. DNS and port 80 must work for the usual HTTP certificate challenge.

Nginx proxies the built frontend and API through FastAPI; no separate frontend process is needed. Unbuffered NDJSON is necessary for live responses. The 3600-second timeout is an inactivity timeout, not a one-hour model-turn limit. A CDN/load balancer must also allow streaming, and the frontend can reconnect to its durable run if a connection drops. See the [Nginx proxy documentation](https://nginx.org/en/docs/http/ngx_http_proxy_module.html).

Sign in through HTTPS. With `SECURE_COOKIES=true`, an authenticated session intentionally does not work over plain HTTP. Verify that the backend itself is only listening on loopback:

```bash
sudo ss -ltnp | grep ':8080'
```

## 10. Set up and test the application

Open `https://reports.example.com`.

1. On a fresh database, create the first Devs account with your own password. For a migrated database, use the existing account rather than recreating members.
2. Open **Cilësimet → Modeli** and connect the shared ChatGPT and/or Claude subscriptions. Each additional subscription is a separate account; arrange its priority there.
3. Complete the provider's official device/OAuth sign-in. Do not authenticate a separate deployment-user CLI and assume the service will inherit it: the app maintains its own private provider homes.
4. Test each provider with a completed response. The app uses available model catalogs and subscription entitlements, not API keys. Automatic failover tries other same-provider accounts first; the cross-provider Claude target must actually be available to its subscription.
5. Configure SQL Server/HANA sources in Settings, with dedicated read-only database logins, correct VPN/DNS routing and TLS trust.
6. Assign Manager members explicit databases/companies. Devs and President have access to all registered databases/companies. Shared model credentials do not broaden a Manager's grants or share private chats.

During first-use setup, limit public access to your administration IP until the first Devs account exists, then allow the intended users.

Perform a small browser smoke test:

- Send `ca bone?` and verify the reply is Albanian.
- Use ChatGPT and Claude separately when connected.
- Create two chats, then reopen one; histories and native sessions must remain scoped correctly.
- Type and upload while a response is active, then send the new request. The old response should stop and the new one should finish.
- Stop a response while keeping an unsent draft, and verify that the draft remains.
- Create and download a small XLSX report. A successful health check alone does not test sandboxed export execution or database permissions.
- Sign in as a Manager and check the allowed databases/companies and restricted Settings access.
- After active work finishes, restart the service and confirm persistent chats, reports, users, grants and shared connections remain.

```bash
sudo systemctl restart duka-agent
curl --fail https://reports.example.com/api/health
```

## 11. Migrate the current workspace without losing users or grants

For a migration, do this before the first native service startup. Move the **entire original `DATA_DIR` and original project `.env`**. SQLite alone is insufficient: the matching uploads, snapshots, report files, keys and all provider credential/native-history directories are also needed.

### Export from the current Docker deployment

On the **local computer**, in the existing project, wait for active work to finish or stop it through the app:

```bash
umask 077
mkdir -p work/vps-transfer
chmod 700 work/vps-transfer
docker compose stop app
docker compose run --rm -T --no-deps --entrypoint tar app \
  -C /data -czf - . > work/vps-transfer/workspace-data.tar.gz
cp .env work/vps-transfer/project.env
tar -tzf work/vps-transfer/workspace-data.tar.gz > /dev/null
sha256sum work/vps-transfer/workspace-data.tar.gz > work/vps-transfer/workspace-data.sha256
scp work/vps-transfer/workspace-data.tar.gz work/vps-transfer/project.env \
  YOUR_SSH_USER@VPS_IP:/opt/duka-agent/
```

The **source laptop** uses Docker for this export; the target native VPS does not need Docker. Check that the archive command succeeds. Do not access the source volume from another process while archiving, and leave the old app stopped during cutover to avoid diverging histories.

If the source is already native, stop its service and archive its complete configured data directory with `tar -C ORIGINAL_DATA_DIR -czf ... .`, then copy its connection dotenv file instead.

### Restore on the native VPS

Use the empty data directory prepared in step 3. Do not merge two existing workspaces. If the target already has data, stop the service and move that directory aside first, retaining a backup, then create a new empty directory.

```bash
chmod 600 /opt/duka-agent/project.env /opt/duka-agent/workspace-data.tar.gz
sudo systemctl stop duka-agent
sudo tar --no-same-owner -xzf /opt/duka-agent/workspace-data.tar.gz -C /var/lib/duka-agent
sudo chown -R duka:duka /var/lib/duka-agent
sudo chmod 700 /var/lib/duka-agent
sudo install -o duka -g duka -m 0600 /opt/duka-agent/project.env /etc/duka-agent/connections.env
sudo systemctl enable --now duka-agent
sudo systemctl status duka-agent --no-pager
```

The systemd runtime file must retain the new paths and HTTPS origin from step 6; do not replace it with the old Docker `.env`. Backend-managed `DUKA_CONNECTION_...` entries stay in `connections.env` unchanged.

Container UID 10001 becomes the native `duka` user's ownership during this restore. Native provider histories may contain old `/data/...` paths; the app resumes/rebuilds context with the native workspace paths where possible. Verify an existing chat with each provider, and reconnect a subscription in Settings if its session requires renewal. Do not delete native homes to fix a sign-in issue.

Keep the original encrypted credential key even when current connections use dotenv profiles. Keep the migration archive private until the VPS is verified, and retain an off-server backup afterward.

## 12. Back up and update the native deployment

After active chats/reports finish, take a stopped-service backup. This includes private data, configuration, and the installed code/runtimes so rollback can restore the same absolute virtual-environment paths.

```bash
umask 077
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="/opt/duka-agent/backups/$STAMP"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
sudo systemctl stop duka-agent
sudo tar -C /var/lib/duka-agent -czf - . > "$BACKUP_DIR/workspace-data.tar.gz"
sudo tar -C /etc -czf - duka-agent > "$BACKUP_DIR/configuration.tar.gz"
sudo tar -C /opt/duka-agent --exclude='app/frontend/node_modules' \
  -czf - app codex > "$BACKUP_DIR/application.tar.gz"
sudo cp /etc/systemd/system/duka-agent.service "$BACKUP_DIR/duka-agent.service"
tar -tzf "$BACKUP_DIR/workspace-data.tar.gz" > /dev/null
tar -tzf "$BACKUP_DIR/configuration.tar.gz" > /dev/null
tar -tzf "$BACKUP_DIR/application.tar.gz" > /dev/null
sha256sum "$BACKUP_DIR/"*.tar.gz > "$BACKUP_DIR/SHA256SUMS"
```

Verify each command succeeds before updating. Do not modify the stopped data directory while archiving. SQLite uses WAL: copying a live `.sqlite3` file alone can miss committed records. Copy these backups to encrypted off-server storage and keep a retention policy with enough free disk space.

While the service is still stopped, update the code using the selected transfer method. For Git installations:

```bash
cd /opt/duka-agent/app
git fetch origin
git checkout --detach YOUR_NEW_DEPLOY_COMMIT
.venv/bin/python -m pip install -r backend/requirements.txt
npm install --prefix /opt/duka-agent/codex --save-exact @openai/codex@0.162.1
npm --prefix frontend ci
npm --prefix frontend run build
sudo systemd-analyze verify /etc/systemd/system/duka-agent.service
sudo systemctl daemon-reload
sudo systemctl start duka-agent
sudo systemctl status duka-agent --no-pager
curl --fail https://reports.example.com/api/health
```

Use the CLI/SDK versions specified by the selected release if they change later; do not upgrade only the provider SDK or native CLI independently. Keep `runtime.env`, `connections.env` and `/var/lib/duka-agent` in place. Startup applies database migrations automatically. Run the browser smoke tests after updating.

### Rollback or restore

Stop the service and preserve the failed deployment first. Restore the saved application archive to `/opt/duka-agent`, configuration to `/etc`, and the saved unit to `/etc/systemd/system/duka-agent.service`. Extract into empty/moved-aside target directories rather than layering old code over new files. The restored virtual environment must stay at `/opt/duka-agent/app/.venv`.

If the failed release changed the schema incompatibly, also restore the matching pre-upgrade data archive to an empty `/var/lib/duka-agent` and its matching connection configuration. Older code is not guaranteed to downgrade a newer schema. Restore data ownership with `sudo chown -R duka:duka /var/lib/duka-agent`; `connections.env` must be owned by `duka` with mode 600. Then verify the unit, run `daemon-reload`, start the service and repeat health/browser checks.

The host Node installation, Nginx site and TLS certificates are managed separately; preserve their configuration as part of your VPS backup plan.

## 13. Troubleshooting

| Symptom | Check |
| --- | --- |
| Service will not start | `sudo journalctl -u duka-agent -n 100 --no-pager`; verify paths, Python imports, readable frontend build, runtime file and writable data/connection paths. |
| `codex` or `node` not found | Absolute `CODEX_BINARY`, Node symlinks and the systemd `PATH`; test as `duka`, not only as the SSH user. |
| Claude executable missing | Install the pinned SDK in this exact virtual environment and check its bundled CLI using step 5. |
| Settings changes are ignored | Global settings belong in `runtime.env` and require a service restart; database profiles belong in the configured writable `connections.env`. |
| Database settings cannot be saved | `duka` owns `connections.env` and can write it; systemd `ReadWritePaths` includes that exact file. |
| Repeated sign-in or 403 | Correct HTTPS URL, secure cookies, exact allowed origin and Nginx forwarded headers. |
| Replies stream in one batch | Disable proxy/CDN buffering and check the streaming proxy configuration. |
| SQL Server/HANA is unreachable | VPN/routing, DNS, authorized source IP, port, SELECT permissions and TLS certificate trust. Do not turn off certificate checks as a general fix. |
| XLSX isolation fails | Kernel/architecture and the sandbox preflight; remove conflicting service restrictions rather than disabling application isolation. |
| Process killed or disk full | RAM, worker concurrency, workbook limits, SQLite/history growth, large uploads and backup retention. |
| Existing workspace appears empty | Correct `DATA_DIR` and complete restored data. Stop before creating replacement users; check the original path/archive. |

Keep service logs, connection files, archives and provider homes private. Ordinary access logs and provider stderr are already suppressed; raw authentication logging is not needed for normal operation.
