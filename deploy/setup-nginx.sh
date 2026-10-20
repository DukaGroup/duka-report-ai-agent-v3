#!/usr/bin/env bash
set -euo pipefail

duka_deploy_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
duka_domain="$(awk '$1 == "server_name" { gsub(";", "", $2); print $2; exit }' "$duka_deploy_dir/nginx.conf")"
if [[ -z "$duka_domain" || "$duka_domain" == "reports.example.com" ]]; then
    echo "Set your domain in deploy/nginx.conf and .env before running this script." >&2
    exit 1
fi

install -m 644 "$duka_deploy_dir/nginx.conf" /etc/nginx/sites-available/duka-agent
ln -sfn /etc/nginx/sites-available/duka-agent /etc/nginx/sites-enabled/duka-agent
nginx -t
systemctl enable --now nginx
systemctl reload nginx
certbot --nginx -d "$duka_domain" --redirect
curl --fail "https://$duka_domain/api/health"
