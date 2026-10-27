"""Exercise the installer in an isolated Git checkout, without changing the host."""

import getpass
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def executable(path, content):
    path.write_text(content)
    path.chmod(0o755)


def fixture_installer(tmp_path):
    app, data, binaries = (tmp_path / name for name in ("app", "data", "bin"))
    (app / "deploy").mkdir(parents=True)
    (app / "backend/app").mkdir(parents=True)
    data.mkdir()
    binaries.mkdir()
    (app / "backend/app/main.py").write_text("# fixture backend\n")
    (app / ".gitignore").write_text(".venv/\nfrontend/dist/\n")
    (app / "deploy/hana-native.env.example").write_text("APP_ENV=production\n")
    script = (ROOT / "deploy/install-native.sh").read_text()
    script = script.replace("/var/www/duka-agent/app", str(app))
    script = script.replace("/var/www/duka-agent/codex", str(tmp_path / "codex"))
    script = script.replace("/var/lib/duka-agent", str(data))
    script = script.replace("/run/lock/duka-native-install.lock", str(tmp_path / "install.lock"))
    script = script.replace("source /etc/os-release", 'ID=ubuntu; VERSION_ID="${NATIVE_TEST_OS:-24.04}"')
    script = script.replace(
        'if [[ $EUID != 0 || -z "${SUDO_USER:-}" || "$SUDO_USER" == root ]]; then', "if false; then"
    )
    (app / "deploy/install-native.sh").write_text(script)
    executable(app / "deploy/install-service.sh", '#!/bin/bash\necho service >> "$NATIVE_TEST_LOG"\n')
    executable(app / "deploy/setup-provided-https.sh", '#!/bin/bash\necho "https $*" >> "$NATIVE_TEST_LOG"\n')
    executable(
        binaries / "sudo",
        """#!/bin/bash
while (($#)); do
 case "$1" in
  -u) shift 2 ;;
  -H|--) shift ;;
  *) break ;;
 esac
done
exec "$@"
""",
    )
    executable(
        binaries / "id",
        """#!/bin/bash
if [[ "$1" == duka ]]; then exit 0; fi
exec /usr/bin/id "$@"
""",
    )
    executable(
        binaries / "install",
        """#!/bin/bash
args=()
while (($#)); do
 case "$1" in
  -o|-g) shift 2 ;;
  *) args+=("$1"); shift ;;
 esac
done
exec /usr/bin/install "${args[@]}"
""",
    )
    executable(
        binaries / "systemctl",
        """#!/bin/bash
if [[ "$1" == is-active ]]; then [[ "$NATIVE_TEST_ACTIVE" == true ]]; else exit 0; fi
""",
    )
    executable(binaries / "node", "#!/bin/bash\necho 24\n")
    executable(binaries / "uname", "#!/bin/bash\necho x86_64\n")
    executable(binaries / "apt-get", '#!/bin/bash\necho apt >> "$NATIVE_TEST_LOG"\n')
    executable(binaries / "curl", "#!/bin/bash\nexit 0\n")
    executable(
        binaries / "npm",
        """#!/bin/bash
echo "npm $*" >> "$NATIVE_TEST_LOG"
if [[ "$NATIVE_TEST_BUILD_FAIL" == true ]]; then exit 1; fi
mkdir -p frontend/dist
printf 'fixture frontend' > frontend/dist/index.html
""",
    )
    executable(
        binaries / "python3.12",
        """#!/bin/bash
mkdir -p .venv/bin
printf '#!/bin/bash\nexit 0\n' > .venv/bin/python
cp .venv/bin/python .venv/bin/pip
chmod +x .venv/bin/python .venv/bin/pip
""",
    )
    for args in (
        ["init", "-q"],
        ["config", "user.email", "fixture@example.test"],
        ["config", "user.name", "Fixture"],
        ["add", "."],
        ["commit", "-qm", "Fixture installer"],
        ["remote", "add", "origin", "https://github.com/pellumbmaraj/duka-report-ai-agent-v3.git"],
        ["update-ref", "refs/remotes/origin/main", "HEAD"],
    ):
        subprocess.run(["git", "-C", str(app), *args], check=True, capture_output=True)
    environment = {
        **os.environ,
        "PATH": str(binaries) + ":" + os.environ["PATH"],
        "SUDO_USER": getpass.getuser(),
        "NATIVE_TEST_LOG": str(tmp_path / "calls"),
        "NATIVE_TEST_ACTIVE": "false",
        "NATIVE_TEST_BUILD_FAIL": "false",
    }
    return app, data, environment


@pytest.mark.parametrize("mode", ["fresh", "existing", "prepare"])
def test_native_installer_preserves_settings_and_supports_restore_preparation(tmp_path, mode):
    app, data, env = fixture_installer(tmp_path)
    runtime = data / "runtime.env"
    if mode == "existing":
        runtime.write_text("APP_ENV=production\nDUKA_CONNECTION_FIXTURE_PRESENT=true\n")
        runtime.chmod(0o600)
        original = runtime.read_bytes()
    tls = tmp_path / "private-tls"
    tls.mkdir()
    for name in ("hana.crt", "hana.key", "chain.p7b", "company-root.crt"):
        (tls / name).write_text("fixture material")
    args = ["--prepare-only"] if mode == "prepare" else ["--tls-dir", str(tls)]
    result = subprocess.run(
        ["bash", str(app / "deploy/install-native.sh"), *args], cwd=app, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    calls = Path(env["NATIVE_TEST_LOG"]).read_text()
    assert "npm --prefix frontend run build" in calls
    if mode == "prepare":
        assert not runtime.exists() and "service" not in calls and "https" not in calls
    else:
        assert "service" in calls and "https --domain hana.dukagroup.local" in calls
        assert "Installed GitHub revision:" in result.stdout
        assert runtime.stat().st_mode & 0o777 == 0o600
        if mode == "existing":
            assert runtime.read_bytes() == original


@pytest.mark.parametrize("failure", ["dirty", "unpublished", "active", "platform", "missing_env", "build"])
def test_native_installer_refuses_unsafe_updates_before_service_start(tmp_path, failure):
    app, data, env = fixture_installer(tmp_path)
    if failure == "dirty":
        (app / "backend/app/main.py").write_text("# locally edited source\n")
    elif failure == "unpublished":
        (app / "new.py").write_text("# unpublished\n")
        subprocess.run(["git", "-C", str(app), "add", "."], check=True)
        subprocess.run(["git", "-C", str(app), "commit", "-qm", "Unpublished"], check=True)
    elif failure == "active":
        env["NATIVE_TEST_ACTIVE"] = "true"
    elif failure == "platform":
        env["NATIVE_TEST_OS"] = "22.04"
    elif failure == "missing_env":
        (data / "application.sqlite3").write_bytes(b"existing fixture data")
    else:
        env["NATIVE_TEST_BUILD_FAIL"] = "true"
    result = subprocess.run(
        ["bash", str(app / "deploy/install-native.sh")], cwd=app, env=env, capture_output=True, text=True
    )
    assert result.returncode != 0
    calls = Path(env["NATIVE_TEST_LOG"])
    assert not calls.exists() or "service" not in calls.read_text()
    assert not (data / "runtime.env").exists()
    if failure != "build":
        assert not calls.exists()  # No apt/build before the failed prerequisite.
