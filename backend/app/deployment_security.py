"""Web HTTPS/ownership checks; database TLS choices are source-configured."""

import hmac
import configparser
import ipaddress
import os
import secrets
import stat
from urllib.parse import urlsplit


def loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host or "").is_loopback
    except ValueError:
        return False


def origin_url(value):
    try:
        parsed = urlsplit(value)
        if (any(ord(c) <= 32 or ord(c) == 127 for c in value)
                or parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
                or parsed.password or parsed.path or parsed.query or parsed.fragment
                or "*" in value or parsed.port == 0):
            raise ValueError()
        return parsed
    except ValueError:
        raise ValueError("ALLOWED_ORIGINS must contain exact HTTP(S) origins without paths or wildcards.") from None


def production(settings):
    return settings.production or any(not loopback(origin_url(o).hostname) for o in settings.allowed_origins)


def validate_web_settings(settings):
    if not settings.allowed_origins:
        raise ValueError("At least one exact ALLOWED_ORIGINS value is required.")
    urls = [origin_url(o) for o in settings.allowed_origins]
    if production(settings):
        if not settings.secure_cookies or any(o.scheme != "https" for o in urls):
            raise ValueError("Public deployment requires HTTPS ALLOWED_ORIGINS and SECURE_COOKIES=true.")


def validate_freetds(path):
    parser = configparser.ConfigParser(interpolation=None)
    try:
        loaded = parser.read(path) if path else []
    except configparser.Error:
        raise ValueError('Invalid production FreeTDS configuration.') from None
    if not loaded or parser.sections() != ['global']:
        raise ValueError('Production SQL Server needs the supplied FreeTDS trust configuration.')
    values = parser['global']
    if (values.get('encryption') not in ('require', 'request', 'off') or values.get('dump file')
            or os.getenv('TDSDUMP') or os.getenv('TDSDUMPCONFIG')):
        raise ValueError('FreeTDS must use a valid TLS mode with database protocol dumps disabled.')


def bootstrap_path(settings):
    return settings.data_dir / "workspace-setup.token"


def bootstrap_required(settings):
    return production(settings) or settings.require_setup_token


def bootstrap_token(settings):
    descriptor = os.open(bootstrap_path(settings), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "r") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise OSError("Setup token file must be a private regular file.")
        value = source.read(100).strip()
        if len(value) != 43 or not all(c.isalnum() or c in "-_" for c in value):
            raise OSError("Invalid setup token file.")
        return value


def prepare_bootstrap(settings, db):
    if not bootstrap_required(settings) or db.one("SELECT count(*) AS n FROM users")["n"]:
        return
    try:
        descriptor = os.open(bootstrap_path(settings), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        bootstrap_token(settings)  # Refuse unsafe, partial or invalid existing files.
        return
    with os.fdopen(descriptor, "w") as target:
        target.write(secrets.token_urlsafe(32) + "\n")
        target.flush()
        os.fsync(target.fileno())


def verify_bootstrap(settings, supplied):
    return not bootstrap_required(settings) or hmac.compare_digest(
        bootstrap_token(settings).encode(), (supplied or "").encode("utf-8", errors="replace"))
