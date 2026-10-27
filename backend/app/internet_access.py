"""Additional public-address check before Claude's native WebFetch tool runs.

The native tool owns fetching/redirect handling. This hook grants no generic
socket, shell, filesystem or authenticated-browser capabilities.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit


async def public_web_fetch(data, tool_use_id=None, context=None):
    del tool_use_id, context
    try:
        value = data["tool_input"]["url"]
        url = urlsplit(value)
        host = url.hostname or ""
        if (not isinstance(value, str) or len(value) > 8192 or any(ord(c) <= 32 or ord(c) == 127 for c in value)
                or "\\" in value or url.scheme not in ("http", "https") or not host
                or url.username is not None or url.password is not None or url.port not in (None, 80, 443)
                or host.rstrip(".").lower() == "localhost"
                or host.rstrip(".").lower().endswith((".localhost", ".local", ".internal"))):
            raise ValueError()
        addresses = await asyncio.wait_for(asyncio.to_thread(
            socket.getaddrinfo, host, url.port or (443 if url.scheme == "https" else 80), type=socket.SOCK_STREAM), 5)
        if not addresses:
            raise ValueError()
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0].split("%", 1)[0])
            # Reject mapped IPv6, special-purpose ranges and mixed public/private DNS.
            translated = ip.version == 6 and any(ip in ipaddress.ip_network(prefix) for prefix in (
                "64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32"))
            if (not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip, "is_site_local", False)
                    or getattr(ip, "ipv4_mapped", None) is not None or translated):
                raise ValueError()
    except (KeyError, TypeError, ValueError, OSError, TimeoutError):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                "permissionDecisionReason": "Only public HTTP(S) webpages on standard ports may be read; private, local and unresolved addresses are unavailable."}}
    return {}
