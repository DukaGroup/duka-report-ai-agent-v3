# Hana at https://hana.dukagroup.local — native deployment

SSH is how you administer the server. Your website certificate, private key and `.p7b` chain secure the browser's HTTPS connection. No Docker is used in this guide: Nginx serves the frontend; systemd runs the Python backend on `127.0.0.1:8080`.

These steps assume the server is still `10.0.200.22`, your SSH user is `hana`, and the server runs **Ubuntu 24.04 x86-64**. First check on the server with `cat /etc/os-release` and `uname -m`. Other operating systems need different dependency installation steps. Report isolation requires Landlock ABI 3+ and seccomp, provided by the standard supported Ubuntu kernel.

**Existing data:** this is a fresh-server installation. Uploading source code does not move the laptop's Docker database, reports, users, grants or model credentials. To retain an existing workspace, follow [backup and restore](backup-and-restore.md) and restore its data and private configuration **before the first service start**. Never replace an existing `runtime.env` with the example below.

## 1. Check DNS and certificates

Ask IT to configure this internal DNS record for LAN and VPN users:

```text
hana.dukagroup.local → 10.0.200.22
```

The website certificate must contain `hana.dukagroup.local` (or a matching `*.dukagroup.local`) in its **Subject Alternative Name**. A certificate for a public `.com` domain will not cover `.local`.

Get these files from the certificate administrator:

| Example filename | Contents |
| --- | --- |
| `hana.crt` | One website certificate, PEM or DER |
| `hana.key` | Matching unencrypted PEM private key, for unattended Nginx startup |
| `chain.p7b` | Intermediate CA certificates; PEM/DER PKCS#7 or PEM certificates are accepted |
| `company-root.crt` | One root CA certificate, confirmed independently with IT |

The root's fingerprint must be confirmed through a trusted channel. Finding a root certificate in the `.p7b` is not sufficient reason to trust it. No CA private key is needed.

This setup uses your company PKI; **do not run Certbot for `.local`**. Client operating systems/browsers must trust the company root CA. The installer validates against the explicit root you supply but does not add it to any trust store. Some systems resolve `.local` via multicast DNS; if `getent hosts hana.dukagroup.local` fails or gives a different address, IT must configure the appropriate internal/split-DNS resolution on LAN/VPN clients.

## 2. Upload code and certificate files — on your laptop

Open a laptop terminal (outside the SSH session):

```bash
ssh hana@10.0.200.22 'mkdir -p ~/hana-source; mkdir -p -m 700 ~/hana-tls'

cd /home/pume-laptop/Documents/duka-group/duka-report-ai-agent-v3
rsync -av \
  --exclude='.git/' --exclude='.env' --exclude='.env.*' \
  --exclude='work/' --exclude='data/' --exclude='outputs/' \
  --exclude='*.sqlite*' --exclude='*.duka-backup' --exclude='*.backup-key' \
  --exclude='*.key' --exclude='*.pem' --exclude='*.p7b' --exclude='*.pfx' --exclude='*.p12' \
  --exclude='node_modules/' --exclude='.venv/' --exclude='__pycache__/' \
  --exclude='.pytest_cache/' --exclude='frontend/dist/' \
  ./ hana@10.0.200.22:~/hana-source/
```

The domain-specific environment example is `deploy/hana-native.env.example`, so it is included even though project `.env` files are excluded. No `--delete` is used.

In the directory containing your actual certificate files, upload them separately (replace these filenames with yours):

```bash
chmod 600 hana.key
scp hana.crt hana.key chain.p7b company-root.crt hana@10.0.200.22:~/hana-tls/
ssh hana@10.0.200.22
```

The remaining installation commands run **inside SSH, on the server**.

## 3. Install runtime dependencies — on the server

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl openssl rsync libgomp1 libstdc++6 \
  python3.12 python3.12-venv nginx
curl -fsSL https://deb.nodesource.com/setup_24.x -o ~/node24-setup.sh
sudo bash ~/node24-setup.sh
sudo apt-get install -y nodejs
node --version
```

Node should report version 24. The backend uses it for the Codex CLI; frontend files are compiled with it and then served as static assets.

## 4. Put the application in its native directory

Create the service account only if it does not already exist:

```bash
if ! id duka >/dev/null 2>&1; then
  sudo useradd --system --user-group --home-dir /var/lib/duka-agent --shell /usr/sbin/nologin duka
fi
sudo install -d -o "$(id -un)" -g "$(id -gn)" /var/www/duka-agent
sudo install -d -o duka -g duka -m 700 /var/lib/duka-agent
rsync -av ~/hana-source/ /var/www/duka-agent/app/
cd /var/www/duka-agent/app

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip==26.2
.venv/bin/pip install -r backend/requirements.txt
npm install --prefix /var/www/duka-agent/codex --save-exact @openai/codex@0.162.1
npm --prefix frontend ci
npm --prefix frontend run build
chmod -R a+rX frontend/dist
```

The `duka` service account needs read/execute access to `/var/www/duka-agent` and its application files. Private business data remains under `/var/lib/duka-agent`, mode `700`; never make that directory readable to Nginx.

## 5. Configure and start the backend

On a fresh installation with no runtime environment, install the provided production example:

```bash
if ! sudo test -e /var/lib/duka-agent/runtime.env; then
  sudo install -o duka -g duka -m 600 deploy/hana-native.env.example /var/lib/duka-agent/runtime.env
