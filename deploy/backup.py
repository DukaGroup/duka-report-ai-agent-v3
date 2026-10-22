"""Authenticated, streaming backups. Run backup only after stopping the service."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat
import tarfile
import tempfile

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"DUKA-BACKUP-1\n"
CHUNK = 1024 * 1024


def key_bytes(path, create=False):
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if create:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as target:
                target.write(os.urandom(32))
                target.flush()
                os.fsync(target.fileno())
    with os.fdopen(os.open(path, flags), "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("Backup key must be a regular file with mode 600.")
        key = source.read(33)
        if len(key) != 32:
            raise ValueError("Invalid backup key.")
        return key


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def database_check(path):
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup database integrity check failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Backup database contains broken references.")


class EncryptedWriter:
    def __init__(self, output, cipher):
        self.output, self.cipher = output, cipher

    def write(self, data):
        self.output.write(self.cipher.update(data))
        return len(data)


def create_backup(data_dir, env_file, output, key_file):
    data_dir, env_file, output = data_dir.resolve(), env_file.resolve(), output.absolute()
    if not data_dir.is_dir() or not env_file.is_file():
        raise ValueError("Existing data and environment files are required.")
    if output.resolve().is_relative_to(data_dir) or key_file.resolve().is_relative_to(data_dir):
        raise ValueError("Keep the backup and its key outside DATA_DIR.")
    if output.exists() or output.is_symlink():
        raise ValueError("Refusing to overwrite an existing backup.")
    key = key_bytes(key_file, create=True)
    with tempfile.TemporaryDirectory(prefix="duka-backup-") as work:
        snapshot = Path(work) / "application.sqlite3"
        with sqlite3.connect((data_dir / "application.sqlite3").as_uri() + "?mode=ro", uri=True) as source:
            with sqlite3.connect(snapshot) as target:
                source.backup(target)
        database_check(snapshot)
        nonce = os.urandom(12)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        cipher.authenticate_additional_data(MAGIC)
        manifest, directories = {}, set()
        published = False
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as destination:
                destination.write(MAGIC + nonce)
                with tarfile.open(fileobj=EncryptedWriter(destination, cipher), mode="w|gz", dereference=True) as archive:
                    def add_directory(name):
                        if name not in directories:
                            info = tarfile.TarInfo(name)
                            info.type, info.mode = tarfile.DIRTYPE, 0o700
                            archive.addfile(info)
                            directories.add(name)

                    def add(path, name):
                        manifest[name] = digest(path)
                        archive.add(path, arcname=name, recursive=False)

                    def walk_error(error):
                        raise error

                    add_directory('config')
                    for base, dirs, files in os.walk(data_dir, followlinks=False, onerror=walk_error):
                        relative_base = Path(base).relative_to(data_dir).as_posix()
                        add_directory('data' if relative_base == '.' else 'data/' + relative_base)
                        dirs.sort()
                        for directory in dirs:
                            if (Path(base) / directory).is_symlink():
                                raise ValueError("Backup refuses linked directories; keep persistent data inside DATA_DIR.")
                        for name in sorted(files):
                            path = Path(base) / name
                            relative = path.relative_to(data_dir).as_posix()
                            if relative in ("application.sqlite3", "application.sqlite3-wal", "application.sqlite3-shm"):
                                continue
                            resolved = path.resolve()
                            if not resolved.is_relative_to(data_dir) or not resolved.is_file():
                                raise ValueError("Backup refuses external links and special files.")
                            add(resolved, "data/" + relative)
                    add(snapshot, "data/application.sqlite3")
                    add(env_file, "config/runtime.env")
                    info = tarfile.TarInfo("manifest.json")
                    content = json.dumps({"version": 1, "files": manifest, "directories": sorted(directories)}, sort_keys=True).encode()
                    info.size, info.mode = len(content), 0o600
                    import io
                    archive.addfile(info, io.BytesIO(content))
                destination.write(cipher.finalize() + cipher.tag)
                destination.flush()
                os.fsync(destination.fileno())
            verify_or_restore(output, key_file)
            published = True
        finally:
            if not published:
                output.unlink(missing_ok=True)


def decrypt(archive, key_file, destination):
    key = key_bytes(key_file)
    with archive.open("rb") as source, destination.open("xb") as target:
        os.chmod(destination, 0o600)
        if source.read(len(MAGIC)) != MAGIC:
            raise ValueError("Unsupported backup format.")
        nonce = source.read(12)
        length = archive.stat().st_size - len(MAGIC) - 12 - 16
        if length < 1:
            raise ValueError("Truncated backup.")
        source.seek(-16, os.SEEK_END)
        tag = source.read(16)
        source.seek(len(MAGIC) + 12)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        cipher.authenticate_additional_data(MAGIC)
        while length:
            block = source.read(min(length, CHUNK))
            if not block:
                raise ValueError("Truncated backup.")
            target.write(cipher.update(block))
            length -= len(block)
        # No archive extraction takes place before authentication succeeds.
        target.write(cipher.finalize())


def extract_verified(archive, destination):
    seen, hashes, directories, manifest = set(), {}, set(), None
    with tarfile.open(archive, mode="r:gz") as source:
        for member in source:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or ".." in name.parts or "\\" in member.name or not name.parts
                    or member.name in seen or not (member.isfile() or member.isdir())
                    or (name.parts[0] not in ("data", "config") and member.name != "manifest.json")):
                raise ValueError("Unsafe or duplicate backup member.")
            seen.add(member.name)
            if member.isdir():
                destination.joinpath(*name.parts).mkdir(parents=True, exist_ok=True, mode=0o700)
                directories.add(member.name)
                continue
            if member.name == "manifest.json":
                if member.size > 16 * 1024 * 1024:
                    raise ValueError("Backup manifest exceeds its limit.")
                manifest = json.load(source.extractfile(member))
                continue
            path = destination.joinpath(*name.parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with path.open("xb") as target, source.extractfile(member) as content:
                os.chmod(path, 0o700 if member.mode & 0o100 else 0o600)
                shutil.copyfileobj(content, target, CHUNK)
            hashes[member.name] = digest(path)
    if (not manifest or manifest.get("version") != 1 or manifest.get("files") != hashes
            or manifest.get('directories') != sorted(directories)):
        raise ValueError("Backup contents do not match the manifest.")
    if not {"data/application.sqlite3", "config/runtime.env"} <= hashes.keys():
        raise ValueError("Backup is missing required state.")
    database_check(destination / "data/application.sqlite3")
    for directory in [destination, *[p for p in destination.rglob("*") if p.is_dir()]]:
        directory.chmod(0o700)
    return len(hashes)


def verify_or_restore(archive, key_file, target=None):
    target = target.absolute() if target is not None else None
    if target is not None and (target.is_symlink() or (target.exists() and any(target.iterdir()))):
        raise ValueError("Restore requires a new or empty directory; existing data is never overwritten.")
    with tempfile.TemporaryDirectory(prefix="duka-restore-", dir=target.parent if target else None) as work:
        work = Path(work)
        decrypted = work / "archive.tar.gz"
        decrypt(archive, key_file, decrypted)
        payload = work / "payload"
        payload.mkdir(mode=0o700)
        count = extract_verified(decrypted, payload)
        if target is not None:
            if target.exists():
                target.rmdir()  # Fails if anything was added while verification ran.
            payload.rename(target)
        return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "verify", "restore"])
    parser.add_argument("--key-file", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("/var/lib/duka-agent"))
    parser.add_argument("--env-file", type=Path, default=Path("/var/lib/duka-agent/runtime.env"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "backup":
            if not args.output:
                parser.error("backup requires --output")
            create_backup(args.data_dir, args.env_file, args.output, args.key_file)
        else:
            if not args.archive or (args.command == "restore" and not args.target):
                parser.error("verify/restore require --archive; restore also requires --target")
            verify_or_restore(args.archive, args.key_file, args.target if args.command == "restore" else None)
    except Exception:
        parser.exit(1, "Backup operation failed. Check private file permissions, free space, archive/key pairing and the empty restore directory. No existing workspace was overwritten.\n")
    print("Backup operation completed and integrity checks passed.")


if __name__ == "__main__":
    main()
