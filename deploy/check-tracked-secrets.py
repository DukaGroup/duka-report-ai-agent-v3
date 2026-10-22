"""Reject private artifacts and recognizable credentials in the Git index."""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_FILE = re.compile(r"(^|/)(?:\.env(?:\.(?!example$)[^/]+)?|auth\.json|workspace-setup\.token|[^/]+\.(?:backup-key|duka-backup))$|^(?:outputs|data|work)/")
TOKEN = re.compile(rb"(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-(?:proj-|ant-)[A-Za-z0-9_-]{25,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{40,})")
ENV_SECRET = re.compile(rb"(?im)^\s*[A-Z0-9_]*(?:PASSWORD|TOKEN|SECRET|PRIVATE_KEY)\s*=\s*[\"']?([^\s\"'#]+)")


def check():
    failures = []
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    for path in filter(None, paths):
        if PRIVATE_FILE.search(path) and path != '.env.example':
            failures.append((path, 'private runtime data must not be tracked'))
            continue
        content = subprocess.check_output(['git', 'show', ':' + path], cwd=ROOT)
        if TOKEN.search(content):
            failures.append((path, 'credential-like content'))
        if path.endswith(('.env.example', '.env', '.sh', '.md', '.yml', '.yaml')):
            for match in ENV_SECRET.finditer(content):
                value = match.group(1).lower()
                if (value and value not in (b'true', b'false', b'none', b'null')
                        and not value.startswith((b'$', b'<', b'example', b'replace', b'changeme', b'your_', b'test-', b'fixture-'))):
                    failures.append((path, 'non-placeholder secret assignment'))
                    break
    for path, reason in failures:
        print(f'{path}: {reason}', file=sys.stderr)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(check())
