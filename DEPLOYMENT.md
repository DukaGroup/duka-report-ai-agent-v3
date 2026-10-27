# Deploy Hana without Docker

This is the single deployment guide for **https://hana.dukagroup.local**. The short path is: clone GitHub on the server, upload only your certificate files, then run one installer. Follow steps 1–7 in order; the later sections cover database connectivity, updates, renewal, backup/recovery and troubleshooting.

SSH is how you administer the server. Your website certificate, private key and `.p7b` chain secure the browser's HTTPS connection. No Docker is used in this guide: Nginx serves the frontend; systemd runs the Python backend on `127.0.0.1:8080`.

These steps assume the server is still `10.0.200.22`, your SSH user is `hana`, and the server runs **Ubuntu 24.04 x86-64**. First check on the server with `cat /etc/os-release` and `uname -m`. Other operating systems need different dependency installation steps. Report isolation requires Landlock ABI 3+ and seccomp, provided by the standard supported Ubuntu kernel.

**Existing data:** this is a fresh-server installation. Cloning source code does not move the laptop's Docker database, reports, users, grants or model credentials. To retain an existing workspace, obtain a verified encrypted workspace backup and its separate key, then use **Restore an existing workspace before the first start** in step 4 below. Restore the complete data and configuration before starting the service. Never replace an existing `runtime.env` with the example below.

## Deployment layout and requirements

```text
Laptop -- SSH :22 --> Server administration
Browser -- HTTPS :443 --> Nginx
                           |-- frontend/dist/ (website files)
                           `-- /api/ --> systemd: duka-agent --> 127.0.0.1:8080
                                           |-- model subscription processes
                                           |-- SQL Server / SAP HANA
                                           `-- /var/lib/duka-agent/ (persistent data)
```

| Item | Value |
| --- | --- |
| SSH target | `hana@10.0.200.22` |
| Website | `https://hana.dukagroup.local` |
| Application source | `/var/www/duka-agent/app` |
| Python virtual environment | `/var/www/duka-agent/app/.venv` |
| Codex executable | `/var/www/duka-agent/codex/node_modules/.bin/codex` |
| Backend service | `duka-agent.service`, running as `duka` |
| Frontend | `/var/www/duka-agent/app/frontend/dist`, served by Nginx |
| Private data and configuration | `/var/lib/duka-agent`, `runtime.env` inside it |
| Installed Nginx site | `/etc/nginx/sites-available/duka-agent` |
| TLS certificate releases | `/etc/nginx/tls/hana.dukagroup.local/` |

Keep SSH access restricted to your administration network. Allow HTTPS from the intended LAN/VPN clients. The backend listens on loopback only. No separate database server is required for application storage: the backend uses SQLite; SQL Server and HANA are external business-data sources.

Your SSH user needs `sudo`. The server needs free disk space for source, dependencies, model caches, business snapshots, reports and backups, and outbound HTTPS for package downloads and provider sign-in/inference/web search. Its network must also reach your business database endpoints; the laptop's VPN does not automatically give the server the same routes.

**First, on your laptop:**

```bash
ssh hana@10.0.200.22
```

**In that SSH session, on the server:**

```bash
cat /etc/os-release
uname -m
df -h /var
timedatectl status
```

Continue with the dependency commands below only for Ubuntu 24.04 and `x86_64`. Steps 2 and 4 run on the server. Step 3 explicitly switches back to your laptop only to upload certificate files.

## 1. Check DNS and certificates

Ask IT to configure this internal DNS record for LAN and VPN users:

```text
hana.dukagroup.local → 10.0.200.22
```

The website certificate must contain `hana.dukagroup.local` (or a matching `*.dukagroup.local`) in its **Subject Alternative Name**. A certificate for a public `.com` domain will not cover `.local`.

Get these files from the certificate administrator:

| Example filename | Contents |
| --- | --- |
| `hana.cer` | One website certificate, PEM or DER |
| `hana.key` | Matching unencrypted PEM private key, for unattended Nginx startup |
| `chain.p7b` | CA chain, PEM/DER PKCS#7; it may include the root and intermediates |

These are the only three input files. No separate root certificate file is required. The installer uses the server’s existing CA trust store by default. If the root is included in `chain.p7b` but is not already trusted, confirm its SHA256 fingerprint independently with IT and use `--trust-root-sha256` as shown in section 6. Finding a root in the bundle does not automatically make it trusted. No CA private key is needed.

