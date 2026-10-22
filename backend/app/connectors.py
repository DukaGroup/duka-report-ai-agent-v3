"""Backend-only SQL Server connections and approved parameterized SELECT scripts.

Use a SQL Server account granted SELECT only. read_only is a routing hint, not an ACL.
The model sees dataset schemas/results, never credentials or SQL connection strings.
"""

import asyncio
import json
import math
import re
import time
from datetime import date, datetime
from decimal import Decimal
from dataclasses import replace
from typing import Any, Protocol

from jsonschema import Draft202012Validator, SchemaError

from .db import now
from .source_secrets import SourceSecrets, SecretsUnavailable
from .database_tools import DatabaseQuery, compile_select


class SourceNotConfigured(Exception):
    pass


class DatabaseUnavailable(SourceNotConfigured):
    def __init__(self, message, category="query", code=None):
        super().__init__(message)
        self.category, self.code = category, code


class ReportConnector(Protocol):
    async def fetch(self, query_key: str, parameters: dict[str, Any]) -> list[dict[str, Any]]: ...


def safe_database_error(exc):
    # Driver errors can include the host, login, database name and SQL text.
    message = str(exc).lower()
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    if code == 208 or "invalid object name" in message:
        return "The selected SQL table/view references an unavailable object. Check the view definition and access to its dependencies; the database connection itself is working."
    if code == 207 or "invalid column name" in message:
        return "A query column is unavailable. Refresh the table schema and use the current column names."
    if code == 8115 or "arithmetic overflow" in message:
        return "SQL Server reported a numeric overflow. Narrow the query or use a suitable numeric type."
    if "18456" in message or "login failed" in message:
        return "SQL Server authentication failed. Check SQLSERVER_USER and SQLSERVER_PASSWORD."
    if "4060" in message or "cannot open database" in message:
        return "The configured database could not be opened. Check SQLSERVER_DATABASE and login access."
    if "permission" in message or "229" in message:
        return "SQL Server denied access. Grant the reporting account SELECT on the approved tables/views."
    if "certificate" in message or "ssl" in message or "tls" in message:
        return "SQL Server TLS negotiation failed. Check the server encryption and certificate configuration."
    if "timeout" in message or "timed out" in message:
        return "SQL Server timed out. Check the host, port, firewall, and query performance."
    return "SQL Server could not complete the request. Check connectivity, database permissions, and the approved query script."


