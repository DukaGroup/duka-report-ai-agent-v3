#!/usr/bin/env bash
# Run from the GitHub checkout on Ubuntu 24.04 x86-64, using sudo.
set -euo pipefail
umask 022
duka_app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
duka_prepare_only=false
duka_tls_dir=
usage() {
    echo 'Usage: sudo bash deploy/install-native.sh [--tls-dir /PRIVATE/DIRECTORY | --prepare-only]'
    echo 'TLS directory files: hana.crt, hana.key, chain.p7b, company-root.crt'
}
while (($#)); do
    case "$1" in
        --help|-h) usage; exit 0 ;;
        --prepare-only) duka_prepare_only=true; shift ;;
        --tls-dir)
            if (($# < 2)); then usage >&2; exit 2; fi
            duka_tls_dir="$2"; shift 2 ;;
        *) usage >&2; exit 2 ;;
    esac
done
if [[ $EUID != 0 || -z "${SUDO_USER:-}" || "$SUDO_USER" == root ]]; then
    echo 'Run with sudo from your normal SSH account, not from a root login.' >&2; exit 1
fi
if [[ "$duka_app_dir" != /var/www/duka-agent/app ]]; then
    echo 'Clone the GitHub repository into /var/www/duka-agent/app first. See DEPLOYMENT.md.' >&2; exit 1
fi
if [[ "$duka_prepare_only" == true && -n "$duka_tls_dir" ]]; then
    echo 'Use --prepare-only for restore preparation, or --tls-dir for installation.' >&2; exit 2
fi
duka_owner="$SUDO_USER"
as_builder() { sudo -u "$duka_owner" -H -- "$@"; }
duka_git() { as_builder git -C "$duka_app_dir" "$@"; }
# Git operations use the checkout owner, not root or credentials embedded in URLs.
duka_origin="$(duka_git remote get-url origin)"
case "$duka_origin" in
    https://github.com/pellumbmaraj/duka-report-ai-agent-v3.git|git@github.com:pellumbmaraj/duka-report-ai-agent-v3.git) ;;
    *) echo 'The checkout must use the Hana GitHub repository as origin.' >&2; exit 1 ;;
esac
if [[ -n "$(duka_git status --porcelain --untracked-files=normal)" ]]; then
    echo 'The source checkout has local changes. Review them before deploying GitHub code.' >&2; exit 1
fi
if ! duka_git merge-base --is-ancestor HEAD refs/remotes/origin/main; then
    echo 'This commit is not recorded on origin/main. Fetch/pull main from GitHub before installing.' >&2; exit 1
fi
# shellcheck source=/dev/null
source /etc/os-release
if [[ "${ID:-}" != ubuntu || "${VERSION_ID:-}" != 24.04 || "$(uname -m)" != x86_64 ]]; then
    echo 'This installer requires Ubuntu 24.04 x86-64. It has not changed the server.' >&2; exit 1
fi
if [[ -n "$duka_tls_dir" ]]; then
    duka_tls_dir="$(realpath -e -- "$duka_tls_dir")"
    for duka_file in hana.crt hana.key chain.p7b company-root.crt; do
        if [[ ! -r "$duka_tls_dir/$duka_file" ]]; then
            echo "Missing TLS file: $duka_file. See DEPLOYMENT.md for the required files." >&2; exit 1
        fi
    done
fi
exec 9>/run/lock/duka-native-install.lock
flock -n 9 || { echo 'Another native installation is running.' >&2; exit 1; }
if systemctl is-active --quiet duka-agent; then
    echo 'Finish active work, create a backup, then stop duka-agent before installing/updating.' >&2; exit 1
fi
if [[ -L /var/lib/duka-agent/runtime.env ]]; then
    echo 'Refusing a symlinked runtime.env.' >&2; exit 1
fi
if [[ -e /var/lib/duka-agent/application.sqlite3 && ! -f /var/lib/duka-agent/runtime.env ]]; then
    echo 'An existing workspace is missing runtime.env. Restore its private configuration first.' >&2; exit 1
fi

apt-get update
apt-get install -y ca-certificates curl git openssl libgomp1 libstdc++6 python3.12 python3.12-venv nginx
if ! command -v node >/dev/null || [[ "$(node -p 'process.versions.node.split(".")[0]')" != 24 ]]; then
    duka_node_setup="$(mktemp)"
    trap 'rm -f -- "$duka_node_setup"' EXIT
    curl --fail --silent --show-error --location https://deb.nodesource.com/setup_24.x -o "$duka_node_setup"
    bash "$duka_node_setup"
    apt-get install -y nodejs
fi
if [[ "$(node -p 'process.versions.node.split(".")[0]')" != 24 ]]; then
    echo 'Node 24 is required; inspect the NodeSource installation.' >&2; exit 1
fi
if ! id duka >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/duka-agent --shell /usr/sbin/nologin duka
fi
install -d -o duka -g duka -m 700 /var/lib/duka-agent
install -d -o "$duka_owner" -g "$(id -gn "$duka_owner")" /var/www/duka-agent/codex
cd -- "$duka_app_dir"
as_builder python3.12 -m venv .venv
as_builder .venv/bin/python -m pip install --upgrade pip==26.2
as_builder .venv/bin/pip install -r backend/requirements.txt
as_builder npm install --prefix /var/www/duka-agent/codex --save-exact @openai/codex@0.162.1
as_builder npm --prefix frontend ci
as_builder npm --prefix frontend run build
as_builder chmod -R a+rX frontend/dist
if ! sudo -u duka test -r "$duka_app_dir/backend/app/main.py"; then
    echo 'The duka service user cannot read the checkout. Make code directories traversable; keep data private.' >&2; exit 1
fi
if [[ "$duka_prepare_only" == true ]]; then
    echo 'Dependencies and frontend are ready. Restore the workspace before running this installer without --prepare-only.'
    exit 0
fi
if [[ ! -e /var/lib/duka-agent/runtime.env ]]; then
    install -o duka -g duka -m 600 deploy/hana-native.env.example /var/lib/duka-agent/runtime.env
fi
bash deploy/install-service.sh
curl --fail --silent --show-error --retry 10 --retry-connrefused --retry-delay 1 \
    --connect-timeout 3 --max-time 30 http://127.0.0.1:8080/api/health
if [[ -n "$duka_tls_dir" ]]; then
    bash deploy/setup-provided-https.sh --domain hana.dukagroup.local \
        --certificate "$duka_tls_dir/hana.crt" --key "$duka_tls_dir/hana.key" \
        --chain "$duka_tls_dir/chain.p7b" --ca "$duka_tls_dir/company-root.crt"
else
    echo 'Backend ready. Activate supplied HTTPS certificates with deploy/setup-provided-https.sh.'
fi
echo
echo "Installed GitHub revision: $(duka_git rev-parse --short HEAD)"
