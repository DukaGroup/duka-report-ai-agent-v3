# Deploy Duka Report Agent on a VPS with Docker

This guide installs the current application on **Ubuntu 24.04 LTS, x86-64**, using Docker Compose, Nginx and HTTPS. Commands are for a normal SSH user with `sudo`, unless marked **local computer**. Replace `reports.example.com`, `VPS_IP`, `YOUR_DEPLOY_COMMIT` and local paths before running commands.

Run the commands in order and stop if a command fails; do not continue past a failed build, checksum, backup or configuration test.

The example installation directory is `/opt/duka-agent/app`. The application stays on `127.0.0.1:8080`; Nginx serves the public website. Do not expose port 8080 publicly.

## 1. Prepare the VPS and domain

Start with a VM offering 4 vCPUs, 16 GB RAM and at least 100 GB SSD for modest use. These are starting estimates, not measured capacity guarantees; large exports and concurrent model processes can need more RAM and storage. Monitor the database, uploads, native histories, reports and backups as they grow.

Use an x86-64 VM with a distribution kernel supporting **Landlock ABI 3+ and seccomp**. Ubuntu 24.04's normal kernel is a suitable starting point; the sandbox check below verifies the actual VPS. Docker shares the host kernel. An ARM VPS or a restricted container-based VPS does not satisfy this application's current workbook isolation requirements.

Point the domain's DNS `A` record at the VPS IPv4 address. Add an `AAAA` record only if IPv6 actually reaches this server.

Connect and install host utilities:

```bash
ssh YOUR_SSH_USER@VPS_IP
sudo apt-get update
sudo apt-get install -y ca-certificates curl git rsync acl nginx certbot python3-certbot-nginx ufw
uname -m
uname -r
```

`uname -m` must show `x86_64`. If the server needs OS updates or a reboot, complete those before deployment.

Allow SSH and web traffic in both the VPS provider firewall and the host firewall. If SSH uses a custom port, allow that port before enabling UFW.

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

The VPS also needs outbound HTTPS/DNS for provider authentication, model requests and package installation, plus private/VPN routes to the configured SQL Server or HANA endpoints. Database servers should allow the VPS's authorized address. Use the actual database ports; SQL Server commonly uses 1433, while HANA ports depend on the instance and tenant.

## 2. Install Docker Engine and Compose

On a fresh VPS without a conflicting Docker/containerd installation:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF_DOCKER_APT
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF_DOCKER_APT
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker version
sudo docker compose version
sudo docker run --rm hello-world
```

For an existing container host, follow the [official Docker installation guide](https://docs.docker.com/engine/install/ubuntu/) for conflicting packages before changing its engine. This guide uses `sudo docker`; membership in the Docker group is unnecessary.

## 3. Put the correct application version on the server

Create the parent directory, owned by your SSH deployment user:

```bash
sudo install -d -m 0755 -o "$(id -un)" -g "$(id -gn)" /opt/duka-agent
```

Choose one transfer method.

### Option A: Git

First commit and push the version you intend to deploy. Local uncommitted changes are not included in a clone.

```bash
git clone https://github.com/pellumbmaraj/duka-report-ai-agent-v3.git /opt/duka-agent/app
cd /opt/duka-agent/app
git checkout --detach YOUR_DEPLOY_COMMIT
```

Use your normal Git authentication if the repository is private; do not put a token in the clone URL.

### Option B: Copy the current working tree

On the VPS:

```bash
mkdir -p /opt/duka-agent/app
```

On your **local computer**, from the actual project directory:

```bash
rsync -av \
  --exclude='.git/' --exclude='.env' --exclude='.venv/' \
  --exclude='work/' --exclude='data/' --exclude='outputs/' \
  --exclude='node_modules/' --exclude='frontend/dist/' \
  --exclude='__pycache__/' --exclude='.pytest_cache/' --exclude='.ruff_cache/' \
  ./ YOUR_SSH_USER@VPS_IP:/opt/duka-agent/app/
```

Application data and credentials are migrated separately in step 10. Do not mix the source-code transfer with private data transfer.

## 4. Create production configuration

On the VPS:

```bash
cd /opt/duka-agent/app
```

For a **fresh workspace only**:

```bash
if [ -e .env ]; then
  printf '%s\n' 'Existing .env retained; review it instead of replacing it.'
