import os
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = Path(os.getenv("DATA_DIR", "data")).resolve()
    frontend_dir: Path = Path(os.getenv("FRONTEND_DIR", "frontend/dist")).resolve()
    codex_binary: str = os.getenv("CODEX_BINARY", "codex")
    claude_binary: str | None = os.getenv("CLAUDE_BINARY") or None
    session_hours: int = int(os.getenv("SESSION_HOURS", "24"))
    production: bool = os.getenv("APP_ENV", "development").lower() == "production"
    require_setup_token: bool = os.getenv("REQUIRE_SETUP_TOKEN", "false").lower() == "true"
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    allowed_origins: tuple[str, ...] = tuple(
        x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",")
    )
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    whisper_language: str | None = os.getenv("WHISPER_LANGUAGE") or None
    voice_enabled: bool = os.getenv("VOICE_ENABLED", "true").lower() == "true"
    max_runtimes: int = int(os.getenv("MAX_CODEX_RUNTIMES", "8"))
    max_workers: int = int(os.getenv("MAX_CODEX_WORKERS", "16"))
    report_max_rows: int = int(os.getenv("REPORT_MAX_ROWS", "1000000"))
    report_max_bytes: int = int(os.getenv("REPORT_MAX_BYTES", "250000000"))
    workbook_timeout: int = int(os.getenv("WORKBOOK_SCRIPT_TIMEOUT_SECONDS", "300"))
    workbook_memory_mb: int = int(os.getenv("WORKBOOK_SCRIPT_MEMORY_MB", "4096"))
    # Zero means no application-imposed wall-clock limit on model investigations.
    turn_timeout: int = int(os.getenv("TURN_TIMEOUT_SECONDS", "0"))
    sqlserver_host: str = field(default_factory=lambda: os.getenv("SQLSERVER_HOST", ""), repr=False)
    sqlserver_port: str = field(default_factory=lambda: os.getenv("SQLSERVER_PORT", "1433"), repr=False)
    sqlserver_user: str = field(default_factory=lambda: os.getenv("SQLSERVER_USER", ""), repr=False)
    sqlserver_password: str = field(default_factory=lambda: os.getenv("SQLSERVER_PASSWORD", ""), repr=False)
    sqlserver_database: str = field(default_factory=lambda: os.getenv("SQLSERVER_DATABASE", ""), repr=False)
    sqlserver_encryption: str = os.getenv("SQLSERVER_ENCRYPTION", "require")
    sqlserver_validate_certificate: bool = False
    sqlserver_tls_ca_certificate: str = field(default="", repr=False)
    sqlserver_tls_server_name: str = field(default="", repr=False)
    sqlserver_timeout: int = int(os.getenv("SQLSERVER_TIMEOUT_SECONDS", "15"))
    hana_host: str = field(default_factory=lambda: os.getenv("HANA_HOST", ""), repr=False)
    hana_port: str = field(default_factory=lambda: os.getenv("HANA_PORT", "30015"), repr=False)
    hana_user: str = field(default_factory=lambda: os.getenv("HANA_USER", ""), repr=False)
    hana_password: str = field(default_factory=lambda: os.getenv("HANA_PASSWORD", ""), repr=False)
    hana_database: str = field(default_factory=lambda: os.getenv("HANA_DATABASE", ""), repr=False)
    hana_encrypt: bool = True
    hana_validate_certificate: bool = False
    hana_tls_ca_certificate: str = field(default="", repr=False)
    hana_tls_server_name: str = field(default="", repr=False)
    env_file: Path | None = field(
        default_factory=lambda: Path(os.getenv("ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env"))),
        repr=False,
    )
    query_dir: Path = field(default_factory=lambda: Path(os.getenv("REPORT_QUERY_DIR", "backend/queries")).resolve())

    def hana_environment(self, prefix="HANA"):
        from .env_store import read_environment
        values = dict(os.environ)
        if self.env_file is not None and self.env_file.exists():
            values.update(read_environment(self.env_file))
        updates = {}
        for name in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE", "TLS_CA_CERTIFICATE", "TLS_SERVER_NAME"):
            value = values.get(prefix + "_" + name)
            if value is not None:
                updates["hana_" + name.lower()] = value if name == "PASSWORD" else value.strip()
        for name in ("ENCRYPT", "VALIDATE_CERTIFICATE"):
            value = values.get(prefix + "_" + name)
            if value is not None:
                if value.lower() not in ("true", "false"):
                    raise ValueError("HANA TLS options must be true or false.")
                updates["hana_" + name.lower()] = value.lower() == "true"
        return replace(self, **updates)

    def database_environment(self, prefix="SQLSERVER"):
        """Read SQL settings privately, preserving literal password characters.

        The mounted .env file takes precedence over stale container variables.
        Reads happen when resolving a connection, not in the Codex process.
        """
        from .env_store import read_environment

        values = dict(os.environ) if prefix != "SQLSERVER" else {
            key: os.environ[key] for key in ("SQLSERVER_VALIDATE_CERTIFICATE", "SQLSERVER_TLS_CA_CERTIFICATE", "SQLSERVER_TLS_SERVER_NAME")
            if key in os.environ
        }
        if self.env_file is not None and self.env_file.exists():
            values.update(read_environment(self.env_file))
        updates = {}
        if prefix != "SQLSERVER":
            if not any(f"{prefix}_{name}" in values for name in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE")):
                return None
            # A partial named profile must not borrow another database's credentials.
            updates = {f"sqlserver_{name.lower()}": "" for name in ("HOST", "USER", "PASSWORD", "DATABASE")}
            updates.update(sqlserver_port="1433", sqlserver_encryption="require", sqlserver_validate_certificate=False,
                           sqlserver_tls_ca_certificate="", sqlserver_tls_server_name="")
        for name in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE", "ENCRYPTION", "TLS_CA_CERTIFICATE", "TLS_SERVER_NAME"):
            key = f"{prefix}_{name}"
            if key in values:
                value = values[key] or ""
                updates[f"sqlserver_{name.lower()}"] = value if name == "PASSWORD" else value.strip()
        value = values.get(prefix + "_VALIDATE_CERTIFICATE")
        if value is not None:
            if value.lower() not in ("true", "false"):
                raise ValueError("Database TLS options must be true or false.")
            updates["sqlserver_validate_certificate"] = value.lower() == "true"
        if "sqlserver_port" in updates and not updates["sqlserver_port"]:
            updates["sqlserver_port"] = "1433"
        return replace(self, **updates, env_file=None)

    def prepare(self):
        from .deployment_security import validate_web_settings
        validate_web_settings(self)
        if not 1 <= self.session_hours <= 168:
            raise ValueError("SESSION_HOURS must be between 1 and 168.")
        if self.turn_timeout < 0:
            raise ValueError("TURN_TIMEOUT_SECONDS must be nonnegative; 0 disables the response time limit.")
        if not 1 <= self.workbook_timeout <= 300 or not 256 <= self.workbook_memory_mb <= 4096:
            raise ValueError("Workbook worker limits must be 1–300 seconds and 256–4096 MB.")
        if not 1 <= self.report_max_rows <= 1000000 or self.report_max_bytes < 1:
            raise ValueError("REPORT_MAX_ROWS must be 1–1000000 and REPORT_MAX_BYTES must be positive.")
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # mkdir(mode=...) does not repair permissions on an existing volume.
        self.data_dir.chmod(0o700)
        for name in ("codex", "workspaces", "speech-cache", "cache"):
            (self.data_dir / name).mkdir(exist_ok=True, mode=0o700)
            (self.data_dir / name).chmod(0o700)