This setup uses your company PKI; **do not run Certbot for `.local`**. Client operating systems/browsers must trust the company root CA. The installer validates against system trust or an explicitly confirmed root fingerprint from the supplied chain; it does not add certificates to global trust stores. Some systems resolve `.local` via multicast DNS; if `getent hosts hana.dukagroup.local` fails or gives a different address, IT must configure the appropriate internal/split-DNS resolution on LAN/VPN clients.

## 2. Get all application code from GitHub — on the server

Inside your SSH session:

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates
sudo install -d -m 755 -o "$(id -un)" -g "$(id -gn)" /var/www/duka-agent
git clone --branch main https://github.com/pellumbmaraj/duka-report-ai-agent-v3.git /var/www/duka-agent/app
cd /var/www/duka-agent/app
```

**The server downloads the frontend, backend, deployment scripts and configuration templates directly from GitHub. Do not copy application source from your laptop.** Private runtime configuration and certificate files stay outside Git.

If `/var/www/duka-agent/app` already contains a Git checkout, do not clone over it. Finish active work, back up the existing workspace, stop the backend and use the update commands in section 9. If that directory contains a previous non-Git installation, keep its private configuration/data and arrange a separate reviewed cutover; do not delete it to make clone succeed.

For a private repository, authenticate Git using your organization's approved credential helper or read-only deploy key. Do not put a GitHub token in the clone URL or in this guide. If Git reports `Could not resolve host`, fix DNS on the server as described in section 12 before retrying.

**These deployment changes must be committed and pushed to GitHub first.** A server clone/pull only receives files that exist in the remote repository. Dependencies are downloaded from their normal package sources by the installer.

## 3. Upload only certificate files — on your laptop

Keep your existing SSH terminal open. In a second terminal on your laptop, change to the directory containing the actual certificate files. Rename them to the filenames below, or use the individual certificate command in step 6 with your filenames.

```bash
ssh hana@10.0.200.22 'mkdir -p -m 700 ~/hana-tls'
chmod 600 hana.key
scp hana.cer hana.key chain.p7b hana@10.0.200.22:~/hana-tls/
```

Only certificate material is transferred from the laptop. No separate company root file or CA private key is required. If the files are already on the server, skip this upload.

`hana.cer` can be PEM or DER; the extension does not determine its encoding. `chain.p7b` is decoded automatically. Keep the private key restricted and do not commit these files to GitHub.

## 4. Install everything with one command — on the server

Return to the server's SSH terminal:

```bash
cd /var/www/duka-agent/app
sudo bash deploy/install-native.sh --tls-dir "$HOME/hana-tls"
```

For a **fresh workspace**, this is the main installation command. It:

1. Checks Ubuntu 24.04/x86-64, a clean GitHub checkout and the three supplied files (`hana.cer`, `hana.key`, `chain.p7b`).
2. Installs the required system packages and Node 24 when needed.
3. Creates the `duka` service account and private data directory.
4. Installs pinned backend dependencies and the Codex CLI, and builds the frontend.
5. Creates the domain's production `runtime.env` only if none exists.
6. Installs/starts the backend systemd service, checks its health, then validates and activates Nginx HTTPS.

Build/package commands run as your normal SSH user; the backend runs separately as `duka`. The installer refuses to update an active backend so it cannot interrupt chats/reports unexpectedly. It does not fetch or merge source code itself: the `git clone`/`git pull --ff-only` commands select the revision first. If a build fails, the backend is not started; correct the named error and rerun. If TLS activation fails after backend startup, use the certificate command in step 6 after correcting the certificate files; you do not need to rebuild the application.

The `duka` account needs read/execute access to the checkout and virtual environment. Nginx reads only the frontend build. The private data directory remains mode `700`.

**Restoring an existing workspace:** instead of the main command above, prepare dependencies without starting services or creating runtime.env:

```bash
sudo bash deploy/install-native.sh --prepare-only
```

Then follow the restore subsection below. Before the first start, set `ALLOWED_ORIGINS=https://hana.dukagroup.local` and `SECURE_COOKIES=true` in the restored private runtime.env, retaining its database profiles. Then run the main `--tls-dir` command to start the existing workspace.

### Restore an existing workspace before the first start

Skip this subsection for a deliberately fresh workspace. To retain existing users, source IDs, grants, chats, uploads, reports, model credentials and keys, obtain a complete `.duka-backup` archive and its matching separate key from the previous installation. A source-code copy or an ordinary SQLite-only copy is insufficient. Stop the source backend for the complete backup; do not let both installations write to the same data directory. The native backup commands are included later in this file.

