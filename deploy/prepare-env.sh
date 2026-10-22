#!/usr/bin/env bash
set -euo pipefail
duka_app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
duka_data_dir="/var/lib/duka-agent"
duka_env_file="$duka_data_dir/runtime.env"
install -d -o duka -g duka -m 700 "$duka_data_dir"
"$duka_app_dir/.venv/bin/python" "$duka_app_dir/deploy/prepare_env.py" \
    --app-dir "$duka_app_dir" --data-dir "$duka_data_dir"
chown duka:duka "$duka_env_file"
chmod 600 "$duka_env_file"
echo "Private environment ready at $duka_env_file. Existing contents were preserved."
