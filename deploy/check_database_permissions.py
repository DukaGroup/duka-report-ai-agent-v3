"""Read-only privilege inventory for operators; never grants/revokes permissions."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from dataclasses import replace
from contextlib import contextmanager
import sqlite3

SQL_SERVER_CHECKS = [
    "SELECT IS_SRVROLEMEMBER('sysadmin') AS is_admin",
    "SELECT permission_name FROM fn_my_permissions(NULL, 'SERVER')",
    "SELECT permission_name FROM fn_my_permissions(NULL, 'DATABASE')",
    "SELECT DISTINCT p.permission_name FROM sys.objects o CROSS APPLY "
    "sys.fn_my_permissions(QUOTENAME(SCHEMA_NAME(o.schema_id))+'.'+QUOTENAME(o.name), 'OBJECT') p "
    "WHERE o.is_ms_shipped=0",
]
READ_ONLY = {
    'SELECT', 'CONNECT', 'CONNECT SQL', 'VIEW DEFINITION', 'VIEW ANY DEFINITION', 'VIEW ANY DATABASE',
    'VIEW CHANGE TRACKING', 'VIEW DATABASE STATE', 'VIEW SERVER STATE', 'VIEW DATABASE PERFORMANCE STATE',
    'VIEW SERVER PERFORMANCE STATE', 'VIEW SECURITY DEFINITION', 'VIEW PERFORMANCE DEFINITION',
    'CATALOG READ', 'METADATA READ',
}


def inspect(connector):
    if connector.dialect == 'hana':
        rows = connector._run_full(
            'SELECT DISTINCT PRIVILEGE AS "permission_name" FROM SYS.EFFECTIVE_PRIVILEGES WHERE USER_NAME=CURRENT_USER', {}
        )
        if not rows:
            return {'status': 'unverified', 'reason': 'Effective privileges were not visible.'}
    else:
        admin = connector._run_full(SQL_SERVER_CHECKS[0], {})
        if not admin or admin[0].get('is_admin') is None:
            return {'status': 'unverified', 'reason': 'Server-role membership could not be verified.'}
        if admin[0]['is_admin']:
            return {'status': 'requires_dba', 'non_read_permissions': ['sysadmin']}
        rows = []
        for query in SQL_SERVER_CHECKS[1:]:
            rows.extend(connector._run_full(query, {}))
        if not rows:
            return {'status': 'unverified', 'reason': 'Effective privileges were not visible.'}
    extra = sorted({str(row['permission_name']).upper() for row in rows} - READ_ONLY)
    return {'status': 'requires_dba' if extra else 'read_only_inventory', 'non_read_permissions': extra}


async def run(source_id=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
    from dotenv import load_dotenv
    path = Path(os.getenv('ENV_FILE', '/var/lib/duka-agent/runtime.env'))
    os.environ.setdefault('DATA_DIR', '/var/lib/duka-agent')
    load_dotenv(path, override=False, interpolate=False)
    from app.config import Settings
    from app.connectors import SQLServerConnector, QueryCatalog
    from app.hana import HanaConnector
    from app.db import Database
    from app.env_store import prefix_for, read_environment
    os.environ.setdefault('FREETDSCONF', str(Path(__file__).with_name('freetds.conf')))
    settings = Settings(env_file=path)
    class ReadOnlyDatabase(Database):
        @contextmanager
        def connect(self):
            connection = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
            finally:
                connection.close()
    db = ReadOnlyDatabase(settings.data_dir / 'application.sqlite3')
    values = read_environment(path)
    sources = db.all("SELECT id,kind,credential_profile FROM data_sources WHERE enabled=1 AND kind IN ('sqlserver','saphana')")
    results = []
    for source in sources:
        if source_id and source['id'] != source_id:
            continue
        try:
            profile = source['credential_profile']
            base = replace(settings, sqlserver_host='',sqlserver_user='',sqlserver_password='',sqlserver_database='',
                           hana_host='',hana_user='',hana_password='',hana_database='')
            if profile == 'saved':
                saved = db.one('SELECT ciphertext FROM source_credentials WHERE source_id=?', (source['id'],))
                prefix = prefix_for(source['id'])
                if not saved or saved['ciphertext'] != 'env' or values.get(prefix + 'PRESENT') != 'true':
                    raise ValueError('Start the upgraded app to finish legacy credential migration first.')
                updates = {key[len(prefix):].lower(): value or '' for key,value in values.items()
                           if key.startswith(prefix) and key != prefix + 'PRESENT'}
                for key in ('hana_encrypt','hana_validate_certificate','sqlserver_validate_certificate'):
                    if key in updates:
                        if updates[key] not in ('true','false'):
                            raise ValueError('Invalid TLS option')
                        updates[key] = updates[key] == 'true'
                if 'sqlserver_timeout' in updates:
                    updates['sqlserver_timeout'] = int(updates['sqlserver_timeout'])
                configured = replace(base, **updates)
            elif profile == 'legacy':
                raise ValueError('Start the upgraded service to finish legacy profile migration first.')
            else:
                configured = base.hana_environment() if source['kind'] == 'saphana' else base.database_environment(profile)
            if configured is None:
                raise ValueError('Missing configuration')
            connector = (HanaConnector if source['kind'] == 'saphana' else SQLServerConnector)(configured, QueryCatalog(settings.query_dir))
            names, offset = [], 0
            while True:
                page = await connector.databases(offset=offset, limit=100)
                names.extend(row['name'] for row in page['databases'])
                offset = page.get('next_offset')
                if offset is None:
                    break
                if len(names) >= 1000:
                    raise ValueError('Inventory too large')
            if not names:
                raise ValueError('No visible databases')
            for name in names:
                try:
                    target = await connector.in_database(name)
                    result = await asyncio.to_thread(inspect, target)
                except Exception:
                    result = {'status': 'unverified', 'reason': 'Privilege inventory failed; ask the DBA to verify it.'}
                results.append({'source_id': source['id'], 'database': name, **result})
        except Exception:
            results.append({'source_id': source['id'], 'status': 'unverified',
                            'reason': 'Source inventory failed; check connection access with the DBA.'})
    print(json.dumps({'checks': results, 'scope': 'Visible databases only; no changes were made. Privilege inventory does not verify TLS certificates or which business objects should be approved.'}, indent=2))
    return 0 if results and all(row['status'] == 'read_only_inventory' for row in results) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-id')
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run(args.source_id)))
    except Exception:
        parser.exit(1, 'Could not inspect privileges. Check private configuration and database connectivity.\n')
