# Encrypted backup and restore — native deployment

Run from `/var/www/duka-agent/app`. Backups include the complete private data directory, a consistent SQLite copy, environment settings, users, grants, uploads, reports, subscription credentials/history and notification keys. The wrapper briefly stops the service and restarts it even if backup fails. It does not modify grants or business databases.

## Create a backup

```bash
# Create an authenticated encrypted backup and verify recovery.
sudo bash deploy/backup.sh
# List the private archives.
sudo ls -lh /var/backups/duka-agent
```

The encryption key is created once at `/var/lib/duka-agent-backup.key` with mode `600`. **Copy it separately to a secure location.** Move archives to a separate backup location too. The key is never included in an archive; losing it makes recovery impossible. No backup schedule is installed automatically.

## Verify or restore

```bash
# Check authentication, file hashes, SQLite integrity and foreign keys.
sudo .venv/bin/python deploy/backup.py verify --key-file /var/lib/duka-agent-backup.key --archive /path/to/backup.duka-backup
# Recover separately; existing workspace data is never overwritten.
sudo .venv/bin/python deploy/backup.py restore --key-file /var/lib/duka-agent-backup.key --archive /path/to/backup.duka-backup --target /var/lib/duka-agent-recovery
```

Recovered files are under `data/`; a separate environment copy is under `config/runtime.env`. Review recovery before switching the service. For a **fresh destination only**, before first service startup:

```bash
# This deliberately fails if the destination contains any data.
(
set -e
sudo rmdir /var/lib/duka-agent
sudo mv /var/lib/duka-agent-recovery/data /var/lib/duka-agent
sudo install -o duka -g duka -m 600 /var/lib/duka-agent-recovery/config/runtime.env /var/lib/duka-agent/runtime.env
sudo chown -R duka:duka /var/lib/duka-agent
sudo chmod 700 /var/lib/duka-agent
)
```

Retain the restored connection profiles and original encryption/notification keys. Adjust only the public domain and deployment paths for the new host, then run the service and HTTPS installers. To replace an existing workspace, keep its verified backup and restore alongside it first; do not delete it or merge SQLite databases.
