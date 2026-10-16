#!/usr/bin/env python3
"""Official CLI-shaped auth fixture; never contacts Anthropic."""
import json
import os
import sys
from pathlib import Path

home = Path(os.environ["CLAUDE_CONFIG_DIR"])
account = home / "fixture-account.json"
command = sys.argv[2]
if command == "status":
    print(account.read_text() if account.exists() else json.dumps({"loggedIn": False, "authMethod": "none"}))
elif command == "login":
    assert "--claudeai" in sys.argv and "--console" not in sys.argv
    print("Visit: https://claude.com/cai/oauth/authorize?state=fixture", flush=True)
    if sys.stdin.readline().strip() != "fixture-single-use-code":
        sys.exit(1)
    account.write_text(json.dumps({"loggedIn": True, "authMethod": "claude.ai", "email": "claude@example.com", "subscriptionType": "max"}))
    account.chmod(0o600)
    print("Login successful", flush=True)
elif command == "logout":
    account.unlink(missing_ok=True)
    print("Logged out")
else:
    sys.exit(1)
