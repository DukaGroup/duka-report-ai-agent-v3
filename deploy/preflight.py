"""Read-only checks run as the native service user before starting Uvicorn."""
import os
import stat
import sys
import argparse
from pathlib import Path


def check_environment(path):
    from dotenv import dotenv_values

    descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r+") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o007:
            raise ValueError("The runtime environment must be a private regular file (600 or 660).")
        values = dotenv_values(stream=source, interpolate=False)
    for key, value in values.items():
        if value is not None:
            os.environ.setdefault(key, value)
    # The native service is always production, regardless of file contents.
    os.environ["APP_ENV"] = "production"


def main(domain=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    path = Path(os.getenv("ENV_FILE", "/var/lib/duka-agent/runtime.env"))
    try:
        check_environment(path)
        from app.config import Settings
        from app.deployment_security import validate_freetds, validate_web_settings
        settings = Settings(env_file=path)
        validate_web_settings(settings)
        if domain and 'https://' + domain not in settings.allowed_origins:
            raise ValueError('Nginx domain must match an allowed HTTPS origin.')
        validate_freetds(os.getenv('FREETDSCONF', str(Path(__file__).with_name('freetds.conf'))))
        if not settings.data_dir.is_dir() or not os.access(settings.data_dir, os.W_OK):
            raise ValueError("DATA_DIR must exist and be writable by the service user.")
        if stat.S_IMODE(settings.data_dir.stat().st_mode) != 0o700:
            raise ValueError("DATA_DIR must have permissions 700.")
    except (OSError, ValueError):
        print("Deployment checks failed: use a private, writable runtime.env, DATA_DIR mode 700, HTTPS ALLOWED_ORIGINS and SECURE_COOKIES=true.", file=sys.stderr)
        return 1
    print("Production environment checks passed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain')
    raise SystemExit(main(parser.parse_args().domain))
