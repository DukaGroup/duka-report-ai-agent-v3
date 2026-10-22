# VPS troubleshooting — without Docker

Use this only if a step in [the deployment guide](deploy-without-docker.md) fails. Run the commands on the VPS; use only the section matching the error. Application paths remain under `/var`.

## What changes from the laptop?

| Item | VPS requirement |
|---|---|
| Company VPN | Unnecessary **only if the VPS already has network access to the database servers**. A private address such as `192.168.7.10` is not reachable over the public internet. Otherwise, a company-provided private route or VPN is still needed. |
| Database CA certificates | No custom CA is needed when the database certificate is already trusted by the VPS. A private/company CA still needs configuring, even if the laptop already trusts it. Trusting the business data does not configure certificate trust. Keep the standard `ca-certificates` package installed; the app also needs HTTPS access to the model providers. |
| Native packages | Docker is not required. Use Ubuntu 24.04 **x86-64**, Python 3.12, and the repository's pinned dependencies. The report sandbox also requires Landlock ABI 3+ and seccomp. |

The app uses [`pymssql`](https://pypi.org/project/pymssql/2.4.4/) for SQL Server and [`hdbcli`](https://pypi.org/project/hdbcli/2.30.27/) for HANA. Both publish native Linux packages. The official pymssql wheels bundle FreeTDS and SSL support; Microsoft ODBC drivers are not used by this app.

## 1. Find the failing layer

```bash
cd /var/www/duka-agent/app
# Check startup errors, then test the backend directly.
sudo journalctl -u duka-agent -n 60 --no-pager
curl --fail --max-time 5 http://127.0.0.1:8080/api/health
```

If health returns `"status":"ok"`, the backend is running. This does **not** prove database connectivity. Test each source in **Cilësimet → Burimet e të dhënave**. If only the public website fails, go to section 6.

## 2. A Python package will not install or import

```bash
# Confirm x86_64 and Python 3.12.
uname -m
.venv/bin/python --version
# Install native runtime libraries, then retry the pinned dependencies using driver wheels.
sudo apt-get update
sudo apt-get install -y libgomp1 libstdc++6 libssl3t64
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --only-binary=pymssql,hdbcli -r backend/requirements.txt
# Confirm both drivers load as the service user.
sudo -u duka .venv/bin/python -c "import pymssql; from hdbcli import dbapi; print('Both database drivers loaded')"
```

`No matching distribution` usually means an incompatible Python/CPU/platform, an unavailable pinned release, or a package-index problem. Use the guide's Ubuntu/Python combination and inspect the named package before changing versions. `libgomp.so.1`, `libstdc++.so.6`, or `libssl.so.3` errors point to the runtime libraries above. Do not copy the laptop's virtual environment; install a new one on the VPS.

If reports fail with a **Landlock/seccomp** error, the host kernel or hosting restrictions must be fixed. Use a VM with Ubuntu's standard supported kernel and the required features enabled; do not disable the app's sandbox. An ARM VPS is incompatible with the current sandbox even if a driver installs.

## 3. Database connection times out or hostname is unknown

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

- **Unknown hostname:** the VPS needs the company's DNS resolver or a hostname resolvable from its network. The laptop's VPN DNS does not transfer to the VPS. `DOCKER_DNS_*` settings do not affect a native deployment.
- **Timeout/no route:** ask the network administrator to verify the VPS-to-database route and permitted source IP. Being a VPS does not itself provide company-network access.
- **Connection refused:** confirm the server's SQL listener and port.
- **TCP succeeds:** routing is working; check TLS, login, and database permissions next. TCP alone does not authenticate to the database.

## 4. TLS / CA certificate errors

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

For **SQL Server**, production uses `deploy/freetds.conf` through the unit's `FREETDSCONF` variable. It requires encryption, system CA trust and hostname verification. Keep `SQLSERVER_ENCRYPTION=require`. For a private company CA, obtain the verified CA certificate from the DBA, install it as `/usr/local/share/ca-certificates/duka-company.crt` and run `sudo update-ca-certificates`. Use the database DNS name matching its certificate. HANA certificate settings do not apply to SQL Server. See [FreeTDS configuration](https://www.freetds.org/userguide/freetdsconf.htm).

The native service reads `/var/lib/duka-agent/runtime.env`, not the checkout's `.env`. After changes, restart it with `sudo systemctl restart duka-agent`. If preflight rejects startup, verify exact HTTPS origins, `SECURE_COOKIES=true`, the supplied FreeTDS file, data directory mode `700`, and environment ownership `duka:duka` with mode `600`. A fresh workspace's setup code is available only through `sudo cat /var/lib/duka-agent/workspace-setup.token`; existing workspaces do not need it.

## 5. Connection settings, logins, or member access fail

The service reads `/var/www/duka-agent/app/.env`, not the laptop's environment. Retain existing named profiles and `DUKA_CONNECTION_<ID>_` prefixes; edit the matching source in Settings. Restore the complete workspace data when migrating so saved connections and grants still match.

```bash
# Check that the service can read/update its configuration and write its data.
sudo -u duka test -r /var/www/duka-agent/app/.env
sudo -u duka test -w /var/www/duka-agent/app/.env
sudo -u duka test -w /var/lib/duka-agent
```

These checks return silently on success. If one fails, repeat the relevant ownership/permission commands in the main guide. The service cannot use files kept under your home directory because `ProtectHome=true`.

| Error | Fix |
|---|---|
| SQL Server `18456` / login failed | Check the source login/password and server authentication settings. |
| SQL Server `4060` / cannot open database | Check the database name and that login's access. For HANA, the tenant database is different from a company schema. |
| Permission denied / SQL Server `229` | Ask the DBA to grant the reporting login SELECT on the required tables/views. |
| Source works for Devs but Manager sees “Qasja nuk lejohet” | Check that member's exact source, database, and company selections. Preserve existing grants; do not grant every database to bypass the error. |

After manual `.env` changes or dependency fixes, restart and retest the affected source:

```bash
sudo systemctl restart duka-agent
sudo systemctl status duka-agent --no-pager
```

## 6. Website shows 502 or HTTPS setup fails

```bash
# Check the proxy configuration and its recent errors.
sudo nginx -t
sudo journalctl -u nginx -n 40 --no-pager
```

For **502**, first make the backend health check in section 1 succeed. Nginx must proxy to `127.0.0.1:8080`. For **Certbot/domain errors**, confirm the domain resolves to this VPS, matches `.env` and `deploy/nginx.conf`, and is reachable on ports 80/443. Then retry the supplied script:

```bash
sudo bash deploy/setup-nginx.sh
```

The website's HTTPS certificate and the database's CA certificate are separate; fixing one does not fix the other.