Upload the archive and key separately over SSH into private server directories. In the commands below, replace `/PRIVATE/PATH/workspace.duka-backup` and `/PRIVATE/PATH/backup.key` with the actual paths. On the destination server, after installing dependencies but **before step 5**:

```bash
cd /var/www/duka-agent/app
sudo .venv/bin/python deploy/backup.py verify \
  --archive /PRIVATE/PATH/workspace.duka-backup \
  --key-file /PRIVATE/PATH/backup.key
sudo .venv/bin/python deploy/backup.py restore \
  --archive /PRIVATE/PATH/workspace.duka-backup \
  --key-file /PRIVATE/PATH/backup.key \
  --target /var/lib/duka-agent-recovery
```

The restore checks authentication, file hashes and SQLite integrity before publishing recovered files. It refuses to overwrite an existing nonempty target. Review the restored data privately. For an **empty destination only**, switch it into place:

```bash
(
set -e
sudo rmdir /var/lib/duka-agent
sudo mv /var/lib/duka-agent-recovery/data /var/lib/duka-agent
sudo install -o duka -g duka -m 600 \
  /var/lib/duka-agent-recovery/config/runtime.env \
  /var/lib/duka-agent/runtime.env
sudo chown -R duka:duka /var/lib/duka-agent
sudo chmod 700 /var/lib/duka-agent
)
```

`rmdir` deliberately fails if the destination is not empty; `set -e` prevents continuing after that failure. Do not replace it with recursive deletion. For an existing destination, retain its own verified backup and arrange a separate recovery/cutover instead. After restore, adjust the HTTPS origin in step 5 while retaining all connection profile prefixes and private keys.

## 5. Check the backend and private configuration

The installer already starts the backend for a normal installation. Check it:

```bash
sudo systemctl status duka-agent --no-pager
curl --fail http://127.0.0.1:8080/api/health
```

Fresh production settings are preconfigured for your domain:

```dotenv
APP_ENV=production
ALLOWED_ORIGINS=https://hana.dukagroup.local
SECURE_COOKIES=true
```

Existing runtime.env settings are preserved. For restored workspaces, ensure the allowed origin matches this domain while retaining source profiles and keys. Only if you need to edit configuration, run:

```bash
sudoedit /var/lib/duka-agent/runtime.env
sudo systemctl restart duka-agent
```

Do not put private values in a tracked file. Configure data sources through Hana after sign-in, or retain the restored runtime.env database profiles. The health endpoint permits a loopback check; sign-in and application traffic require the HTTPS address.

## 6. Certificate setup, repair or renewal

The main installer already calls this setup using exactly `hana.cer`, `hana.key`, and `chain.p7b`. Use this command to repair a failed TLS activation, renew certificates, or supply different filenames:

```bash
cd /var/www/duka-agent/app
sudo bash deploy/setup-provided-https.sh \
  --domain hana.dukagroup.local \
  --certificate "$HOME/hana-tls/hana.cer" \
  --key "$HOME/hana-tls/hana.key" \
  --chain "$HOME/hana-tls/chain.p7b"
```

The `.cer` file accepts PEM or DER. The installer checks the key match, domain/SAN, validity, certificate signatures and server-auth purpose. It orders intermediates, removes duplicates and omits roots from the served full chain. Password-protected private keys are rejected so unattended Nginx startup cannot hang on a password prompt.

### If the company CA is not already trusted by the server

Inspect root fingerprints from the existing `.p7b` using the installed Python environment:

```bash
.venv/bin/python deploy/provided_tls.py --inspect-chain "$HOME/hana-tls/chain.p7b"
```

This prints public certificate identities and SHA256 fingerprints; it does not install or trust them. Confirm the root fingerprint through IT's trusted records, not merely by copying whatever the bundle prints. Then rerun the command above with the extra option:

```text
--trust-root-sha256 CONFIRMED_64_HEX_DIGIT_FINGERPRINT
```

For a first installation, the same option is supported on the main installer:

```bash
sudo bash deploy/install-native.sh --tls-dir "$HOME/hana-tls" \
  --trust-root-sha256 CONFIRMED_64_HEX_DIGIT_FINGERPRINT
```

Replace the placeholder with the independently confirmed fingerprint. A colon-separated SHA256 fingerprint is also accepted when quoted. If the backend is already running after a failed TLS setup, use the certificate-only command instead of rerunning the main installer. An incorrect fingerprint, missing root, untrusted issuer or invalid chain fails closed. If `chain.p7b` contains only intermediates, the server must already trust the remaining root, or IT must provide the complete/correct chain or configure its normal OS trust policy; no certificate is fabricated.

