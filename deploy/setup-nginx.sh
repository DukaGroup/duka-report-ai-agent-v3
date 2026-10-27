#!/usr/bin/env bash
set -euo pipefail

duka_deploy_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
duka_domain="$(awk '$1 == "server_name" { gsub(";", "", $2); print $2; exit }' "$duka_deploy_dir/nginx.conf")"
if [[ -z "$duka_domain" || "$duka_domain" == "reports.example.com" ]]; then
    echo "Set your domain in deploy/nginx.conf and .env before running this script." >&2
    exit 1
fi
if [[ ! "$duka_domain" =~ ^([a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$ ]]; then
    echo "Use a valid DNS domain in deploy/nginx.conf." >&2
    exit 1
fi
case "${duka_domain,,}" in
    *.local|*.localhost|*.internal|*.test)
        echo 'For internal domains use deploy/setup-provided-https.sh with your company certificate, key, chain and trusted root. See docs/deploy-hana-internal.md.' >&2
        exit 1 ;;
esac
sudo -u duka env ENV_FILE=/var/lib/duka-agent/runtime.env DATA_DIR=/var/lib/duka-agent \
    /var/www/duka-agent/app/.venv/bin/python "$duka_deploy_dir/preflight.py" --domain "$duka_domain"
install -d -m 755 /var/lib/letsencrypt
duka_generated="$(mktemp)"
trap 'rm -f "$duka_generated"' EXIT

if [[ ! -s "/etc/letsencrypt/live/$duka_domain/fullchain.pem" ]]; then
    sed "s/reports\.example\.com/$duka_domain/g" "$duka_deploy_dir/nginx.conf" > "$duka_generated"
    install -m 644 "$duka_generated" /etc/nginx/sites-available/duka-agent
    ln -sfn /etc/nginx/sites-available/duka-agent /etc/nginx/sites-enabled/duka-agent
    nginx -t
    systemctl enable --now nginx
    systemctl reload nginx
fi
certbot certonly --webroot -w /var/lib/letsencrypt -d "$duka_domain" --keep-until-expiring
sed "s/reports\.example\.com/$duka_domain/g" "$duka_deploy_dir/nginx-https.conf" > "$duka_generated"
install -m 644 "$duka_generated" /etc/nginx/sites-available/duka-agent
ln -sfn /etc/nginx/sites-available/duka-agent /etc/nginx/sites-enabled/duka-agent
nginx -t
systemctl enable --now nginx
systemctl reload nginx
install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
install -m 755 "$duka_deploy_dir/reload-nginx.sh" /etc/letsencrypt/renewal-hooks/deploy/duka-agent
curl --fail "https://$duka_domain/api/health"
