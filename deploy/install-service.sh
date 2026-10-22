#!/usr/bin/env bash
set -euo pipefail

duka_deploy_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$duka_deploy_dir/prepare-env.sh"
sudo -u duka env ENV_FILE=/var/lib/duka-agent/runtime.env DATA_DIR=/var/lib/duka-agent \
    /var/www/duka-agent/app/.venv/bin/python "$duka_deploy_dir/preflight.py"

install -m 644 "$duka_deploy_dir/duka-agent.service" /etc/systemd/system/duka-agent.service
systemd-analyze verify /etc/systemd/system/duka-agent.service
systemctl daemon-reload
systemctl enable duka-agent
systemctl restart duka-agent
systemctl status duka-agent --no-pager
