#!/bin/sh
set -eu

# A host TLS proxy reaches a published Docker port through its bridge gateway.
# Trust that address only, rather than arbitrary X-Forwarded-* from other peers.
HOST_PROXY_IP="${HOST_PROXY_IP:-$(ip -4 route show default | awk 'NR == 1 {print $3}')}"
if [ -z "$HOST_PROXY_IP" ]; then
    echo 'Cannot identify the host proxy address; set HOST_PROXY_IP explicitly.' >&2
    exit 1
fi
export HOST_PROXY_IP
envsubst '${HOST_PROXY_IP}' < /etc/nginx/duka.conf.template > /tmp/nginx.conf
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
