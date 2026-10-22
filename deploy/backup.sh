#!/usr/bin/env bash
set -euo pipefail
umask 077
duka_app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
duka_backup_dir="${1:-/var/backups/duka-agent}"
install -d -m 700 "$duka_backup_dir"
duka_resume=0
trap 'if [[ "$duka_resume" == 1 ]]; then systemctl start duka-agent; fi' EXIT
if systemctl is-active --quiet duka-agent; then
    duka_resume=1
    systemctl stop duka-agent
fi
"$duka_app_dir/.venv/bin/python" "$duka_app_dir/deploy/backup.py" backup \
    --key-file /var/lib/duka-agent-backup.key \
    --output "$duka_backup_dir/$(date -u +%Y%m%dT%H%M%S)-$(cat /proc/sys/kernel/random/uuid).duka-backup"
