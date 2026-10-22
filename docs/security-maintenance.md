# Security follow-up and deployment checks

## Changes prepared locally

- Real `.env` and all `outputs/` artifacts were removed from the Git index and ignored. Their working files were retained byte-for-byte. `.env.example` remains a credential-free template.
- The local pre-commit hook checks the Git index for private artifacts and recognizable credential patterns. On another developer clone, enable it with `git config core.hooksPath .githooks`; run `python3 deploy/check-tracked-secrets.py` manually too. Pattern matching cannot detect every possible secret.
- Public configurations require HTTPS origins and secure cookies. Public HTTP app requests and unexpected hosts are rejected. Fresh production workspaces use a private, single-use first-account token; existing workspaces retain their accounts.
- Native deployment uses `/var/lib/duka-agent/runtime.env`, verified SQL Server/HANA TLS and an HTTPS-only Nginx proxy. Database-account permissions remain separate from app member grants.
- [Encrypted recovery](backup-and-restore.md) verifies authentication, hashes, SQLite integrity and foreign keys before publishing recovered data. Restore refuses to overwrite a nonempty directory.

## Git history and credential rotation

Untracking files does not erase old commits. A filtered history copy was prepared and checked locally at `work/security-hardening-20261022/sanitized.git`: `.env`, `outputs/` and known historical password values were removed. Internal Codex snapshot/tree refs were dropped from that isolated copy. The original checkout history and remote were left intact. The copy contains the committed history at preparation time; current uncommitted fixes must be committed and included before publishing a replacement.

Publishing rewritten history requires coordinating other clones and remote refs. Cached views/forks may need further cleanup. Do not push the original history back afterward. Follow [GitHub's sensitive-data removal procedure](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository). No force push was made because this work was scoped to local preparation/testing.

Have the DBA replace credentials exposed through repository history. Prefer a dedicated SELECT-only reporting login with approved access, then update the **existing source** in Devs settings and test it before revoking the old login. Do not delete/recreate sources or users: those identifiers carry existing grants. No live database password, login or privilege was changed locally. History cleanup cannot invalidate a copied credential. See [OWASP secrets management](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html).

## Check reporting-account privileges on the VPS

After configuring sources, run this read-only inventory as the service user:

```bash
sudo -u duka env ENV_FILE=/var/lib/duka-agent/runtime.env DATA_DIR=/var/lib/duka-agent .venv/bin/python deploy/check_database_permissions.py
```

`requires_dba` flags admin/write/execute permissions; `unverified` means the boundary could not be established. Errors never count as success. The inventory checks visible databases and effective permissions, including SQL Server object permissions. It cannot decide which business objects should be approved and never grants or revokes anything. Normal app startup must finish legacy credential migration first. References: [SQL Server permissions](https://learn.microsoft.com/en-us/sql/relational-databases/system-functions/sys-fn-my-permissions-transact-sql), [HANA privileges](https://help.sap.com/docs/PRODUCT_ID/4fe29514fd584807ac9f2a04f6754767/20a2f3ea75191014a4c1d9b0859b9917.html).

The native unit uses `deploy/freetds.conf`, requiring SQL Server encryption, system CA trust and hostname checks. HANA requires encryption and certificate validation in production. For private CAs or hostname mismatches, fix trust/DNS/certificates through [troubleshooting](deploy-troubleshooting.md); do not disable verification. See [FreeTDS configuration](https://www.freetds.org/userguide/freetdsconf.htm).

The VPS, actual certificate chains and live database privileges were not accessed during local testing. Keep OS packages patched, restrict administration, store backups separately with a separately protected key, and periodically verify recovery. No firewall rules, subscriptions or automated schedules were changed.