class QueryCatalog:
    def __init__(self, directory):
        self.directory = directory

    def load(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[a-zA-Z0-9_]+", key):
            raise SourceNotConfigured("Unknown approved query key.")
        try:
            manifest = json.loads((self.directory / f"{key}.json").read_text())
            sql = (self.directory / f"{key}.sql").read_text()
            Draft202012Validator.check_schema(manifest["parameters_schema"])
            # Operator-deployed files only; no SQL uploads or model-written SQL.
            plain = re.sub(r"/\*.*?\*/|--[^\n]*", " ", sql, flags=re.S).strip().rstrip(";")
            if (
                not re.match(r"^SELECT\b", plain, re.I)
                or ";" in plain
                or re.search(
                    r"\b(INTO|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXEC(?:UTE)?|MERGE|OPENROWSET|OPENDATASOURCE|OPENQUERY)\b",
                    plain,
                    re.I,
                )
            ):
                raise ValueError("Read-only SELECT required")
            placeholders = set(re.findall(r"%\(([a-zA-Z0-9_]+)\)s", sql))
            if not placeholders.issubset(manifest["parameters_schema"].get("properties", {})):
                raise ValueError("Unknown parameter")
            return manifest, sql
        except (OSError, ValueError, KeyError, TypeError, SchemaError) as exc:
            raise SourceNotConfigured(
                "The approved query script is missing or invalid. Ask an administrator to check the backend query files."
            ) from exc

    def list(self):
        queries = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                manifest, _ = self.load(path.stem)
                queries.append({"query_key": path.stem, **manifest})
            except SourceNotConfigured:
                queries.append({"query_key": path.stem, "error": "Query files are invalid."})
        return queries


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return "[binary value omitted]"
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


class SQLServerConnector:
    dialect = "sqlserver"
    error_message = staticmethod(safe_database_error)
    def __init__(self, settings, catalog, driver=None):
        self.settings, self.catalog, self.driver = settings, catalog, driver

    def missing(self):
        return [
            f"SQLSERVER_{key.upper()}"
            for key in ("host", "port", "user", "password")
            if not getattr(self.settings, f"sqlserver_{key}")
        ]

    def _connect(self):
        if self.missing():
            raise SourceNotConfigured("Missing connection settings: " + ", ".join(self.missing()))
        try:
            port = int(self.settings.sqlserver_port)
            if not 1 <= port <= 65535:
                raise ValueError()
        except ValueError as exc:
            raise SourceNotConfigured("SQLSERVER_PORT must be a number between 1 and 65535.") from exc
        if self.settings.sqlserver_encryption not in ("require", "request", "off"):
            raise SourceNotConfigured("SQLSERVER_ENCRYPTION must be require, request, or off.")
        from .deployment_security import production
        if production(self.settings) and self.settings.sqlserver_encryption != "require":
            raise SourceNotConfigured("Production SQL Server connections require encryption.")
        if production(self.settings):
            import os
            from .deployment_security import validate_freetds
            try:
                validate_freetds(os.getenv('FREETDSCONF'))
            except (OSError, ValueError):
                raise SourceNotConfigured("Production SQL Server requires the trusted FreeTDS configuration with CA and hostname validation.") from None
        driver = self.driver
        if driver is None:
            import pymssql

            driver = pymssql
        return driver.connect(
            server=self.settings.sqlserver_host,
            port=str(port),
            user=self.settings.sqlserver_user,
            password=self.settings.sqlserver_password,
            database=self.settings.sqlserver_database or "master",
            as_dict=True,
            login_timeout=self.settings.sqlserver_timeout,
            timeout=self.settings.sqlserver_timeout,
            tds_version="7.4",
            encryption=self.settings.sqlserver_encryption,
            read_only=True,
            autocommit=False,
            appname="Duka reporting",
        )

    def _run(self, sql, parameters, max_rows=500):
        return self._execute(sql, parameters, max_rows, 100000)

    def _run_full(self, sql, parameters):
        return self._execute(sql, parameters, self.settings.report_max_rows, self.settings.report_max_bytes)

    def _execute(self, sql, parameters, max_rows, max_bytes):
        connection = None
        traffic = getattr(self, "traffic", None)
        correlation, started, outcome, row_count, code = None, time.perf_counter(), "error", None, None
        failure = None
        if traffic:
            from .db import uid

            correlation = uid()
            traffic.record("backend-database", "sql/select", "started", correlation_id=correlation,
                           size=len(sql.encode()), detail={"bound_parameters": len(parameters)},payload={"sql":sql,"parameters":parameters})
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(sql, parameters)
            result, size = [], 2
            while batch := cursor.fetchmany(1000):
                if len(result) + len(batch) > max_rows:
                    raise DatabaseUnavailable(
                        "The complete result exceeds the configured row limit. Ask an administrator to increase it; no partial report was generated.",
                        "limit",
                    )
                for row in batch:
                    converted = {key: json_value(value) for key, value in row.items()}
                    if len(converted) > 100 or any(len(key) > 100 for key in converted):
                        raise DatabaseUnavailable(
                            "The query returned too many columns or long column names. Select at most 100 columns with short aliases."
                        )
                    # Count compact UTF-8 JSON, matching immutable snapshot storage.
                    # Escaped unicode/repeated formatting must not consume capacity.
                    size += len(json.dumps(converted, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode()) + 1
                    if size > max_bytes:
                        raise DatabaseUnavailable(
                            "The complete result exceeds the configured size limit. Ask an administrator to increase it; no partial report was generated.",
                            "limit",
                        )
                    result.append(converted)
            outcome, row_count = "ok", len(result)
            return result
        except SourceNotConfigured as exc:
            failure = str(exc)
            raise
        except Exception as exc:
            code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
            failure = self.error_message(exc)
            raise DatabaseUnavailable(failure, "query" if connection else "connection", code) from None
        finally:
            if connection:
                try:
                    connection.rollback()
                except Exception:
                    pass
                try:
                    connection.close()
                except Exception:
                    pass
            if traffic:
                traffic.record("database-backend", "sql/select", outcome, correlation_id=correlation,
                               duration_ms=round((time.perf_counter()-started)*1000, 2),
                               detail={"row_count": row_count, "database_error_code": code},
                               payload={"rows":result} if outcome=='ok' else {"error":failure,"database_error_code":code})

    async def check(self):
        if self.settings.sqlserver_database:
            await asyncio.to_thread(self._run, "SELECT 1 AS connected", {})
        else:
            await self.databases(limit=1)

    def _catalog_run(self, sql, parameters):
        # Discover from master, so an offline/default business database cannot
        # block discovery of the other databases. No system-data query is exposed.
        catalog = SQLServerConnector(replace(self.settings, sqlserver_database="master"), self.catalog, self.driver)
        catalog.traffic = getattr(self, "traffic", None)
        try:
            return catalog._run(sql, parameters)
        except DatabaseUnavailable:
            # Some restricted logins can inspect the catalog only via their DB.
            return self._run(sql, parameters)

    async def databases(self, offset=0, limit=100):
        """Inventory online business databases accessible to this reporting login."""
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid database catalog page. Use offset >= 0 and limit 1–200.")
        rows = await asyncio.to_thread(
            self._catalog_run,
            """SELECT name, CASE WHEN name=DB_NAME() THEN 1 ELSE 0 END AS is_default
            FROM sys.databases WHERE database_id>4 AND state=0 AND HAS_DBACCESS(name)=1
            ORDER BY name OFFSET %(offset)s ROWS FETCH NEXT %(size)s ROWS ONLY""",
            {"offset": offset, "size": limit + 1},
        )
        for row in rows:
            row["is_default"] = int(row["name"] == self.settings.sqlserver_database)
        return {"databases": rows[:limit], "next_offset": offset + limit if len(rows) > limit else None}

    async def in_database(self, database):
        # Names are bound catalog values and passed to the driver, never SQL fragments.
        # Use a separate connector: concurrent chats cannot mutate each other's target.
        if not isinstance(database, str) or not 1 <= len(database) <= 128 or "\x00" in database:
            raise ValueError("Choose a database name returned by list_databases.")
        if database == self.settings.sqlserver_database:
            return self
        allowed = await asyncio.to_thread(
            self._catalog_run,
            """SELECT name FROM sys.databases WHERE name=%(database)s
            AND database_id>4 AND state=0 AND HAS_DBACCESS(name)=1""",
            {"database": database},
        )
        if not allowed:
            raise SourceNotConfigured("Database is unavailable or the reporting login cannot access it.")
        connector = SQLServerConnector(replace(self.settings, sqlserver_database=allowed[0]["name"]), self.catalog, self.driver)
        connector.traffic = getattr(self, "traffic", None)
        return connector

    async def fetch(self, query_key, parameters):
        if not self.settings.sqlserver_database:
            raise SourceNotConfigured("Select a database from discover_databases before reading business data.")
        manifest, sql = self.catalog.load(query_key)
        Draft202012Validator(manifest["parameters_schema"]).validate(parameters)
        return await asyncio.to_thread(self._run, sql, parameters)

    async def fetch_report(self, query_key, parameters):
        if not self.settings.sqlserver_database:
            raise SourceNotConfigured("Select a database from discover_databases before reading business data.")
        manifest, sql = self.catalog.load(query_key)
        Draft202012Validator(manifest["parameters_schema"]).validate(parameters)
        return await asyncio.to_thread(self._run_full, sql, parameters)

    async def schemas(self, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid catalog page. Use a nonnegative offset and limit 1–200.")
        rows = await asyncio.to_thread(self._run, """SELECT TABLE_SCHEMA AS schema_name,
            SUM(CASE WHEN TABLE_TYPE='BASE TABLE' THEN 1 ELSE 0 END) AS table_count,
            SUM(CASE WHEN TABLE_TYPE='VIEW' THEN 1 ELSE 0 END) AS view_count
            FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA NOT IN ('sys','INFORMATION_SCHEMA')
            GROUP BY TABLE_SCHEMA ORDER BY TABLE_SCHEMA
            OFFSET %(offset)s ROWS FETCH NEXT %(size)s ROWS ONLY""", {"offset":offset,"size":limit+1})
        return {"schemas":rows[:limit], "next_offset":offset+limit if len(rows)>limit else None}

    async def tables(self, offset=0, limit=100, kind="all", name_contains="", schema=None):
        if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("Invalid catalog page. Use a nonnegative offset and limit 1–200.")
        if kind not in ("all", "table", "view") or not isinstance(name_contains, str) or len(name_contains) > 128:
            raise ValueError("Invalid table filter. Choose all/table/view and a short name fragment.")
        if schema is not None and (not isinstance(schema, str) or not 1 <= len(schema) <= 128):
            raise ValueError("Choose a schema name returned by list_schemas.")
        predicates, params = [], {"offset": offset, "size": limit + 1}
        if kind != "all":
            predicates.append("TABLE_TYPE=%(kind)s")
            params["kind"] = "BASE TABLE" if kind == "table" else "VIEW"
        if name_contains:
            predicates.append("TABLE_NAME LIKE %(name)s")
            params["name"] = "%" + name_contains.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]") + "%"
        if schema is not None:
            predicates.append("TABLE_SCHEMA=%(schema)s")
            params["schema"] = schema
        where = " WHERE " + " AND ".join(predicates) if predicates else ""
        rows = await asyncio.to_thread(
            self._run,
            """SELECT TABLE_SCHEMA AS schema_name, TABLE_NAME AS name, TABLE_TYPE AS kind
            FROM INFORMATION_SCHEMA.TABLES"""
            + where
            + """ ORDER BY TABLE_SCHEMA,TABLE_NAME
            OFFSET %(offset)s ROWS FETCH NEXT %(size)s ROWS ONLY""",
            params,
        )
        return {"tables": rows[:limit], "next_offset": offset + limit if len(rows) > limit else None}

    async def describe(self, schema, table):
        if (
            not isinstance(schema, str)
            or not isinstance(table, str)
            or not 1 <= len(schema) <= 128
            or not 1 <= len(table) <= 128
        ):
            raise ValueError("Use a schema and table name from list_tables.")
        params = {"schema": schema, "table": table}
        columns = await asyncio.to_thread(
            self._run,
            """SELECT COLUMN_NAME AS name, DATA_TYPE AS type,
            IS_NULLABLE AS nullable, NUMERIC_PRECISION AS precision, NUMERIC_SCALE AS scale
            FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA=%(schema)s AND TABLE_NAME=%(table)s
            ORDER BY ORDINAL_POSITION""",
            params,
        )
        if not columns:
            raise ValueError("Table not found or the reporting login cannot inspect it.")
        keys = await asyncio.to_thread(
            self._run,
            """SELECT pc.name AS column_name,
            rs.name AS referenced_schema, rt.name AS referenced_table, rc.name AS referenced_column,
            fk.name AS relationship
            FROM sys.foreign_key_columns fkc
            JOIN sys.foreign_keys fk ON fk.object_id=fkc.constraint_object_id
            JOIN sys.tables pt ON pt.object_id=fkc.parent_object_id
            JOIN sys.schemas ps ON ps.schema_id=pt.schema_id
            JOIN sys.columns pc ON pc.object_id=pt.object_id AND pc.column_id=fkc.parent_column_id
            JOIN sys.tables rt ON rt.object_id=fkc.referenced_object_id
            JOIN sys.schemas rs ON rs.schema_id=rt.schema_id
            JOIN sys.columns rc ON rc.object_id=rt.object_id AND rc.column_id=fkc.referenced_column_id
            WHERE ps.name=%(schema)s AND pt.name=%(table)s
            ORDER BY fk.name,fkc.constraint_column_id""",
            params,
        )
        return {"schema": schema, "table": table, "columns": columns, "relationships": keys}

    async def query(self, query, row_scopes=None):
        query = DatabaseQuery.model_validate(query)
        descriptions = {table.alias: await self.describe(table.schema_name, table.name) for table in query.tables}
        sql, params, columns = compile_select(query, descriptions, dialect=self.dialect, row_scopes=row_scopes)
        rows = await asyncio.to_thread(self._run, sql, params, 501)
        truncated = len(rows) > query.limit
        return {
            "rows": rows[: query.limit],
            "columns": columns,
            "row_count": min(len(rows), query.limit),
            "truncated": truncated,
            "query": query.model_dump(by_alias=True),
            "scope": "Limited preview; do not infer full-database totals."
            if truncated
            else "All matching rows within the result limit.",
        }

    async def report_query(self, query, row_scopes=None):
        """One cursor reads the entire filtered/grouped result; no TOP or OFFSET.

        Batching limits fetch memory without changing query membership or risking
        duplicate/missing rows from offset pagination on a changing database.
        """
        plan = DatabaseQuery.model_validate(query)
        descriptions = {table.alias: await self.describe(table.schema_name, table.name) for table in plan.tables}
        sql, params, columns = compile_select(plan, descriptions, complete=True, dialect=self.dialect, row_scopes=row_scopes)
        rows = await asyncio.to_thread(self._run_full, sql, params)
        return {
            "rows": rows,
            "columns": columns,
            "row_count": len(rows),
            "truncated": False,
            "query": plan.model_dump(by_alias=True, exclude={"limit"}),
            "scope": "All matching result rows; the chat preview limit does not apply to this Excel export.",
        }


    async def sap_context(self, schema):
        from .sap_context import inspect_context
        return await inspect_context(self, schema)

    async def balance_reconciliation(self, options):
        raise SourceNotConfigured(
            "Fixed backend accounting calculators are retired. Use model-authored calculate_data code over authorized queries."
        )

    async def sales_catalog(self, company=None):
        from .sales_discovery import discover_sales

        return await discover_sales(self, company)


class ConnectorRegistry:
    @staticmethod
    def connector_class(kind):
        if kind == "saphana":
            from .hana import HanaConnector
            return HanaConnector
        return SQLServerConnector

    def __init__(self, settings=None, db=None):
        self.connectors: dict[str, ReportConnector] = {}
        self.db, self.settings = db, settings
        self.secrets = SourceSecrets(settings, db) if db and settings else None
        self.catalog = QueryCatalog(settings.query_dir) if settings else None
        if db and settings:
            for saved in db.all("SELECT source_id FROM source_credentials WHERE ciphertext<>'env'"):
                try:
                    self.secrets.load(saved["source_id"])
                except SecretsUnavailable:
                    # The owning source reports its recovery error below; other
                    # configured sources can still be used independently.
                    pass
            for source in db.all("SELECT * FROM data_sources"):
                self.attach(source)

    def register(self, source_id: str, connector: ReportConnector):
        self.connectors[source_id] = connector

    def resolve_connector(self, source_id):
        if self.db:
            source = self.db.one("SELECT enabled FROM data_sources WHERE id=?", (source_id,))
            if not source or not source["enabled"]:
                self.connectors.pop(source_id, None)
                raise SourceNotConfigured("This connection is disconnected or has been removed. Ask an administrator to reconnect it.")
        connector = self.connectors.get(source_id)
        if type(connector) in (SQLServerConnector, self.connector_class("saphana")):
            effective = self.source_settings(source_id)
            prefix = "hana_" if connector.dialect == "hana" else "sqlserver_"
            fields = ("host", "port", "user", "password", "database", "encrypt", "validate_certificate", "tls_ca_certificate", "tls_server_name") if prefix == "hana_" else ("host", "port", "user", "password", "database", "encryption", "timeout")
            if any(
                getattr(effective, prefix + key) != getattr(connector.settings, prefix + key)
                for key in fields
            ):
                connector = type(connector)(effective, self.catalog, connector.driver)
                self.register(source_id, connector)
                self.status(source_id, "not_configured" if connector.missing() else "not_checked", checked=False)
        if isinstance(connector, SQLServerConnector):
            connector.traffic = getattr(self, "traffic", None)
            if connector.traffic:
                connector.traffic.protect_settings(connector.settings)
        return connector

    def attach(self, source):
        if not source.get("enabled", 1):
            self.connectors.pop(source["id"], None)
            self.status(source["id"], "disconnected", checked=False)
            return
        if source["kind"] in ("sqlserver", "saphana"):
            try:
                connector = self.connector_class(source["kind"])(self.source_settings(source["id"]), self.catalog)
            except SecretsUnavailable as exc:
                self.connectors.pop(source["id"], None)
                self.status(source["id"], "error", str(exc))
                return
            self.register(source["id"], connector)
            if getattr(self,'traffic',None):
                self.traffic.protect_settings(connector.settings)
            missing = connector.missing()
            self.status(
                source["id"],
                "not_configured" if missing else "not_checked",
                "Missing connection settings: " + ", ".join(missing) if missing else None,
                checked=False,
            )

    def source_settings(self, source_id):
        environment = self.source_environment(source_id)
        # An explicitly configured environment is authoritative, even when partial.
        # Never mix credentials from .env with stale settings saved in the form.
        profile = self.db.one("SELECT credential_profile FROM data_sources WHERE id=?", (source_id,))
        if profile and profile["credential_profile"] != "saved":
            return environment
        values = self.secrets.load(source_id)
        updates = {key.lower(): value for key, value in (values or {}).items()}
        if "sqlserver_timeout" in updates:
            try:
                updates["sqlserver_timeout"] = int(updates["sqlserver_timeout"])
                if updates["sqlserver_timeout"] < 1:
                    raise ValueError()
            except (TypeError, ValueError):
                raise SecretsUnavailable("The SQL Server timeout must be a positive number.") from None
        for key in ("hana_encrypt", "hana_validate_certificate"):
            if key in updates:
                if updates[key] not in ("true", "false"):
                    raise SecretsUnavailable("HANA TLS options must be true or false.")
                updates[key] = updates[key] == "true"
        return replace(self.empty_connection_settings(), **updates)

    def empty_connection_settings(self):
        return replace(self.settings, sqlserver_host="", sqlserver_user="", sqlserver_password="", sqlserver_database="", sqlserver_port="1433", hana_host="", hana_user="", hana_password="", hana_database="", hana_port="30015", hana_encrypt=True, hana_validate_certificate=True, hana_tls_ca_certificate="", hana_tls_server_name="")

    def source_environment(self, source_id):
        source = self.db.one("SELECT name,kind,credential_profile FROM data_sources WHERE id=?", (source_id,))
        if source and source["kind"] == "saphana":
            if source["credential_profile"] == "legacy":
                self.db.execute("UPDATE data_sources SET credential_profile='HANA' WHERE id=?", (source_id,))
            if source["credential_profile"] == "saved":
                return self.empty_connection_settings()
            try:
                return self.empty_connection_settings().hana_environment()
            except (OSError, ValueError):
                raise SecretsUnavailable("The SAP HANA .env configuration could not be read. Check field values and backend file permissions.") from None
        if source and source["credential_profile"] == "legacy":
            prefix = re.sub(r"[^A-Z0-9]+", "_", source["name"].upper()).strip("_")
            named = self.settings.database_environment(prefix + "_SQLSERVER") if prefix else None
            saved = self.db.one("SELECT source_id FROM source_credentials WHERE source_id=?", (source_id,))
            first = self.db.one("SELECT id FROM data_sources WHERE kind='sqlserver' ORDER BY created_at,rowid LIMIT 1")
            generic = self.settings.database_environment()
            generic_configured = any(getattr(generic, "sqlserver_" + key) for key in ("host", "user", "password", "database"))
            if named is not None:
                profile = prefix + "_SQLSERVER"
            elif saved and (not generic_configured or first and first["id"] != source_id):
                profile = "saved"
            else:
                profile = "SQLSERVER"
            self.db.execute("UPDATE data_sources SET credential_profile=? WHERE id=?", (profile, source_id))
        else:
            profile = source["credential_profile"] if source else "saved"
        if profile == "saved":
            return self.empty_connection_settings()
        if profile == "SQLSERVER" and source:
            prefix = re.sub(r"[^A-Z0-9]+", "_", source["name"].upper()).strip("_")
            if prefix and self.settings.database_environment(prefix + "_SQLSERVER") is not None:
                profile = prefix + "_SQLSERVER"
                self.db.execute("UPDATE data_sources SET credential_profile=? WHERE id=?", (profile, source_id))
        return self.settings.database_environment(profile) or self.empty_connection_settings()

    def public_source(self, source):
        result = dict(source)
        try:
            self.source_environment(source["id"])
        except SecretsUnavailable:
            # Preserve metadata access so an administrator can repair this
            # connection without blocking the other sources or the editor.
            pass
        profile = self.db.one("SELECT credential_profile FROM data_sources WHERE id=?", (source["id"],))
        result.pop("credential_profile", None)
        result["configuration_origin"] = "saved" if profile["credential_profile"] == "saved" else "environment"
        result["credential_storage"] = ".env"
        result["env_prefix"] = self.secrets.env_prefix(source["id"]) if result["configuration_origin"] == "saved" else profile["credential_profile"] + "_"
        result["error_scope"] = (
            "query" if source["status"] == "connected" and source.get("last_error") else "connection"
        )
        try:
            effective = self.source_settings(source["id"])
            prefix = "HANA" if source["kind"] == "saphana" else "SQLSERVER"
            result["connection_fields"] = {
                f"{prefix}_{key.upper()}": bool(getattr(effective, f"{prefix.lower()}_{key}"))
                for key in ("host", "port", "user", "password", "database")
            }
            result["database_scope"] = "default" if getattr(effective, prefix.lower()+"_database") else "all"
            if prefix == "HANA":
                result["tls"] = {"encrypt": effective.hana_encrypt, "validate_certificate": effective.hana_validate_certificate,
                                 "custom_ca": bool(effective.hana_tls_ca_certificate), "server_name_configured": bool(effective.hana_tls_server_name)}
        except SecretsUnavailable as exc:
            result["connection_fields"] = {}
            result.update(status="error", last_error=str(exc), error_scope="connection")
            self.status(source["id"], "error", str(exc))
        return result

    def status(self, source_id, status, error=None, checked=True):
        if self.db:
            self.db.execute(
                "UPDATE data_sources SET status=?,last_error=?,checked_at=? WHERE id=? AND enabled=1",
                (status, error, now() if checked else None, source_id),
            )

    def configuration(self):
        environment = self.settings.database_environment()
        return {
            "environment": {
                f"SQLSERVER_{key.upper()}": bool(getattr(environment, f"sqlserver_{key}"))
                for key in ("host", "port", "user", "password", "database")
            },
            "queries": self.catalog.list(),
        }

    async def check(self, source_id):
        connector = self.resolve_connector(source_id)
        if not connector or not hasattr(connector, "check"):
            source = (
                self.db.one("SELECT kind,last_error FROM data_sources WHERE id=?", (source_id,)) if self.db else None
            )
            if source and source["kind"] in ("sqlserver", "saphana") and source["last_error"]:
                raise SourceNotConfigured(source["last_error"])
            raise SourceNotConfigured("No connector is implemented for this source type. Choose SQL Server or SAP HANA.")
        try:
            await connector.check()
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "connected")
        except SourceNotConfigured as exc:
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "not_configured" if connector.missing() else "error", str(exc))

    async def fetch(self, dataset, parameters, *, complete=False, user_id=None):
        connector = self.resolve_connector(dataset["source_id"])
        if not connector or not dataset["enabled"]:
            raise SourceNotConfigured(
                "This database is not connected yet. An administrator must configure its connector and enable the dataset."
            )
        if user_id:
            from .data_access import DataAccess
            access = DataAccess(self.db)
            self.authorized_source(user_id, dataset['source_id'])
            if access.scoped(user_id,dataset['source_id']):
                raise SourceNotConfigured("Company/database-restricted members must use structured queries; this registered script has no verified access boundary.")
        Draft202012Validator(json.loads(dataset["parameters_schema_json"])).validate(parameters)
        try:
            method = connector.fetch_report if complete and hasattr(connector, "fetch_report") else connector.fetch
            rows = await method(dataset["query_key"], parameters)
            if self.connectors.get(dataset["source_id"]) is connector:
                self.status(dataset["source_id"], "connected")
            return rows
        except SourceNotConfigured as exc:
            if self.connectors.get(dataset["source_id"]) is connector:
                self.status(dataset["source_id"], "error", str(exc))
            raise

    def authorized_source(self, user_id, source_id):
        source = self.db.one(
            """SELECT s.* FROM data_sources s JOIN users u ON u.id=? AND u.active=1
            WHERE s.id=? AND s.enabled=1 AND (u.role IN ('devs','president') OR EXISTS(SELECT 1 FROM source_grants g WHERE g.source_id=s.id AND g.user_id=u.id))""",
            (user_id, source_id),
        )
        if not source or source["kind"] not in ("sqlserver", "saphana"):
            raise SourceNotConfigured("Database source is unavailable or access was not granted.")
        return source

    def accessible_sources(self, user_id):
        return self.db.all(
            """SELECT s.id,s.name,s.kind,s.status FROM data_sources s JOIN users u ON u.id=? AND u.active=1
            WHERE s.kind IN ('sqlserver','saphana') AND s.enabled=1 AND (u.role IN ('devs','president') OR EXISTS(SELECT 1 FROM source_grants g WHERE g.source_id=s.id AND g.user_id=u.id))
            ORDER BY s.created_at""",
            (user_id,),
        )

    async def database_inventory(self, user_id):
        """Discover every granted source; a failed server cannot hide other servers."""
        semaphore = asyncio.Semaphore(4)

        async def inspect(source):
            async with semaphore:
                databases, offset, warnings, unavailable, complete = [], 0, [], [], True
                try:
                    while True:
                        page = await self.database_call(user_id, source["id"], "databases", offset=offset, limit=200)
                        databases.extend(page["databases"])
                        warnings.extend(page.get("warnings", []))
                        unavailable.extend(page.get("unavailable_databases", []))
                        complete = complete and page.get("catalog_complete", True)
                        if page["next_offset"] is None:
                            break
                        offset = page["next_offset"]
                    return {**source, "databases": databases, "catalog_complete": complete, "warnings": list(dict.fromkeys(warnings)),
                            "unavailable_databases": list(dict.fromkeys(unavailable))}
                except (SourceNotConfigured, ValueError) as exc:
                    return {**source, "databases": databases, "catalog_complete": False, "error": str(exc)}

        sources = await asyncio.gather(*(inspect(source) for source in self.accessible_sources(user_id)))
        return {"sources": sources, "catalog_complete": all(s["catalog_complete"] for s in sources),
                "scope": "Only sources, databases and companies authorized for this user. System databases are excluded. Company restrictions returned by discovery and queries are enforced before reading data; do not infer business coverage from a database or company name."}

    async def database_call(self, user_id, source_id, operation, database=None, **arguments):
        self.authorized_source(user_id, source_id)
        from .data_access import DataAccess, restricted_call
        access = DataAccess(self.db)
        if operation == "balance_reconciliation":
            raise SourceNotConfigured(
                "Fixed backend accounting calculators are retired. Use model-authored calculate_data code over authorized queries."
            )
        connector = self.resolve_connector(source_id)
        if not isinstance(connector, SQLServerConnector):
            raise SourceNotConfigured(
                "This database connection is not configured. Ask the administrator to configure the source."
            )
        traffic = getattr(self, "traffic", None)
        started, outcome, detail = time.perf_counter(), "error", {"source_id": source_id}
        if traffic:
            traffic.record("backend-database", operation, "started", user_id=user_id, correlation_id=source_id)
        try:
            prefix = "hana_" if connector.dialect == "hana" else "sqlserver_"
            if operation != "databases" and database is None and not getattr(connector.settings, prefix + "database"):
                raise SourceNotConfigured("Select a database from discover_databases before reading business data.")
            selected_database = database
            if operation != "databases":
                if selected_database is None:
                    selected_database = getattr(connector.settings, prefix + "database") or None
                if selected_database is not None and (
                    not isinstance(selected_database, str) or not 1 <= len(selected_database) <= 128 or "\x00" in selected_database
                ):
                    raise ValueError("Choose a database name returned by discovery.")
                # Reject an ungranted target before even probing its catalog or
                # selecting a tenant. Audit/history discovery has the same gate.
                access.stamp(user_id, source_id, selected_database)
            active_connector = await connector.in_database(selected_database) if selected_database else connector
            actual_database = getattr(active_connector.settings, prefix+"database") or None
            stamp = access.stamp(user_id,source_id,None if operation == 'databases' else actual_database)
            if operation == 'databases' and access.scoped(user_id,source_id):
                allowed = {r['database_name']:r for r in self.db.all('SELECT * FROM database_grants WHERE user_id=? AND source_id=?',(user_id,source_id))}
                rows, offset, warnings = [], 0, []
                while True:
                    page = await connector.databases(offset=offset,limit=200)
                    rows.extend({**r,'all_companies':bool(allowed[r['name']]['all_companies']),'companies':json.loads(allowed[r['name']]['companies_json'])} for r in page['databases'] if r['name'] in allowed)
                    warnings.extend(page.get('warnings',[]))
                    if page['next_offset'] is None:
                        break
                    offset = page['next_offset']
                start,size = arguments.get('offset',0),arguments.get('limit',100)
                if type(start) is not int or start<0 or type(size) is not int or not 1<=size<=200:
                    raise ValueError('Invalid database catalog page.')
                result = {'databases':rows[start:start+size],'next_offset':start+size if len(rows)>start+size else None,'warnings':list(dict.fromkeys(warnings))}
            else:
                units = access.rule(user_id,source_id,actual_database) if operation != 'databases' else None
                result = await restricted_call(active_connector,operation,arguments,units) if access.scoped(user_id,source_id) and operation != 'databases' else await getattr(active_connector, operation)(**arguments)
            self.authorized_source(user_id, source_id)
            if stamp != access.stamp(user_id,source_id,None if operation == 'databases' else actual_database):
                raise SourceNotConfigured('Data access changed during the request. Retry with the current grants.')
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "connected")
            outcome = "ok"
            if isinstance(result, dict):
                result = {**result, "source_id": source_id, "database": actual_database, "access_stamp":stamp,
                          **({'access_scope':{'all_companies':units is None,'companies':units or []}} if operation != 'databases' else {})}
            detail["row_count"] = result.get("row_count") if isinstance(result, dict) else len(result)
            return result
        except DatabaseUnavailable as exc:
            detail["database_error_code"] = exc.code
            detail["error_category"] = exc.category
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "connected" if exc.category in ("query", "limit") else "error", str(exc))
            raise
        finally:
            if traffic:
                traffic.record("database-backend", operation, outcome, user_id=user_id, correlation_id=source_id,
                               duration_ms=round((time.perf_counter()-started)*1000, 2), detail=detail)
