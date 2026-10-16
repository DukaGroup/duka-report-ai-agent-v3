"""Private project .env profiles, with migration from legacy encrypted rows.

The legacy key remains in the private volume for recovery. Neither credential
store is exposed to the Codex workspace or public source metadata.
"""

import json
import os

from cryptography.fernet import Fernet, InvalidToken
from .env_store import EnvStore, prefix_for


class SecretsUnavailable(Exception):
    pass


class SourceSecrets:
    def __init__(self, settings, db):
        self.path = settings.data_dir / "source-credentials.key"
        self.db = db
        self.environment = EnvStore(settings)
        if self.environment.journal.exists():
            try:
                with self.environment.locked():
                    pass
            except (OSError, ValueError):
                raise SecretsUnavailable("The project .env recovery could not complete. Check backend file permissions and storage.") from None

    def _cipher(self):
        try:
            if not self.path.exists():
                if self.db.one("SELECT source_id FROM source_credentials LIMIT 1"):
                    raise SecretsUnavailable(
                        "The database credential key is missing. Restore it from the server backup."
                    )
                try:
                    with self.path.open("xb") as key_file:
                        os.chmod(self.path, 0o600)
                        key_file.write(Fernet.generate_key())
                except FileExistsError:
                    pass
            os.chmod(self.path, 0o600)
            return Fernet(self.path.read_bytes())
        except (OSError, ValueError) as exc:
            raise SecretsUnavailable(
                "The database credential key cannot be read. Check the private data volume."
            ) from exc

    def encrypt(self, source_id, values):
        # Kept as the existing caller's save operation. New credentials live only
        # in the project .env; the SQLite row records storage mode, never secrets.
        try:
            self.environment.put(source_id, values)
        except (OSError, ValueError):
            raise SecretsUnavailable("The project .env could not be updated. Check its writable mount and backend file permissions.") from None
        return "env"

    def remove(self, source_id):
        try:
            self.environment.put(source_id, None)
        except (OSError, ValueError):
            raise SecretsUnavailable("The project .env could not be updated. Check its writable mount and backend file permissions.") from None

    def env_prefix(self, source_id):
        return prefix_for(source_id)

    def load(self, source_id):
        row = self.db.one("SELECT ciphertext FROM source_credentials WHERE source_id=?", (source_id,))
        if not row:
            return None
        if row["ciphertext"] == "env":
            try:
                values = self.environment.get(source_id)
            except (OSError, ValueError):
                raise SecretsUnavailable("The saved connection .env could not be read. Check backend file permissions.") from None
            if values is None:
                raise SecretsUnavailable("The saved connection profile is missing from the project .env. Restore its configuration.")
            return values
        try:
            payload = json.loads(self._cipher().decrypt(row["ciphertext"]))
            if payload["source_id"] != source_id:
                raise ValueError()
            self.encrypt(source_id, payload["values"])
            self.db.execute("UPDATE source_credentials SET ciphertext='env' WHERE source_id=?", (source_id,))
            return payload["values"]
        except (InvalidToken, ValueError, KeyError, TypeError) as exc:
            raise SecretsUnavailable(
                "Saved database credentials could not be decrypted. Check the server credential key."
            ) from exc
