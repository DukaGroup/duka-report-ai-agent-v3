#!/usr/bin/env bash
# Native Nginx + systemd; no Docker or Certbot is invoked.
set -euo pipefail
duka_deploy_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
duka_domain=hana.dukagroup.local
duka_certificate= duka_key= duka_chain= duka_ca=
usage() {
    echo 'Usage: sudo bash deploy/setup-provided-https.sh [--domain hana.dukagroup.local] --certificate FILE --key FILE --chain FILE.p7b --ca TRUSTED_ROOT.crt'
}
while (($#)); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --domain|--certificate|--key|--chain|--ca)
            if (($# < 2)); then usage >&2; exit 2; fi
            case "$1" in
                --domain) duka_domain="$2" ;;
                --certificate) duka_certificate="$2" ;;
                --key) duka_key="$2" ;;
                --chain) duka_chain="$2" ;;
                --ca) duka_ca="$2" ;;
            esac
            shift 2 ;;
        *) usage >&2; exit 2 ;;
    esac
done
if [[ $EUID != 0 ]]; then echo 'Run this installer with sudo.' >&2; exit 1; fi
if [[ ! "$duka_domain" =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ || ${#duka_domain} -gt 253 ]]; then
    echo 'Use a lowercase DNS hostname, without a scheme, path or port.' >&2; exit 2
fi
for duka_file in "$duka_certificate" "$duka_key" "$duka_chain" "$duka_ca"; do
    if [[ ! -f "$duka_file" || ! -r "$duka_file" ]]; then usage >&2; exit 2; fi
done
if [[ ! -r /var/www/duka-agent/app/frontend/dist/index.html ]]; then
    echo 'Build the frontend under /var/www/duka-agent/app/frontend before installing HTTPS.' >&2; exit 1
fi
sudo -u duka env ENV_FILE=/var/lib/duka-agent/runtime.env DATA_DIR=/var/lib/duka-agent \
    /var/www/duka-agent/app/.venv/bin/python "$duka_deploy_dir/preflight.py" --domain "$duka_domain"

install -d -m 700 "/etc/nginx/tls/$duka_domain"
duka_bundle="$(mktemp -d "/etc/nginx/tls/$duka_domain/release.XXXXXXXX")"
duka_backup="$(mktemp -d)"
duka_site=/etc/nginx/sites-available/duka-agent
duka_enabled=/etc/nginx/sites-enabled/duka-agent
duka_changed=false
duka_committed=false
cleanup() {
    local duka_status=$?
    if [[ "$duka_committed" != true ]]; then
        if [[ "$duka_changed" == true ]]; then
            rm -f -- "$duka_site" "$duka_enabled"
            if [[ -e "$duka_backup/site" || -L "$duka_backup/site" ]]; then cp -a -- "$duka_backup/site" "$duka_site"; fi
            if [[ -e "$duka_backup/enabled" || -L "$duka_backup/enabled" ]]; then cp -a -- "$duka_backup/enabled" "$duka_enabled"; fi
            if nginx -t; then systemctl reload nginx || true; fi
            echo 'HTTPS activation failed; the previous site configuration was restored.' >&2
        fi
        rm -rf -- "$duka_bundle"
    fi
    rm -rf -- "$duka_backup"
    return "$duka_status"
}
trap cleanup EXIT
/var/www/duka-agent/app/.venv/bin/python "$duka_deploy_dir/provided_tls.py" \
    --domain "$duka_domain" --certificate "$duka_certificate" --key "$duka_key" \
    --chain "$duka_chain" --ca "$duka_ca" --output-dir "$duka_bundle"
install -d -m 755 /etc/nginx/sites-available /etc/nginx/sites-enabled
if [[ -e "$duka_site" || -L "$duka_site" ]]; then cp -a -- "$duka_site" "$duka_backup/site"; fi
if [[ -e "$duka_enabled" || -L "$duka_enabled" ]]; then cp -a -- "$duka_enabled" "$duka_backup/enabled"; fi
duka_changed=true
rm -f -- "$duka_site" "$duka_enabled"
install -m 644 "$duka_bundle/site.conf" "$duka_site"
ln -s "$duka_site" "$duka_enabled"
nginx -t
systemctl enable --now nginx
systemctl reload nginx
# Test locally without depending on internal DNS, while checking the real TLS hostname.
curl --fail --silent --show-error --noproxy '*' --connect-timeout 5 --max-time 30 \
    --cacert "$duka_bundle/trusted-root.crt" --resolve "$duka_domain:443:127.0.0.1" \
    "https://$duka_domain/api/health"
duka_committed=true
echo
echo "HTTPS is ready at https://$duka_domain. Configure internal DNS and client root-CA trust."
echo 'Certificate renewal is manual: rerun this command with the renewed files before expiry.'
