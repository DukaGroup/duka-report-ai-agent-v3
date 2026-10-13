import os
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass
class Settings:
    data_dir: Path = Path(os.getenv("DATA_DIR", "data")).resolve()
    frontend_dir: Path = Path(os.getenv("FRONTEND_DIR", "frontend/dist")).resolve()
    codex_binary: str = os.getenv("CODEX_BINARY", "codex")
    session_hours: int = int(os.getenv("SESSION_HOURS", "24"))
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "false").lower() == "true"
    allowed_origins: tuple[str, ...] = tuple(
        x.strip() for x in os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",")
    )
    whisper_model: str = os.getenv("WHISPER_MODEL", "base")
    whisper_language: str | None = os.getenv("WHISPER_LANGUAGE") or None
    voice_enabled: bool = os.getenv("VOICE_ENABLED", "true").lower() == "true"
    max_runtimes: int = int(os.getenv("MAX_CODEX_RUNTIMES", "8"))
    turn_timeout: int = int(os.getenv("TURN_TIMEOUT_SECONDS", "300"))
    sqlserver_host: str = field(default_factory=lambda: os.getenv("SQLSERVER_HOST", ""), repr=False)
    sqlserver_port: str = field(default_factory=lambda: os.getenv("SQLSERVER_PORT", "1433"), repr=False)
    sqlserver_user: str = field(default_factory=lambda: os.getenv("SQLSERVER_USER", ""), repr=False)
    sqlserver_password: str = field(default_factory=lambda: os.getenv("SQLSERVER_PASSWORD", ""), repr=False)
    sqlserver_database: str = field(default_factory=lambda: os.getenv("SQLSERVER_DATABASE", ""), repr=False)
    sqlserver_encryption: str = os.getenv("SQLSERVER_ENCRYPTION", "require")
    sqlserver_timeout: int = int(os.getenv("SQLSERVER_TIMEOUT_SECONDS", "15"))
    env_file: Path | None = field(
        default_factory=lambda: Path(os.getenv("ENV_FILE", str(Path(__file__).resolve().parents[2] / ".env"))),
        repr=False,
    )
    query_dir: Path = field(default_factory=lambda: Path(os.getenv("REPORT_QUERY_DIR", "backend/queries")).resolve())

    def database_environment(self):
        """Read SQL settings privately, preserving literal password characters.

        The mounted .env file takes precedence over stale container variables.
        Reads happen when resolving a connection, not in the Codex process.
        """
        from dotenv import dotenv_values

        if self.env_file is None or not self.env_file.exists():
            return self
        values = dotenv_values(self.env_file, interpolate=False)
        updates = {}
        for name in ("HOST", "PORT", "USER", "PASSWORD", "DATABASE"):
            key = f"SQLSERVER_{name}"
            if key in values:
                value = values[key] or ""
                updates[key.lower()] = value if name == "PASSWORD" else value.strip()
        if "sqlserver_port" in updates and not updates["sqlserver_port"]:
            updates["sqlserver_port"] = "1433"
        return replace(self, **updates, env_file=None)

    def prepare(self):
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ("codex", "workspaces", "speech-cache", "cache"):
            (self.data_dir / name).mkdir(exist_ok=True, mode=0o700)