fi
sudoedit /var/lib/duka-agent/runtime.env
```

Make sure these settings match, retaining any existing database profiles:

```dotenv
APP_ENV=production
ALLOWED_ORIGINS=https://hana.dukagroup.local
SECURE_COOKIES=true
```

Start the backend:

```bash
sudo bash deploy/install-service.sh
sudo systemctl status duka-agent --no-pager
curl --fail http://127.0.0.1:8080/api/health
```

The health endpoint permits this loopback check. Sign-in and application traffic require the configured HTTPS address. The backend is not exposed directly to LAN/VPN clients.

## 6. Validate and activate your certificates

Verify the root fingerprint with IT before proceeding:

```bash
openssl x509 -in ~/hana-tls/company-root.crt -noout -subject -fingerprint -sha256
```

If the root file is DER, add `-inform DER` to that inspection command. The installer accepts either encoding.

Run the certificate installer from the application directory:

```bash
sudo bash deploy/setup-provided-https.sh \
  --domain hana.dukagroup.local \
  --certificate "$HOME/hana-tls/hana.crt" \
  --key "$HOME/hana-tls/hana.key" \
  --chain "$HOME/hana-tls/chain.p7b" \
  --ca "$HOME/hana-tls/company-root.crt"
```

It checks the website hostname, key match, signatures, validity dates and server-auth purpose against the explicit trusted root. It orders the intermediates, removes duplicates and omits the root from the served full chain. Ambiguous or incomplete chains are rejected for correction by IT. The key must be unencrypted; password-protected private keys are rejected rather than prompting during unattended startup.

After validation it stores a private versioned bundle under `/etc/nginx/tls/hana.dukagroup.local/`, renders the native Nginx site, runs `nginx -t`, reloads Nginx and performs a real HTTPS API health check using the supplied root. The local check uses `--resolve` so it does not depend on server DNS; it still verifies the real hostname. If activation or health fails, the previous site configuration is restored and the failed bundle is removed. Existing successful bundles are retained for manual rollback.

No Docker, Certbot, new self-signed website certificate, database reset, or global root-trust change is involved. Existing unrelated Nginx sites are retained. Resolve duplicate `server_name` entries if you previously configured the same domain elsewhere.

## 7. Test from your laptop and open Hana

The network firewall must permit TCP 443 from your intended LAN/VPN users; port 80 is used only to redirect to HTTPS. Keep port 8080 bound to loopback. Keep the SSH rule that allowed you to connect.

On the laptop:

```bash
getent hosts hana.dukagroup.local
curl --fail --cacert company-root.crt https://hana.dukagroup.local/api/health
```

Use a PEM root for `curl`; if necessary convert a DER root with `openssl x509 -inform DER -in company-root.crt -out company-root.pem` and pass that file. If DNS is not ready, this diagnostic preserves hostname verification:

```bash
curl --fail --cacert company-root.crt \
  --resolve hana.dukagroup.local:443:10.0.200.22 \
  https://hana.dukagroup.local/api/health
```

Have IT distribute the verified company root to managed client/browser trust stores. On a Debian/Kali client, after confirming its fingerprint, a PEM root can be installed with:

```bash
sudo install -m 644 company-root.crt /usr/local/share/ca-certificates/duka-company-root.crt
sudo update-ca-certificates
```

Firefox or other separately managed browser stores may require their own company policy/import. Never bypass certificate warnings or use `curl -k` as the solution.

Open **https://hana.dukagroup.local**. For a fresh workspace, retrieve the initial setup token on the **server**:

```bash
sudo cat /var/lib/duka-agent/workspace-setup.token
```

Create the first account, then connect ChatGPT/Claude under **Cilësimet → Modeli**. The server needs outbound access to the provider services and any authorized database/VPN endpoints. Model sign-in is separate from your website certificate.

## Updates, renewal and troubleshooting

Upload changed source with the same laptop `rsync` command, then on the server copy `~/hana-source/` into `/var/www/duka-agent/app/` again.

For frontend updates:

```bash
cd /var/www/duka-agent/app
npm --prefix frontend ci
npm --prefix frontend run build
chmod -R a+rX frontend/dist
```

For backend updates, finish active chats/reports first:

```bash
cd /var/www/duka-agent/app
.venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart duka-agent
```

For certificate renewal, upload the renewed files and rerun step 6 before expiry. The installer never contacts a public CA and does not schedule renewal. Keep your CA's renewal reminders; the served leaf expires on the date shown by `openssl x509 -in ~/hana-tls/hana.crt -noout -enddate`.

Inspect failures with:

```bash
sudo journalctl -u duka-agent -n 80 --no-pager
sudo nginx -t
sudo tail -n 80 /var/log/nginx/error.log
```

An unavailable report sandbox is an OS/kernel prerequisite issue; do not disable isolation to work around it. Use [native troubleshooting](deploy-troubleshooting.md) for database TLS and provider connectivity. Successful source updates keep the same data directory and environment. Use encrypted [backups](backup-and-restore.md) and copy them off the server.

References: [Nginx certificate chains](https://nginx.org/en/docs/http/configuring_https_servers.html#ssl_chains), [OpenSSL PKCS#7](https://docs.openssl.org/3.5/man1/openssl-pkcs7/), [OpenSSL verification](https://docs.openssl.org/3.5/man1/openssl-verify/), [.local resolution](https://www.rfc-editor.org/rfc/rfc6762.html).
