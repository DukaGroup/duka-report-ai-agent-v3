# VPS deployment without Docker

Use **Ubuntu 24.04, x86-64**, with its standard kernel (report isolation needs Landlock ABI 3+ and seccomp). Run commands over SSH with `sudo` available.

Application files live under `/var/www/duka-agent`; persistent data lives under `/var/lib/duka-agent`. The setup scripts install the supplied service and Nginx files into their standard `/etc` locations.

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

Create the service user and directories, then clone your repository, including your committed `.env`.

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
.venv/bin/pip install -r backend/requirements.txt
npm install --prefix /var/www/duka-agent/codex --save-exact @openai/codex@0.162.1
npm --prefix frontend ci
npm --prefix frontend run build
```

## 3. Set your domain and environment

Edit the repository's `.env`, retaining your database settings and setting these production values:

```dotenv
ALLOWED_ORIGINS=https://reports.example.com
SECURE_COOKIES=true
VOICE_ENABLED=false
TURN_TIMEOUT_SECONDS=0
MAX_CODEX_RUNTIMES=4
MAX_CODEX_WORKERS=4
```

Replace `reports.example.com` in `.env` and [deploy/nginx.conf](../deploy/nginx.conf) with your domain. Point the domain's DNS to the VPS. The service reads `.env` directly; no separate environment file is needed.

Give the service access to read and update database settings in `.env`:

```bash
sudo chown "$(id -un)":duka .env
sudo chmod 660 .env
```

**Existing workspace:** before starting the service, restore the complete previous data archive into the empty data directory. Keep the original connection entries in `.env` to preserve members, grants, reports and subscription connections.

```bash
sudo tar --no-same-owner -xzf /path/to/workspace-data.tar.gz -C /var/lib/duka-agent
sudo chown -R duka:duka /var/lib/duka-agent
sudo chmod 700 /var/lib/duka-agent
```

Skip that restore block for a fresh workspace.

## 4. Start the service

The configuration is in [deploy/duka-agent.service](../deploy/duka-agent.service). This script installs it, starts/restarts the app and enables startup after reboot:

```bash
sudo bash deploy/install-service.sh
```

## 5. Enable Nginx and HTTPS

The configuration is in [deploy/nginx.conf](../deploy/nginx.conf). This script installs it, reloads Nginx, obtains the HTTPS certificate and checks app health. Follow Certbot's prompts.

```bash
sudo bash deploy/setup-nginx.sh
```

## 6. Open the app

Open `https://YOUR_DOMAIN`. For a fresh workspace, create the first Devs account. In **Cilësimet**, connect ChatGPT/Claude and configure database sources. The VPS must be able to reach your database servers.

For system notifications, each member enables **Cilësimet → Pamja → Njoftimet e pajisjes** on their device and allows the browser prompt. HTTPS is required; on iPhone/iPad, open the app from its Home Screen shortcut. Back up the complete data directory, including `web-push-private.pem`, to keep existing notification connections working.

```bash
# Check the service.
sudo systemctl status duka-agent --no-pager
# Read recent errors.
sudo journalctl -u duka-agent -n 50 --no-pager
# Restart after changing .env or updating the app.
sudo systemctl restart duka-agent
```

Keep `/var/lib/duka-agent` and `.env` backed up. Stop the service before copying its data. After Git updates, retain server-side `.env` changes and repeat its permission commands if the file was replaced.
