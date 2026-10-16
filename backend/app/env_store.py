"""Locked, literal .env profiles; bind-mounted files need in-place writes + recovery."""

import fcntl
import hashlib
import io
import json
import os
import re
import uuid
from contextlib import contextmanager

from dotenv import dotenv_values
from dotenv.parser import parse_stream


def read_environment(path):
    with path.open() as source:
        fcntl.flock(source, fcntl.LOCK_SH)
        return dict(dotenv_values(stream=io.StringIO(source.read()), interpolate=False))


def prefix_for(source_id):
    try:
        suffix = uuid.UUID(source_id).hex
    except ValueError:
        suffix = hashlib.sha256(source_id.encode()).hexdigest()[:32]
    return "DUKA_CONNECTION_" + suffix.upper() + "_"


class EnvStore:
    def __init__(self, settings):
        self.path = settings.env_file or settings.data_dir / ".env"
        self.journal = settings.data_dir / ".connection-env-recovery.json"

    @contextmanager
    def locked(self):
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "r+", encoding="utf-8") as source:
            fcntl.flock(source, fcntl.LOCK_EX)
            if self.journal.exists():
                recovery = json.loads(self.journal.read_text())
                current = source.read()
                if recovery["path"] != str(self.path):
                    raise OSError("Environment recovery path mismatch")
                if hashlib.sha256(current.encode()).hexdigest() != recovery["after_sha"]:
                    self.write(source, recovery["before"])
                self.journal.unlink()
            source.seek(0)
            yield source

    @staticmethod
    def write(source, value):
        source.seek(0)
        source.write(value)
        source.truncate()
        source.flush()
        os.fsync(source.fileno())

    def get(self, source_id):
        with self.locked() as source:
            values = dict(dotenv_values(stream=io.StringIO(source.read()), interpolate=False))
        prefix = prefix_for(source_id)
        if values.get(prefix + "PRESENT") != "true":
            return None
        result = {key[len(prefix):]:value or "" for key,value in values.items() if key.startswith(prefix) and key != prefix + "PRESENT"}
        if not result:
            raise OSError("Empty managed connection profile")
        return result

    def put(self, source_id, values):
        prefix = prefix_for(source_id)
        if values is not None:
            for key,value in values.items():
                if not re.fullmatch(r"(?:SQLSERVER|HANA)_[A-Z_]+", key) or any(ord(c)<32 and c not in "\r\n\t\b\f" for c in value):
                    raise ValueError("Invalid environment connection field.")
        with self.locked() as source:
            before = source.read()
            # Parse complete bindings so quoted multiline values are removed
            # together. Single quotes also stop Docker Compose interpolation.
            after = "".join(binding.original.string for binding in parse_stream(io.StringIO(before))
                            if not binding.key or not binding.key.startswith(prefix))
            if values is not None:
                after = after.rstrip("\n") + "\n" + prefix + "PRESENT='true'\n"
                for key,value in sorted(values.items()):
                    literal = str(value).replace("\\", "\\\\").replace("'", "\\'")
                    after += prefix + key + "='" + literal + "'\n"
            if after == before:
                return
            payload = json.dumps({"path":str(self.path), "before":before, "after_sha":hashlib.sha256(after.encode()).hexdigest()})
            temporary = self.journal.with_suffix(".tmp")
            with open(temporary, "w", opener=lambda path,flags: os.open(path,flags,0o600)) as journal:
                journal.write(payload)
                journal.flush()
                os.fsync(journal.fileno())
            temporary.replace(self.journal)
            directory = os.open(self.journal.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            try:
                self.write(source, after)
            except BaseException:
                self.write(source, before)
                self.journal.unlink(missing_ok=True)
                raise
            self.journal.unlink()