else
  cp .env.example .env
  chmod 600 .env
fi
```

If retaining the current workspace, use its existing `.env` and data archive from step 10 instead. Do not replace existing `DUKA_CONNECTION_...` entries or database passwords with template values.

Edit `.env` using an editor. Add/update these settings, with one occurrence of each key:

```dotenv
COMPOSE_PROJECT_NAME=duka-agent
PORT=8080
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
DOCKER_DNS_PRIMARY=1.1.1.1
DOCKER_DNS_SECONDARY=1.0.0.1
```

Use your VPN/private DNS resolvers instead of the two public DNS addresses if database hostnames require them. The model timeout of `0` allows investigations to continue until completion or Stop. The 300-second workbook-script limit is a separate execution boundary and remains in place.

The example reduces concurrent native processes from the repository default; size these limits to your server. Workbook memory limits apply per job, not to the whole service. Recording controls are absent, so transcription can remain disabled; the image still installs its pinned optional packages.

Grant the container's backend UID 10001 write access to this one configuration file:

```bash
bash scripts/allow-env-write.sh
getfacl .env
```

The backend saves database connection changes into this file. Keep it a regular writable file, not a symlink, and keep the Compose bind mount writable. Do not run `chmod 600 .env` again after the ACL helper: that would remove its effective container access. Rerun the helper if an editor replaces the file, then recreate the container.

**Do not `source .env` or export its entire contents.** It contains literal database passwords and may contain multiline certificate values. Docker Compose reads its supported dotenv syntax; the backend parses managed connection profiles without interpolation. Single-quote manually entered literal passwords containing `$` in this file.

## 5. Build and check the application sandbox

```bash
cd /opt/duka-agent/app
sudo docker compose build app
```

The repository image already pins Node 24, Python 3.12, Codex `0.162.1`, and Claude Agent SDK `0.2.168`. No host Python, Node, SQL Server ODBC installation or separate Claude CLI installation is needed.

Run a credential-free sandbox check inside the same Compose restrictions:

```bash
sudo docker compose run --rm -T --no-deps --entrypoint python app - <<'PY'
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory(dir='/data') as directory:
    subprocess.run([
        sys.executable, '-c',
        'from app.script_sandbox import isolate; import sys; '
        'isolate(sys.argv[1]); print("Workbook sandbox OK")', directory,
    ], check=True)
PY
```

If this fails, use a VPS/kernel that supports the required isolation. Do not resolve it by disabling the workbook sandbox or adding privileged mode.

If migrating existing data, restore it now using step 10, **before starting the app for the first time**.

Start and check the backend:

```bash
sudo docker compose up -d app
sudo docker compose ps
sudo docker compose logs --tail=100 app
curl --fail http://127.0.0.1:8080/api/health
```

There must be **one application container and one Uvicorn worker**. Native worker leases, cancellation and report scheduling currently rely on one backend process. Do not add `--workers 2`, Gunicorn worker pools, or a second app replica against the same SQLite volume.

## 6. Configure Nginx for streaming responses

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
```

Replace the domain in the file. If the symlink already exists, edit the existing site instead of creating it again. These proxy settings stream NDJSON events without buffering. The read timeout measures inactivity between reads, not the total allowed investigation time. Any CDN/load balancer in front must also support unbuffered streaming; a disconnected browser can reconnect to the durable response.

