# Deployment layout

The browser uses one address. The frontend serves the website and proxies `/api/` to the backend. Only the backend has access to persistent business data and credentials.

| Responsibility | Configuration |
| --- | --- |
| Frontend build and web server | `frontend/Dockerfile`, `frontend/deploy/` |
| Backend API, model runtimes and dependencies | `backend/Dockerfile`, `backend/requirements*.txt` |
| Docker service wiring, private network and persistent volume | `compose.yaml` |
| Docker deployment/migration and host HTTPS proxy | `deploy/docker/` |
| Optional backend database/VPN DNS | `deploy/compose-dns.yaml` |
| Native backend service | `deploy/duka-agent.service`, `deploy/install-service.sh` |
| Native frontend and HTTPS | `deploy/nginx*.conf`, `deploy/setup-nginx.sh` |
| Company certificates / Hana internal domain | `deploy/setup-provided-https.sh`, `deploy/provided_tls.py`, `deploy/hana-native.env.example` |
| Shared backup, secret checks and database privilege checks | Other scripts in `deploy/` |

Choose [Docker deployment](../docs/deploy-with-docker.md) or [native VPS deployment](../docs/deploy-without-docker.md). Both use the same frontend/backend boundary and retain one workspace database; no new database server or data migration is needed.

For the requested domain **hana.dukagroup.local**, follow [the internal native guide](../docs/deploy-hana-internal.md). It distinguishes laptop and server commands and accepts an existing `.p7b` chain without Certbot. Moving to another server still requires explicitly restoring the existing workspace if its records are to be retained.
