#!/usr/bin/env bash
set -euo pipefail

duka_deploy_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

install -m 644 "$duka_deploy_dir/duka-agent.service" /etc/systemd/system/duka-agent.service
systemd-analyze verify /etc/systemd/system/duka-agent.service
systemctl daemon-reload
systemctl enable duka-agent
systemctl restart duka-agent
systemctl status duka-agent --no-pager