A pinned root is extracted into a generated `verification-ca.pem` inside the private TLS release for the local health check. This is an output derived from your existing chain, not a fourth file to upload. It is used only for that deployment's verification; it does not change global system trust.

After validation the installer stores a private versioned bundle under `/etc/nginx/tls/hana.dukagroup.local/`, renders the native Nginx site, runs `nginx -t`, reloads Nginx and performs a verified HTTPS API health check. Its local `--resolve` check verifies the real hostname without depending on DNS. Failed activation restores the previous site configuration; successful releases are retained for manual rollback. Existing unrelated Nginx sites are retained. Resolve duplicate hostname entries if you previously configured the same domain elsewhere.

## 7. Test from your laptop and open Hana

The network firewall must permit TCP 443 from your intended LAN/VPN users; port 80 is used only to redirect to HTTPS. Keep port 8080 bound to loopback. Keep the SSH rule that allowed you to connect.

On the laptop, after IT's company CA trust policy is applied:

```bash
getent hosts hana.dukagroup.local
curl --fail https://hana.dukagroup.local/api/health
```

If DNS is not ready, this diagnostic preserves hostname and CA verification:

```bash
curl --fail --resolve hana.dukagroup.local:443:10.0.200.22 \
  https://hana.dukagroup.local/api/health
```

The browser and laptop must trust the company issuing CA independently of the server's deployment check. Have IT distribute its verified root from the existing chain through the normal client/browser management policy. No separately named company certificate is assumed by these deployment commands. If the chain lacks the root, IT must already have it in its PKI records. Firefox or other separately managed browser stores may need their own policy. Do not bypass warnings or use `curl -k` as the solution.

Open **https://hana.dukagroup.local**. For a fresh workspace, retrieve the initial setup token on the **server**:

```bash
sudo cat /var/lib/duka-agent/workspace-setup.token
```

Create the first account, then connect ChatGPT/Claude under **Cilësimet → Modeli**. The server needs outbound access to the provider services and any authorized database/VPN endpoints. Model sign-in is separate from your website certificate.

## 8. Configure and verify database connections

Open **Cilësimet → Burimet e të dhënave**, edit or add each source, and run **Test connection**. Test database access independently of the website health endpoint. Existing restored source IDs and grants must be retained.

### SQL Server, including GoTech

Use the SQL Server endpoint, actual SQL port, dedicated reporting username/password and optional default database. Keep `SQLSERVER_ENCRYPTION=require`. The native service loads `deploy/freetds.conf` to require encryption, system CA trust and hostname checks.

The GoTech check on 27 October 2026 reached `192.168.7.10:1433`, but SQL Server presented an untrusted self-signed certificate. Moving the backend does not repair that certificate. Ask the DBA to configure a trusted SQL Server certificate, use the matching DNS hostname, and configure the backend's normal system CA trust when a private CA is involved.

Your three website files are not automatically the SQL Server's CA configuration. The DBA must confirm whether the same issuing CA is used. No extra SQL certificate file is required by the website installer. Installing CA trust does not fix an expired certificate or hostname mismatch.

### The reported GoTech timeout and HANA production-policy error

These errors require different fixes:

- **GoTech timeout:** test connectivity **from the backend server**, not the laptop. The laptop's company VPN does not automatically route the server to `192.168.7.10:1433`. Ask IT to permit the backend server's source IP to the database listener and verify the server's LAN/VPN route. Once TCP works, retest TLS/login; the earlier self-signed SQL certificate may still need correction.
- **`Production HANA connections require encryption and certificate validation.`:** open **Cilësimet → Burimet e të dhënave → SAP HANA → Konfiguro lidhjen → Siguria e lidhjes**. Set **Kriptimi TLS → I aktivizuar** and **Verifikimi i certifikatës → Verifiko certifikatën**, save, then test again. Update this exact saved source; changing generic HANA variables may not override its managed `DUKA_CONNECTION_<ID>_` profile.

The HANA policy error is raised before a connection attempt. A development installation can allow disabled TLS options; production explicitly rejects them. A missing local certificate file is not what triggers that particular error. The database server sends its own TLS certificate. If its issuer is private, configure the database's trusted **public** CA chain in **Certifikata CA e besuar (PEM)** and the correct DNS identity if required. The website's `hana.cer`/`hana.key`/`chain.p7b` secure browser traffic and are separate from database TLS. Do not give the database your website private key or disable validation to bypass the check.

