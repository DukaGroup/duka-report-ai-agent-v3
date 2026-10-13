"""Encrypted per-source credentials, outside public source metadata.

The key belongs to the private data volume, never the Codex workspace/environment.
Back up the key together with the application database.
"""

import json
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretsUnavailable(Exception):
    pass


class SourceSecrets:
    def __init__(self, settings, db):
        self.path = settings.data_dir / "source-credentials.key"
        self.db = db

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
        return self._cipher().encrypt(json.dumps({"source_id": source_id, "values": values}).encode()).decode()

    def load(self, source_id):
        row = self.db.one("SELECT ciphertext FROM source_credentials WHERE source_id=?", (source_id,))
        if not row:
            return None
        try:
            payload = json.loads(self._cipher().decrypt(row["ciphertext"]))
            if payload["source_id"] != source_id:
                raise ValueError()
            return payload["values"]
        except (InvalidToken, ValueError, KeyError, TypeError) as exc:
            raise SecretsUnavailable(
                "Saved database credentials could not be decrypted. Check the server credential key."
            ) from exc
