#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ ! -f .env || -L .env ]]; then
  echo 'Create a regular project-root .env first; existing files are never replaced.' >&2
  exit 1
fi
if ! command -v setfacl >/dev/null; then
  echo 'Install the Linux acl package, then run this script again.' >&2
  exit 1
fi
chmod 600 .env
setfacl -m u:10001:rw .env
echo 'Project .env access configured for the owner and backend container UID 10001.'