Run the new source-scoped diagnostic on the server:

```bash
cd /var/www/duka-agent/app
sudo -u duka env ENV_FILE=/var/lib/duka-agent/runtime.env DATA_DIR=/var/lib/duka-agent \
  .venv/bin/python deploy/diagnose-connections.py
```

It reads registered source profiles without migrating or changing them, checks required fields and production TLS policy, resolves the database hostname, probes TCP, then tests TLS/login using the configured connector. It prints safe stage/error summaries rather than credentials or raw driver exceptions. It does not query business records or modify grants; normal TLS trust-cache files may be refreshed. Use `--source-id ID` to check one source. No result or a failed stage is not a successful database connection.

### SAP HANA

Choose **SAP HANA**, confirm its actual tenant SQL port with the DBA, and keep encryption and certificate validation enabled. `HANA_DATABASE` is an optional tenant name; a SAP Business One company schema is not a tenant name. For private CA trust, configure that source’s **Certifikata CA e besuar** / `HANA_TLS_CA_CERTIFICATE`. If connecting by IP, configure `HANA_TLS_SERVER_NAME` to the verified DNS identity on the server certificate when necessary. Never disable verification as a connectivity fix.

### Access and read-only privileges

Use reporting accounts with SELECT access only. Devs and President have application access to registered sources; Managers need their exact database/company grants. Check privileges with this read-only inventory after startup:

```bash
cd /var/www/duka-agent/app
sudo -u duka env ENV_FILE=/var/lib/duka-agent/runtime.env DATA_DIR=/var/lib/duka-agent \
  .venv/bin/python deploy/check_database_permissions.py
```

`requires_dba` flags visible write/admin/execute permissions; `unverified` is not a successful result. The command does not grant or revoke access.

## 9. Update directly from GitHub — on the server

Wait for active chats/reports to finish. Then, from your SSH session:

```bash
cd /var/www/duka-agent/app
sudo bash deploy/backup.sh
sudo systemctl stop duka-agent
git pull --ff-only origin main
sudo bash deploy/install-native.sh
```

Run each command only after the previous one succeeds. If the pull fails, stop and resolve it before installing. To bring the previous version back while investigating a failed pull that did not update the checkout, run `sudo systemctl start duka-agent`. If a build fails after the checkout changed, correct the error before starting the updated backend.

This downloads code from GitHub, reinstalls pinned dependencies, builds the frontend and starts the updated backend. The existing Nginx HTTPS site and certificate release remain active; certificate renewal is a separate step in section 6. It preserves runtime.env, database records, uploads, reports and successful TLS releases. Certificates remain in the existing private Nginx release and are not fetched from GitHub. If HTTPS has never been configured, use the `--tls-dir` installation command in section 4 with any independently confirmed root fingerprint required by section 6. Use `git log -1 --oneline` to see the installed revision.

`--ff-only` refuses divergent history instead of making a deployment merge. Review local source changes; do not discard them using `git reset --hard` or `git clean`. The installer also refuses dirty source checkouts or a commit not present on the local `origin/main` history. Certificate/backup/database files belong outside the checkout.

If only frontend files changed and you want to avoid restarting the backend, first verify the incoming commit does not alter backend/service files. Then pull that reviewed frontend-only update and run:

```bash
cd /var/www/duka-agent/app
git pull --ff-only origin main
npm --prefix frontend ci
npm --prefix frontend run build
chmod -R a+rX frontend/dist
```

The frontend build writes to the live static directory; schedule a maintenance window. Reverting code alone is not a schema rollback: retain the pre-update encrypted backup and restore alongside the live workspace if recovery is needed. HTTPS renewal alone uses section 6 and does not require rebuilding the application.

## 10. Renew HTTPS certificates

For certificate renewal, upload the renewed files and rerun step 6 before expiry. The installer never contacts a public CA and does not schedule renewal. Keep your CA's renewal reminders; the served leaf expires on the date shown by `openssl x509 -in ~/hana-tls/hana.cer -noout -enddate`.

## 11. Create and verify encrypted backups

Run from `/var/www/duka-agent/app`. Backups include the complete private data directory, a consistent SQLite copy, environment settings, users, grants, uploads, reports, subscription credentials/history and notification keys. The wrapper briefly stops the service and restarts it even if backup fails. It does not modify grants or business databases.

### Create a backup

```bash
# Create an authenticated encrypted backup and verify recovery.
sudo bash deploy/backup.sh
# List the private archives.
sudo ls -lh /var/backups/duka-agent
```