See the [Nginx proxy module reference](https://nginx.org/en/docs/http/ngx_http_proxy_module.html) for these directives.

## 7. Enable HTTPS before creating accounts

Once DNS points to the VPS and port 80 is reachable:

```bash
sudo certbot --nginx -d reports.example.com --redirect
sudo certbot renew --dry-run
curl --fail https://reports.example.com/api/health
```

Complete Certbot's email/registration prompts yourself. Use the HTTPS URL for all normal sign-ins: `SECURE_COOKIES=true` intentionally prevents a working authenticated session over plain HTTP. The loopback health endpoint remains usable without signing in.

Check that 8080 is only bound to loopback:

```bash
sudo ss -ltnp | grep ':8080'
```

## 8. Configure the workspace in the browser

Open `https://reports.example.com`.

1. On an empty installation, create the first Devs member with your own strong password. On a migrated installation, sign in with the existing account; do not recreate users.
2. In **Cilësimet → Modeli**, connect the shared ChatGPT and/or Claude subscriptions. Add each additional subscription as its own account and set the desired order.
3. Complete ChatGPT's device-code login on the official provider page. For Claude, follow its official login URL and return the single-use code to the app.
4. Use the actual available model catalog. There is no API-key fallback. Same-provider accounts are attempted before switching providers; cross-provider Claude fallback requires the configured Opus 5.5 target to be available to that account.
5. In Settings, configure the SQL Server/HANA sources with dedicated read-only database logins. Preserve certificate verification and provide the correct trusted CA when required.
6. Assign Manager members database/company access with the existing checkboxes. Devs and President have all registered database/company access. Shared model subscriptions do not share members' private chats or broaden their grants.

No model subscription login belongs in `.env`. Credentials and native histories persist under the data volume. Sign in again through the app if a migrated provider session requires renewal; do not delete the data volume to fix login.

For first-use setup on a public hostname, keep access limited to your administration IP until the first Devs account has been created, then open access to the intended members.

## 9. Verify the deployment

Perform these checks with a small, clearly identified test chat:

- Send `ca bone?`; the model should answer in Albanian.
- Test each connected provider separately; a connection indicator alone does not prove successful inference.
- Create two chats, send a message in each, and reopen one. Their model sessions must stay separate while reopening retains the chat history.
- During a response, type/upload the next message and send it. The old response should stop and the new one should complete. Check that an unsent draft survives Stop.
- Create a small report and download the XLSX; a health response does not verify sandboxed report execution or database connectivity.
- Sign in as a Manager and verify the granted databases/companies and restricted Settings access.
- Restart the container after active work finishes, then confirm users, grants, chats, reports and subscriptions remain.

```bash
cd /opt/duka-agent/app
sudo docker compose restart app
sudo docker compose ps
curl --fail https://reports.example.com/api/health
```

## 10. Migrate the current laptop/workspace instead of starting empty

This is optional for a fresh installation. For a migration, do it before the first VPS startup. Preserve **the entire data directory plus the original `.env`**, not just SQLite or an Excel export. This retains users, grants, reports, uploads, calculation evidence, keys and every subscription's native history.

On the **local computer**, in the existing Docker project, wait for active chats/reports to finish or stop them from the app. Then:

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

Check the archive command exits successfully before transferring it. Do not access or start another container against that data volume while the archive runs. Leave the old app stopped during cutover so two copies do not develop different histories.

On the VPS, secure the transfer files and install the original environment file into the new project directory:

```bash
chmod 600 /opt/duka-agent/project.env /opt/duka-agent/workspace-data.tar.gz
cd /opt/duka-agent/app
(
  if [ -e .env ]; then
    printf '%s\n' 'STOP: .env already exists. Back it up and resolve which workspace to restore.' >&2
    exit 1
  fi
  cp /opt/duka-agent/project.env .env
)
```

Continue only once `.env` is the original file for the archive being restored. Edit only the VPS-specific application settings from step 4, preserving database profiles and passwords. Set `COMPOSE_PROJECT_NAME=duka-agent`, the public HTTPS origin and secure cookies, then run the ACL helper.

Build the image, create the container/empty volume without starting it, and restore:

```bash
bash scripts/allow-env-write.sh
sudo docker compose build app
sudo docker compose create app
sudo docker compose run --rm -T --no-deps --entrypoint tar app \
  --no-same-owner -C /data -xzf - < /opt/duka-agent/workspace-data.tar.gz
sudo docker compose up -d app
```

Restore into an **empty** volume. If this project has already held data on this VPS, preserve it separately and choose a new unique `COMPOSE_PROJECT_NAME` before creating a replacement volume; do not merge two workspaces. Keep that project name for every later operation.

The restore maps ownership to container UID 10001. Both the source and target paths are `/data`, which also keeps native session paths consistent. If the source deployment is native rather than Docker, archive its entire configured `DATA_DIR` with the service stopped; the same restore command applies, but native sessions may need to be rebuilt or reauthenticated after a path change.

After verifying the VPS, retain the old private backup until the deployment has been accepted. Do not publish archives, `.env`, `auth.json`, or subscription directories.

## 11. Backups and updates

Run all commands from `/opt/duka-agent/app`. Keep the Compose project name constant. Back up to a private path outside the code checkout, then copy the backup to encrypted storage on another host.

After active work has finished:

```bash
cd /opt/duka-agent/app
umask 077
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR="/opt/duka-agent/backups/$STAMP"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
IMAGE_ID=$(sudo docker inspect --format '{{.Image}}' "$(sudo docker compose ps -q app)")
sudo docker image tag "$IMAGE_ID" "duka-agent-app:rollback-$STAMP"
printf '%s\n' "$IMAGE_ID" > "$BACKUP_DIR/image-id.txt"
sudo docker compose stop app
sudo docker compose run --rm -T --no-deps --entrypoint tar app \
  -C /data -czf - . > "$BACKUP_DIR/workspace-data.tar.gz"
cp .env "$BACKUP_DIR/project.env"
cp compose.yaml "$BACKUP_DIR/compose.yaml"
tar -tzf "$BACKUP_DIR/workspace-data.tar.gz" > /dev/null
sha256sum "$BACKUP_DIR/workspace-data.tar.gz" > "$BACKUP_DIR/workspace-data.sha256"
```

If any backup command fails, resolve it before upgrading. Keep all volume access stopped during the archive. SQLite uses WAL; copying only `application.sqlite3` while the app is running is not a complete backup. Do not stage a large SQLite backup in the container's 256 MB `/tmp`.

For Git-based installs, fetch and select the intended release; for copied working trees, transfer the new source files instead. Keep `.env` and the data volume intact.

```bash
git fetch origin
git checkout --detach YOUR_NEW_DEPLOY_COMMIT
bash scripts/allow-env-write.sh
sudo docker compose build app
sudo docker compose up -d app
sudo docker compose ps
curl --fail https://reports.example.com/api/health
```

Run the browser smoke tests again. Schema migrations happen at startup. New source code alone does not update the existing image; rebuild and recreate it. Do not run `docker compose down -v`, volume prune, or delete the `.env` as part of an update.

### Rollback or restore

For code-only rollback, use the retained image tag with a Compose override:

```yaml
# compose.rollback.yaml — replace the timestamp with your saved tag.
services:
  app:
    image: duka-agent-app:rollback-YOUR_TIMESTAMP
```

```bash
sudo docker compose -f compose.yaml -f compose.rollback.yaml up -d --no-build app
```

If the failed release changed the schema incompatibly, restore its matching pre-upgrade data archive and `.env` into a fresh volume using step 10, then start the matching old image. Keep a backup of the failed deployment before replacing it. Do not assume older code can downgrade a newer schema.

## 12. Troubleshooting

| Symptom | Check |
| --- | --- |
| Nginx returns 502 | `sudo docker compose ps`, backend logs and loopback `/api/health`. |
| Sign-in repeats or returns 403 | HTTPS, `SECURE_COOKIES=true`, exact `ALLOWED_ORIGINS` including any nonstandard port. |
| Stream arrives all at once | Nginx/CDN buffering; keep the proxy settings above. |
| Saving database settings fails | `.env` is a regular file, bind is writable, and `bash scripts/allow-env-write.sh` has been run after file replacement. Recreate the container afterward. |
| Database is unreachable | VPN/private DNS, outbound firewall, actual SQL/HANA port, read-only login and TLS trust. Use private DNS in `DOCKER_DNS_*` when needed. |
| Provider is connected but cannot answer | Actual model entitlement, account limits, native login status and account ordering in Modeli. Reconnect through the app when necessary. |
| Excel generation fails on isolation | x86-64 host, Landlock ABI 3+, seccomp and the sandbox check. Do not bypass isolation. |
| Memory/storage exhaustion | Worker concurrency, workbook limits, SQLite growth, uploads, native histories and backup retention. Add capacity before increasing limits. |
| Unexpected empty workspace after moving folders | Wrong Compose project name/volume. Stop and point at the original volume; do not set up replacement users over missing data. |

Diagnostic logs and backups can contain business information. Keep them private. The application already suppresses ordinary HTTP access logs and provider stderr; do not enable raw authentication logging to troubleshoot sign-in.
