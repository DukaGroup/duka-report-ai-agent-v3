"""Backend-only SQL Server connections and approved parameterized SELECT scripts.

Use a SQL Server account granted SELECT only. read_only is a routing hint, not an ACL.
The model sees dataset schemas/results, never credentials or SQL connection strings.
"""

import asyncio
import json
import math
import re
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
    def __init__(self, settings, catalog, driver=None):
        self.settings, self.catalog, self.driver = settings, catalog, driver

    def missing(self):
        return [
            f"SQLSERVER_{key.upper()}"
            for key in ("host", "port", "user", "password", "database")
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
        driver = self.driver
        if driver is None:
            import pymssql

            driver = pymssql
        return driver.connect(
            server=self.settings.sqlserver_host,
            port=str(port),
            user=self.settings.sqlserver_user,
            password=self.settings.sqlserver_password,
            database=self.settings.sqlserver_database,
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
        connection = None
        try:
            connection = self._connect()
            cursor = connection.cursor()
            cursor.execute(sql, parameters)
            rows = cursor.fetchmany(max_rows + 1)
            if len(rows) > max_rows:
                raise DatabaseUnavailable(
                    "The query returned more than 500 rows. Narrow the parameters or use an aggregate query; no partial report was generated."
                )
            result = [{key: json_value(value) for key, value in row.items()} for row in rows]
            if any(len(row) > 100 or any(len(key) > 100 for key in row) for row in result):
                raise DatabaseUnavailable(
                    "The query returned too many columns or long column names. Select at most 100 columns with short aliases."
                )
            if len(json.dumps(result).encode()) > 100000:
                raise DatabaseUnavailable(
                    "The query returned more than 100 KB. Narrow the parameters or use an aggregate query."
                )
            return result
        except SourceNotConfigured:
            raise
        except Exception as exc:
            code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
            raise DatabaseUnavailable(safe_database_error(exc), "query" if connection else "connection", code) from None
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

    async def check(self):
        await asyncio.to_thread(self._run, "SELECT 1 AS connected", {})

    async def fetch(self, query_key, parameters):
        manifest, sql = self.catalog.load(query_key)
        Draft202012Validator(manifest["parameters_schema"]).validate(parameters)
        return await asyncio.to_thread(self._run, sql, parameters)

    async def tables(self, offset=0, limit=100, kind="all", name_contains=""):
        if not isinstance(offset, int) or offset < 0 or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("Invalid catalog page. Use a nonnegative offset and limit 1–200.")
        if kind not in ("all", "table", "view") or not isinstance(name_contains, str) or len(name_contains) > 128:
            raise ValueError("Invalid table filter. Choose all/table/view and a short name fragment.")
        predicates, params = [], {"offset": offset, "size": limit + 1}
        if kind != "all":
            predicates.append("TABLE_TYPE=%(kind)s")
            params["kind"] = "BASE TABLE" if kind == "table" else "VIEW"
        if name_contains:
            predicates.append("TABLE_NAME LIKE %(name)s")
            params["name"] = "%" + name_contains.replace("[", "[[]").replace("%", "[%]").replace("_", "[_]") + "%"
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

    async def query(self, query):
        query = DatabaseQuery.model_validate(query)
        descriptions = {table.alias: await self.describe(table.schema_name, table.name) for table in query.tables}
        sql, params, columns = compile_select(query, descriptions)
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


class ConnectorRegistry:
    def __init__(self, settings=None, db=None):
        self.connectors: dict[str, ReportConnector] = {}
        self.db, self.settings = db, settings
        self.secrets = SourceSecrets(settings, db) if db and settings else None
        self.catalog = QueryCatalog(settings.query_dir) if settings else None
        if db and settings:
            for source in db.all("SELECT * FROM data_sources"):
                self.attach(source)

    def register(self, source_id: str, connector: ReportConnector):
        self.connectors[source_id] = connector

    def resolve_connector(self, source_id):
        connector = self.connectors.get(source_id)
        if type(connector) is SQLServerConnector:
            effective = self.source_settings(source_id)
            fields = ("host", "port", "user", "password", "database", "encryption", "timeout")
            if any(
                getattr(effective, "sqlserver_" + key) != getattr(connector.settings, "sqlserver_" + key)
                for key in fields
            ):
                connector = SQLServerConnector(effective, self.catalog, connector.driver)
                self.register(source_id, connector)
                self.status(source_id, "not_configured" if connector.missing() else "not_checked", checked=False)
        return connector

    def attach(self, source):
        if source["kind"] == "sqlserver":
            try:
                connector = SQLServerConnector(self.source_settings(source["id"]), self.catalog)
            except SecretsUnavailable as exc:
                self.connectors.pop(source["id"], None)
                self.status(source["id"], "error", str(exc))
                return
            self.register(source["id"], connector)
            missing = connector.missing()
            self.status(
                source["id"],
                "not_configured" if missing else "not_checked",
                "Missing connection settings: " + ", ".join(missing) if missing else None,
                checked=False,
            )

    def source_settings(self, source_id):
        environment = self.settings.database_environment()
        # An explicitly configured environment is authoritative, even when partial.
        # Never mix credentials from .env with stale settings saved in the form.
        if any(getattr(environment, f"sqlserver_{key}") for key in ("host", "user", "password", "database")):
            return environment
        values = self.secrets.load(source_id)
        if values is None:
            return self.settings
        return replace(self.settings, **{key.lower(): value for key, value in values.items()})

    def public_source(self, source):
        result = dict(source)
        saved = self.db.one("SELECT source_id FROM source_credentials WHERE source_id=?", (source["id"],))
        environment = self.settings.database_environment()
        using_environment = any(
            getattr(environment, f"sqlserver_{key}") for key in ("host", "user", "password", "database")
        )
        result["configuration_origin"] = "environment" if using_environment or not saved else "saved"
        result["error_scope"] = (
            "query" if source["status"] == "connected" and source.get("last_error") else "connection"
        )
        try:
            effective = self.source_settings(source["id"])
            result["connection_fields"] = {
                f"SQLSERVER_{key.upper()}": bool(getattr(effective, f"sqlserver_{key}"))
                for key in ("host", "port", "user", "password", "database")
            }
        except SecretsUnavailable:
            result["connection_fields"] = {}
        return result

    def status(self, source_id, status, error=None, checked=True):
        if self.db:
            self.db.execute(
                "UPDATE data_sources SET status=?,last_error=?,checked_at=? WHERE id=?",
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
            if source and source["kind"] == "sqlserver" and source["last_error"]:
                raise SourceNotConfigured(source["last_error"])
            raise SourceNotConfigured("No connector is implemented for this source type. Choose SQL Server.")
        try:
            await connector.check()
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "connected")
        except SourceNotConfigured as exc:
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "not_configured" if connector.missing() else "error", str(exc))

    async def fetch(self, dataset, parameters):
        connector = self.resolve_connector(dataset["source_id"])
        if not connector or not dataset["enabled"]:
            raise SourceNotConfigured(
                "This database is not connected yet. An administrator must configure its connector and enable the dataset."
            )
        Draft202012Validator(json.loads(dataset["parameters_schema_json"])).validate(parameters)
        try:
            rows = await connector.fetch(dataset["query_key"], parameters)
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
            WHERE s.id=? AND (u.role='admin' OR EXISTS(SELECT 1 FROM source_grants g WHERE g.source_id=s.id AND g.user_id=u.id))""",
            (user_id, source_id),
        )
        if not source or source["kind"] != "sqlserver":
            raise SourceNotConfigured("Database source is unavailable or access was not granted.")
        return source

    def accessible_sources(self, user_id):
        return self.db.all(
            """SELECT s.id,s.name,s.kind,s.status FROM data_sources s JOIN users u ON u.id=? AND u.active=1
            WHERE s.kind='sqlserver' AND (u.role='admin' OR EXISTS(SELECT 1 FROM source_grants g WHERE g.source_id=s.id AND g.user_id=u.id))
            ORDER BY s.created_at""",
            (user_id,),
        )

    async def database_call(self, user_id, source_id, operation, **arguments):
        self.authorized_source(user_id, source_id)
        connector = self.resolve_connector(source_id)
        if not isinstance(connector, SQLServerConnector):
            raise SourceNotConfigured(
                "This database connection is not configured. Ask the administrator to configure the source."
            )
        try:
            result = await getattr(connector, operation)(**arguments)
            self.authorized_source(user_id, source_id)
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "connected")
            return result
        except DatabaseUnavailable as exc:
            if self.connectors.get(source_id) is connector:
                self.status(source_id, "connected" if exc.category == "query" else "error", str(exc))
            raise