The encryption key is created once at `/var/lib/duka-agent-backup.key` with mode `600`. **Copy it separately to a secure location.** Move archives to a separate backup location too. The key is never included in an archive; losing it makes recovery impossible. No backup schedule is installed automatically.

### Verify or restore

```bash
# Check authentication, file hashes, SQLite integrity and foreign keys.
sudo .venv/bin/python deploy/backup.py verify --key-file /var/lib/duka-agent-backup.key --archive /path/to/backup.duka-backup
# Recover separately; existing workspace data is never overwritten.
sudo .venv/bin/python deploy/backup.py restore --key-file /var/lib/duka-agent-backup.key --archive /path/to/backup.duka-backup --target /var/lib/duka-agent-recovery
```

For installation into an empty destination, use the complete restore/cutover instructions in step 4 of this file. For an already active server, recover alongside the live workspace and retain its verified backup; do not merge SQLite databases or delete the live directory.

The private data directory, runtime.env and generated files are not application-encrypted at rest. The backup archive is encrypted. Use appropriate disk encryption and filesystem permissions for the live server, and keep the backup key separately from the archives. No automatic backup schedule or certificate-renewal schedule is installed.

## 12. Troubleshoot in this order

### View application logs inside Hana

After deploying this revision and rebuilding the frontend, Devs can open **Cilësimet → Regjistrat e sistemit**. It shows up to 2,000 retained operational events: backend start/stop, saved connection checks, database failures, provider errors and report-tool failures. Filter by level/component, refresh or pause updates, browse older events, or download the displayed page as redacted JSON. Managers and President cannot access the panel or its API.

To capture a database failure, run **Test connection** for that source, then filter the log viewer to **Databazat**. Connection-check entries include the source name, safe error message, category and available driver code. Passwords, tokens, raw driver exceptions and SQL result rows are not copied into these operational logs. This is an application log, not unrestricted access to systemd/Nginx journals. Logging begins after the upgraded backend initializes; earlier startup failures still require the server terminal:

```bash
sudo journalctl -u duka-agent -n 100 --no-pager
sudo journalctl -u duka-agent -f
```

For Nginx failures use `sudo nginx -t` and `sudo tail -n 80 /var/log/nginx/error.log`. Do not add the backend service user to the system journal or administrator groups to expose host logs through the app.


### SSH, GitHub or provider DNS fails

Run diagnostics on the machine where the command failed. A working laptop does not prove DNS works on the server.

```bash
hostname
ip -br address
ip route
getent ahostsv4 github.com
getent ahostsv4 auth.openai.com
getent ahostsv4 chatgpt.com
cat /etc/resolv.conf
```

`Could not resolve host: github.com` means DNS failed before Git contacted the repository. Ask IT to configure company DNS forwarding for public names while retaining internal `.local` and database resolution. Do not hardcode GitHub IP addresses or switch protocols as a DNS fix. Once DNS works, retry Git from the intended checkout; pending local changes should be reviewed before pulling.

For SSH `No route to host`, check the LAN/VPN path and the server's IP/power/network state. A VPN route alone does not prove the destination is reachable. Test the SSH listener with `nc -nvz -w 5 10.0.200.22 22` where available; use the server console if SSH cannot be reached. The application HTTPS certificate is not an SSH login certificate.

For provider sign-in problems, check server DNS, outbound HTTPS, proxy/firewall policy and account/subscription status. Complete sign-in only through the official provider flow. The frontend and backend share one website origin; there is no browser-side database connection or API key to configure.

### Backend health and startup

```bash
cd /var/www/duka-agent/app
# Check startup errors, then test the backend directly.
sudo journalctl -u duka-agent -n 60 --no-pager
curl --fail --max-time 5 http://127.0.0.1:8080/api/health
```

If health returns `"status":"ok"`, the backend is running. This does **not** prove database connectivity. Test each source in **Cilësimet → Burimet e të dhënave**. If only the public website fails, check the website/HTTPS subsection below.

### A Python package will not install or import

```bash
# Confirm x86_64 and Python 3.12.
uname -m
.venv/bin/python --version
# Install native runtime libraries, then retry the pinned dependencies using driver wheels.
sudo apt-get update
sudo apt-get install -y libgomp1 libstdc++6 libssl3t64
.venv/bin/python -m pip install --upgrade pip==26.2
.venv/bin/python -m pip install --only-binary=pymssql,hdbcli -r backend/requirements.txt
# Confirm both drivers load as the service user.
sudo -u duka .venv/bin/python -c "import pymssql; from hdbcli import dbapi; print('Both database drivers loaded')"
```

