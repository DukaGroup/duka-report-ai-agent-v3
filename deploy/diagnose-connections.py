"""Run on the native server as duka. Prints safe source diagnostics, never credentials."""

import argparse
import asyncio
from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import sys


async def main(source_id=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from dotenv import load_dotenv

    path = Path(os.getenv("ENV_FILE", "/var/lib/duka-agent/runtime.env"))
    os.environ.setdefault("DATA_DIR", "/var/lib/duka-agent")
    os.environ.setdefault("FREETDSCONF", str(Path(__file__).with_name("freetds.conf")))
    load_dotenv(path, override=False, interpolate=False)
    from app.config import Settings
    from app.db import Database
    from app.env_store import read_environment
    from app.connection_diagnostics import profile_settings, network_check, check_login
    from app.database_tls import warnings as tls_warnings

    settings = Settings(env_file=path)

    class ReadOnlyDatabase(Database):
        @contextmanager
        def connect(self):
            connection = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
            finally:
                connection.close()

    db = ReadOnlyDatabase(settings.data_dir / "application.sqlite3")
    values = read_environment(path)
    sources = db.all(
        "SELECT id,name,kind,credential_profile FROM data_sources WHERE enabled=1 AND kind IN ('sqlserver','saphana')"
    )
    results = []
    for source in sources:
        if source_id and source["id"] != source_id:
            continue
        result = {"source_id": source["id"], "source_name": source["name"], "kind": source["kind"], "checks": []}
        try:
            configured = profile_settings(
                settings,
                source,
                values,
                db.one("SELECT ciphertext FROM source_credentials WHERE source_id=?", (source["id"],)),
            )
            result["tls_warnings"] = tls_warnings(configured, source["kind"])
            network = network_check(configured, source["kind"])
            result["checks"].append(network)
            if network["status"] == "ok":
                result["checks"].append(await check_login(configured, source["kind"]))
        except Exception:
            result["checks"].append(
                {
                    "stage": "configuration",
                    "status": "error",
                    "message": "Could not read this source profile. Check runtime.env presence, permissions and source configuration.",
                }
            )
        results.append(result)
    print(
        json.dumps(
            {
                "sources": results,
                "note": "No source profiles or business records were changed. TLS trust-cache files may be refreshed. No credentials or raw driver exceptions are printed.",
            },
            indent=2,
        )
    )
    return 0 if results and all(c["status"] == "ok" for r in results for c in r["checks"]) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(main(args.source_id)))
    except Exception:
        parser.exit(
            1,
            "Could not read the native workspace. Check runtime.env, data-directory permissions and service initialization.\n",
        )
