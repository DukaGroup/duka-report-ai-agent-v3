# VPS deployment without Docker

Use **Ubuntu 24.04, x86-64**, with its standard kernel (the report sandbox needs Landlock ABI 3+ and seccomp). Run these steps over SSH as a user with `sudo`.

Replace `reports.example.com` with your domain and point its DNS to the VPS. Push the latest application code before cloning it.

## 1. Install dependencies

Install Python, Nginx, HTTPS tools and Node 24 using the [NodeSource repository](https://github.com/nodesource/distributions/blob/master/DEV_README.md#debian-and-ubuntu-based-distributions).

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git libgomp1 libstdc++6 \
  python3.12 python3.12-venv nginx certbot python3-certbot-nginx ufw
curl -fsSL https://deb.nodesource.com/setup_24.x -o node24-setup.sh
sudo bash node24-setup.sh
sudo apt-get install -y nodejs
```

## 2. Install the application

Create a dedicated service user and private data directories, then download the code.

```bash
sudo useradd --system --user-group --home-dir /var/lib/duka-agent --shell /usr/sbin/nologin duka
sudo install -d -o "$(id -un)" -g "$(id -gn)" /opt/duka-agent
sudo install -d -o duka -g duka -m 700 /var/lib/duka-agent /etc/duka-agent
git clone https://github.com/pellumbmaraj/duka-report-ai-agent-v3.git /opt/duka-agent/app
cd /opt/duka-agent/app
```

Install backend dependencies, the pinned Codex CLI and the production frontend. The Claude CLI comes with the Python dependencies.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
npm install --prefix /opt/duka-agent/codex --save-exact @openai/codex@0.162.1
npm --prefix frontend ci
npm --prefix frontend run build
```

## 3. Configure the application

Write runtime settings. Database credentials use a separate writable file managed by the app.

```bash
sudo tee /etc/duka-agent/runtime.env > /dev/null <<'EOF_RUNTIME'
DATA_DIR=/var/lib/duka-agent
FRONTEND_DIR=/opt/duka-agent/app/frontend/dist
REPORT_QUERY_DIR=/opt/duka-agent/app/backend/queries
ENV_FILE=/etc/duka-agent/connections.env
CODEX_BINARY=/opt/duka-agent/codex/node_modules/.bin/codex
ALLOWED_ORIGINS=https://reports.example.com
SECURE_COOKIES=true
VOICE_ENABLED=false
TURN_TIMEOUT_SECONDS=0
MAX_CODEX_RUNTIMES=4
MAX_CODEX_WORKERS=4
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
EOF_RUNTIME
sudo chmod 600 /etc/duka-agent/runtime.env
sudo -u duka touch /etc/duka-agent/connections.env
sudo chmod 600 /etc/duka-agent/connections.env
```

**Moving an existing workspace?** Before starting the service, restore its complete data archive and original `.env` into the empty installation. This preserves members, grants, conversations, reports and subscription credentials. Replace the two archive/file paths below; skip this block for a fresh workspace.

```bash
sudo tar --no-same-owner -xzf /path/to/workspace-data.tar.gz -C /var/lib/duka-agent
sudo chown -R duka:duka /var/lib/duka-agent
sudo chmod 700 /var/lib/duka-agent
sudo install -o duka -g duka -m 600 /path/to/original.env /etc/duka-agent/connections.env
```

## 4. Start the service

Run one backend worker as `duka`, with automatic startup and restart after failures.

```bash
sudo tee /etc/systemd/system/duka-agent.service > /dev/null <<'EOF_SERVICE'
[Unit]
Description=Duka Report Agent
Wants=network-online.target
After=network-online.target

[Service]
User=duka
Group=duka
WorkingDirectory=/opt/duka-agent/app
EnvironmentFile=/etc/duka-agent/runtime.env
Environment=PATH=/opt/duka-agent/app/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/duka-agent/app/.venv/bin/uvicorn app.main:app --app-dir /opt/duka-agent/app/backend --host 127.0.0.1 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1 --no-access-log --timeout-graceful-shutdown 20
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
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
sudo systemctl enable --now duka-agent
```

## 5. Enable Nginx and HTTPS

Forward requests to the backend. Disabling buffering allows replies to stream normally.

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
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
EOF_NGINX
sudo ln -s /etc/nginx/sites-available/duka-agent /etc/nginx/sites-enabled/duka-agent
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

Allow SSH and web traffic, then obtain an HTTPS certificate. If SSH uses a custom port, allow that port before enabling the firewall. Also allow ports 80/443 in your VPS provider's firewall.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo certbot --nginx -d reports.example.com --redirect
curl --fail https://reports.example.com/api/health
```

## 6. Open the app

Open `https://reports.example.com`. For a fresh workspace, create the first Devs account. In **Cilësimet**, connect ChatGPT/Claude and configure database connections. The VPS must be able to reach those database servers, including any required VPN.

Useful service commands:

```bash
# Check whether the app is running.
sudo systemctl status duka-agent --no-pager
# Read recent errors.
sudo journalctl -u duka-agent -n 50 --no-pager
# Restart after changing runtime settings or updating the app.
sudo systemctl restart duka-agent
```

Keep `/var/lib/duka-agent` and `/etc/duka-agent` backed up. Stop the service before copying its data; keep these directories when updating the code.