`No matching distribution` usually means an incompatible Python/CPU/platform, an unavailable pinned release, or a package-index problem. Use the guide's Ubuntu/Python combination and inspect the named package before changing versions. `libgomp.so.1`, `libstdc++.so.6`, or `libssl.so.3` errors point to the runtime libraries above. Do not copy the laptop's virtual environment; install a new one on the VPS.

If reports fail with a **Landlock/seccomp** error, the host kernel or hosting restrictions must be fixed. Use a VM with Ubuntu's standard supported kernel and the required features enabled; do not disable the app's sandbox. An ARM VPS is incompatible with the current sandbox even if a driver installs.

### Database connection times out or hostname is unknown

Replace the host and port below with the exact source endpoint. SQL Server commonly uses `1433`; confirm HANA's actual tenant SQL port with its administrator.

```bash
# Test DNS and TCP access without database credentials.
sudo -u duka .venv/bin/python - <<'PY'
import socket
host = "YOUR_DATABASE_HOST"
port = 1433
with socket.create_connection((host, port), timeout=5):
    print("TCP connection succeeded")
PY
```

- **Unknown hostname:** the VPS needs the company's DNS resolver or a hostname resolvable from its network. The laptop's VPN DNS does not transfer to the VPS. Configure DNS on this server through its network manager or company VPN configuration.
- **Timeout/no route:** ask the network administrator to verify the VPS-to-database route and permitted source IP. Being a VPS does not itself provide company-network access.
- **Connection refused:** confirm the server's SQL listener and port.
- **TCP succeeds:** routing is working; check TLS, login, and database permissions next. TCP alone does not authenticate to the database.

### Database TLS / CA certificate errors

Refresh the VPS's public trust store and verify its clock:

```bash
sudo apt-get install --reinstall -y ca-certificates
sudo update-ca-certificates
timedatectl status
```

For **HANA**, keep `HANA_ENCRYPT=true` and `HANA_VALIDATE_CERTIFICATE=true` in the source's profile:

- **Unknown issuer/private CA:** obtain the root/intermediate CA certificates from the database administrator. Add them in **Konfiguro lidhjen → Certifikata CA e besuar** (`HANA_TLS_CA_CERTIFICATE`). The app builds its private trust bundle under `/var/lib/duka-agent/tls`.
- **Hostname mismatch:** use the database's correct DNS name, or set that source's `HANA_TLS_SERVER_NAME` to the verified name on its certificate.
- **Expired certificate:** renew the server certificate; adding a CA will not fix expiry.

For **SQL Server**, production uses `deploy/freetds.conf` through the unit's `FREETDSCONF` variable. It requires encryption, system CA trust and hostname verification. Keep `SQLSERVER_ENCRYPTION=require`. For a private database CA, ask the DBA to configure the verified issuer in the backend server’s system trust store. This is a database prerequisite, separate from the three website files. Use the database DNS name matching its certificate. HANA certificate settings do not apply to SQL Server. See [FreeTDS configuration](https://www.freetds.org/userguide/freetdsconf.htm).

The native service reads `/var/lib/duka-agent/runtime.env`, not the checkout's `.env`. After changes, restart it with `sudo systemctl restart duka-agent`. If preflight rejects startup, verify exact HTTPS origins, `SECURE_COOKIES=true`, the supplied FreeTDS file, data directory mode `700`, and environment ownership `duka:duka` with mode `600`. A fresh workspace's setup code is available only through `sudo cat /var/lib/duka-agent/workspace-setup.token`; existing workspaces do not need it.

### Connection settings, logins, or member access fail

The native service reads `/var/lib/duka-agent/runtime.env`, not the laptop's environment or the checkout’s `.env`. Retain existing named profiles and `DUKA_CONNECTION_<ID>_` prefixes; edit the matching source in Settings. Restore the complete workspace data when migrating so saved connections and grants still match.

```bash
# Check that the service can read/update its configuration and write its data.
sudo -u duka test -r /var/lib/duka-agent/runtime.env
sudo -u duka test -w /var/lib/duka-agent/runtime.env
sudo -u duka test -w /var/lib/duka-agent
```

These checks return silently on success. If one fails, repeat the relevant ownership/permission commands in the main guide. The service cannot use files kept under your home directory because `ProtectHome=true`.

