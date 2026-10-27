# VPS deployment without Docker

For **hana.dukagroup.local with an existing certificate, private key and `.p7b` chain**, use the [Hana internal deployment guide](deploy-hana-internal.md). It runs the frontend and backend without Docker and uses company-issued certificates instead of Certbot.

Use **Ubuntu 24.04, x86-64**, with its standard kernel (report isolation needs Landlock ABI 3+ and seccomp). Run commands over SSH with `sudo` available.

If a step fails, use [VPS troubleshooting](deploy-troubleshooting.md) for database routing/VPN, certificates, native drivers, and service errors.

Application files live under `/var/www/duka-agent`; persistent data lives under `/var/lib/duka-agent`. The setup scripts install the supplied service and Nginx files into their standard `/etc` locations. For container deployment, use the separate [Docker guide](deploy-with-docker.md).

## Frontend and backend responsibilities

| Component | Location and process |
| --- | --- |
| Frontend source/build | `frontend/` → `frontend/dist/`; served directly by Nginx |
| Backend source/runtime | `backend/`; `duka-agent.service` runs the Python API on `127.0.0.1:8080` |
| Browser routing | Nginx serves the site and forwards only `/api/` to the backend |
| Persistent data | `/var/lib/duka-agent/`; owned by the backend service user |
| Private configuration | `/var/lib/duka-agent/runtime.env`; never served by Nginx |

Both components use one HTTPS origin, preserving existing login cookies and relative API URLs. Native Nginx configuration lives in `deploy/nginx-https.conf`; the backend service is configured independently in `deploy/duka-agent.service`.

## 1. Install dependencies

Install Python, Nginx, HTTPS tools and Node 24.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git libgomp1 libstdc++6 \
  python3.12 python3.12-venv nginx certbot python3-certbot-nginx
curl -fsSL https://deb.nodesource.com/setup_24.x -o node24-setup.sh
sudo bash node24-setup.sh
sudo apt-get install -y nodejs
```

## 2. Install the application

Create the service user and directories, then clone the code. Credentials and financial files are excluded from Git.

```bash
sudo useradd --system --user-group --home-dir /var/lib/duka-agent --shell /usr/sbin/nologin duka
sudo install -d -o "$(id -un)" -g "$(id -gn)" /var/www/duka-agent
sudo install -d -o duka -g duka -m 700 /var/lib/duka-agent
git clone https://github.com/pellumbmaraj/duka-report-ai-agent-v3.git /var/www/duka-agent/app
cd /var/www/duka-agent/app
```

Install the backend, Codex CLI and production frontend. Claude's CLI comes with the backend dependencies.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip==26.2
.venv/bin/pip install -r backend/requirements.txt
npm install --prefix /var/www/duka-agent/codex --save-exact @openai/codex@0.162.1
npm --prefix frontend ci
npm --prefix frontend run build
```

## 3. Set your domain and environment

**Moving an existing workspace:** first use [backup and restore](backup-and-restore.md). Restore its complete data and environment; do not create another workspace or recreate grants.

Prepare the private environment, then edit it. The script copies an existing project `.env` unchanged when available, otherwise it uses the example. It never overwrites an existing `runtime.env`.

```bash
sudo bash deploy/prepare-env.sh
sudoedit /var/lib/duka-agent/runtime.env
```

Retain your database settings and use these production values:

```dotenv
ALLOWED_ORIGINS=https://reports.example.com
SECURE_COOKIES=true
APP_ENV=production
VOICE_ENABLED=false
TURN_TIMEOUT_SECONDS=0
MAX_CODEX_RUNTIMES=4
MAX_CODEX_WORKERS=4
```

Replace `server_name reports.example.com` in [deploy/nginx.conf](../deploy/nginx.conf) with the same domain and point its DNS to the VPS. Only edit `server_name`; the HTTPS script fills the other locations. App-saved settings also update `/var/lib/duka-agent/runtime.env`, owned by `duka` with mode `600`.

## 4. Start the service

This checks production settings, installs [the service](../deploy/duka-agent.service), starts it and enables startup after reboot:

```bash
sudo bash deploy/install-service.sh
```

## 5. Enable Nginx and HTTPS

The following Certbot flow is for public DNS domains only. For internal `.local` domains or supplied company certificates, use `deploy/setup-provided-https.sh` as documented in the [internal guide](deploy-hana-internal.md).

This obtains the HTTPS certificate, installs the HTTPS proxy and renewal hook, and checks health. Follow Certbot's prompts. HTTP never proxies authenticated app traffic.

```bash
sudo bash deploy/setup-nginx.sh
```

## 6. Open the app

Open `https://YOUR_DOMAIN`. A **fresh workspace** requires the one-time code from this server command when creating the first Devs account:

```bash
sudo cat /var/lib/duka-agent/workspace-setup.token
```

The code file is removed after setup. Existing workspaces retain their users and never ask for this code. In **Cilësimet**, connect ChatGPT/Claude and configure sources. The VPS must reach the database servers. Production requires verified database TLS; configure a private company CA only if needed, as described in [troubleshooting](deploy-troubleshooting.md).

For system notifications, each member enables **Cilësimet → Pamja → Njoftimet e pajisjes** on their device and allows the browser prompt. HTTPS is required; on iPhone/iPad, open the app from its Home Screen shortcut. Back up the complete data directory, including `web-push-private.pem`, to keep existing notification connections working.

```bash
# Check the service.
sudo systemctl status duka-agent --no-pager
# Read recent errors.
sudo journalctl -u duka-agent -n 50 --no-pager
# Restart after changing production settings or updating the app.
sudo systemctl restart duka-agent
```

Create encrypted backups with `sudo bash deploy/backup.sh` and keep the separate key safe; see [backup and restore](backup-and-restore.md). On an older server still using a tracked `.env`, save a private copy **before pulling the cleanup commit**:

```bash
sudo test -e /var/lib/duka-agent/runtime.env || sudo install -o duka -g duka -m 600 .env /var/lib/duka-agent/runtime.env
```

After updating the code, rerun steps 4 and 5. Keep Ubuntu security updates current.

## Update one component

For a frontend-only change, run `npm --prefix frontend ci` and `npm --prefix frontend run build`. Nginx serves the new static files immediately; the backend and data volume do not need to restart. HTML and service-worker caching rules permit clients to pick up the new build. When changing Nginx configuration itself, rerun `deploy/setup-nginx.sh`.

For backend changes, install `backend/requirements.txt` when dependencies change and restart `duka-agent` after active chats/reports finish. Existing users, grants, conversations and reports remain under `/var/lib/duka-agent`. The backend deliberately has no frontend directory in production; use the public Nginx address to open the site.