| Error                                                        | Fix                                                                                                                                            |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| SQL Server `18456` / login failed                          | Check the source login/password and server authentication settings.                                                                            |
| SQL Server `4060` / cannot open database                   | Check the database name and that login's access. For HANA, the tenant database is different from a company schema.                             |
| Permission denied / SQL Server `229`                       | Ask the DBA to grant the reporting login SELECT on the required tables/views.                                                                  |
| Source works for Devs but Manager sees “Qasja nuk lejohet” | Check that member's exact source, database, and company selections. Preserve existing grants; do not grant every database to bypass the error. |

After manual `runtime.env` changes or dependency fixes, restart and retest the affected source:

```bash
sudo systemctl restart duka-agent
sudo systemctl status duka-agent --no-pager
```

### Website shows 502 or HTTPS setup fails

```bash
# Check the proxy configuration and its recent errors.
sudo nginx -t
sudo journalctl -u nginx -n 40 --no-pager
```

For **502**, first make the loopback backend health check succeed. Nginx must forward `/api/` to `127.0.0.1:8080` and serve frontend files from the built `frontend/dist` directory.

For certificate/chain errors, rerun the provided-certificate installer in step 6 after correcting the files. It verifies the real domain and rolls back a failed activation. Do not run a public certificate-issuance tool for this internal domain. Confirm clients trust the verified root and internal DNS resolves correctly. A default Nginx welcome page or the wrong certificate usually means DNS points to another server, the site was not enabled, or another Nginx site has the same hostname.

For file-permission errors, the `duka` account must be able to traverse the code/virtual-environment directories and read the executable, while Nginx must read `frontend/dist`. Keep private business data mode `700` and runtime.env owned by `duka:duka`, mode `600`. Do not expose `/var/lib/duka-agent` through Nginx or move code into an SSH user's home; the service has `ProtectHome=true`.

## 13. Final verification and file responsibilities

Before handing the site to users, confirm:

1. `systemctl is-enabled duka-agent` and `systemctl is-enabled nginx` report enabled.
2. `systemctl status duka-agent --no-pager` is healthy and the loopback health check succeeds.
3. The laptop opens `https://hana.dukagroup.local` without certificate warnings.
4. Sign-in, a new chat with a sourced current-information lookup, and a report download work.
5. Each configured database passes its own connection test; Managers see only assigned databases/companies.
6. You have a verified encrypted backup and its separately protected key.

| Retained deployment file | Responsibility |
| --- | --- |
| `deploy/install-native.sh` | Main native installer: prerequisites, dependencies, build, backend and optional HTTPS |
| `deploy/hana-native.env.example` | Fresh-server production settings for this domain |
| `deploy/duka-agent.service` | Backend process, loopback listener and service restrictions |
| `deploy/install-service.sh` | Validate/install/start the backend systemd service |
| `deploy/prepare-env.sh`, `deploy/prepare_env.py` | Preserve or prepare private configuration |
| `deploy/preflight.py` | Check origins, file permissions and database TLS policy |
| `deploy/setup-provided-https.sh` | Activate your supplied certificates and Nginx site with rollback |
| `deploy/provided_tls.py` | Parse `.p7b`, verify certificate/key/chain/domain and stage the bundle |
| `deploy/nginx-https.conf` | Native frontend and API proxy template; the installer fills its tokens |
| `deploy/freetds.conf` | SQL Server TLS trust and hostname policy |
| `deploy/backup.sh`, `deploy/backup.py` | Encrypted, verified workspace backup and recovery |
| `deploy/diagnose-connections.py` | Check saved configuration, TLS policy, DNS/TCP and database login safely |
| `deploy/check_database_permissions.py` | Read-only reporting-account privilege inventory |
| `deploy/check-tracked-secrets.py` | Prevent private configuration/credentials entering Git |

All listed code and templates come from the GitHub checkout. The main installer calls the smaller helpers; they are not alternate deployment methods. Certificates, runtime.env, business data and backup keys stay outside GitHub. Security reviews in `docs/` are historical audit records; they are not current deployment instructions.

References: [Git clone](https://git-scm.com/docs/git-clone), [Git pull](https://git-scm.com/docs/git-pull), [Nginx HTTPS and chains](https://nginx.org/en/docs/http/configuring_https_servers.html), [OpenSSL PKCS#7](https://docs.openssl.org/3.5/man1/openssl-pkcs7/), [OpenSSL verification](https://docs.openssl.org/3.5/man1/openssl-verify/), [FreeTDS configuration](https://www.freetds.org/userguide/freetdsconf.htm), [.local DNS behavior](https://www.rfc-editor.org/rfc/rfc6762.html).
