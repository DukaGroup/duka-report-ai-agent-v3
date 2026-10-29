"""SAP's hdbcli protocol, HANA catalogs and validated read-only query plans."""

import asyncio
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from .connectors import SQLServerConnector, SourceNotConfigured, DatabaseUnavailable
from .hana_tls import trust_store


def hana_error(exc):
    code = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    text = str(exc).lower()
    if code == 10 or "authentication failed" in text:
        return "SAP HANA authentication failed. Check HANA_USER, HANA_PASSWORD and the tenant SQL port."
    if code == 258 or "insufficient privilege" in text:
        return "SAP HANA denied access. Check SELECT and catalog metadata permissions for the reporting user."
    if code in (259, 260):
        return "The SAP HANA table, view or column is unavailable. Refresh the schema and check object permissions."
    from .database_tls import connection_error
    tls_error = connection_error(text, "SAP HANA")
    if tls_error:
        return tls_error
    if "timeout" in text or "timed out" in text:
        return "SAP HANA timed out. Check the host, SQL port, network and query performance."
    if code in (-10709, -10719) or "connect" in text:
        return "SAP HANA could not establish a connection. Check HANA_HOST and the HANA SQL port; SQL Server ports and protocols are incompatible."
    return "SAP HANA could not complete the request. Check the tenant, SQL port, permissions and query."


class HanaCursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, parameters):
        self.cursor.execute(sql, tuple(parameters.values()) if isinstance(parameters, dict) else parameters)

    def fetchmany(self, size):
        names = [column[0] for column in self.cursor.description]
        return [dict(zip(names, row)) for row in self.cursor.fetchmany(size)]


class HanaConnection:
    def __init__(self, connection):
        self.connection = connection

    def cursor(self):
        return HanaCursor(self.connection.cursor())

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


class HanaConnector(SQLServerConnector):
    dialect = "hana"
    error_message = staticmethod(hana_error)

    def missing(self):
        return ["HANA_" + key.upper() for key in ("host", "port", "user", "password") if not getattr(self.settings, "hana_" + key)]

    def _connect(self):
        from .database_tls import options as tls_options
        try:
            tls = tls_options(self.settings, "saphana")
        except ValueError as exc:
            raise SourceNotConfigured(str(exc)) from None
        if self.missing():
            raise SourceNotConfigured("Missing connection settings: " + ", ".join(self.missing()))
        try:
            port = int(self.settings.hana_port)
            if not 1 <= port <= 65535:
                raise ValueError()
        except ValueError:
            raise SourceNotConfigured("HANA_PORT must be a number between 1 and 65535.") from None
        driver = self.driver
        if driver is None:
            try:
                from hdbcli import dbapi
            except ImportError:
                raise SourceNotConfigured("SAP HANA driver is unavailable. Rebuild the application with hdbcli installed.") from None
            driver = dbapi
        options = {"address": self.settings.hana_host, "port": port, "user": self.settings.hana_user,
                   "password": self.settings.hana_password, "autocommit": False,
                   "encrypt": tls["encrypt"], "sslValidateCertificate": tls["validate_certificate"],
                   "connectTimeout": self.settings.sqlserver_timeout * 1000,
                   "communicationTimeout": max(self.settings.database_query_timeout, self.settings.sqlserver_timeout) * 1000}
        if tls["encrypt"]:
            options["sslCryptoProvider"] = "openssl"
            if tls["validate_certificate"]:
                try:
                    options["sslTrustStore"] = trust_store(self.settings)
                except (OSError, ValueError):
                    raise SourceNotConfigured("The SAP HANA CA bundle is invalid or unavailable. Check HANA_TLS_CA_CERTIFICATE and backend storage permissions.") from None
            if self.settings.hana_tls_server_name:
                options["sslHostNameInCertificate"] = self.settings.hana_tls_server_name
        # HANA Cloud connects directly to its tenant and rejects databaseName.
        if self.settings.hana_database and port != 443:
            options["databaseName"] = self.settings.hana_database
        return HanaConnection(driver.connect(**options))

    async def check(self):
        rows = await asyncio.to_thread(self._run, 'SELECT DATABASE_NAME AS "name" FROM SYS.M_DATABASE', {})
        if self.settings.hana_database and (not rows or rows[0]["name"] != self.settings.hana_database):
            raise SourceNotConfigured("The SAP HANA SQL endpoint did not select the requested tenant. Use the correct tenant SQL port or SYSTEMDB routing endpoint.")

    async def _catalog(self):
        current = await asyncio.to_thread(self._run, 'SELECT DATABASE_NAME AS "name" FROM SYS.M_DATABASE', {})
        if not current:
            raise SourceNotConfigured("SAP HANA did not return the connected database name.")
        name = current[0]["name"]
        warnings = []
        try:
            tenants = await asyncio.to_thread(self._run, 'SELECT DATABASE_NAME AS "name" FROM SYS_DATABASES.M_DATABASES WHERE DATABASE_NAME<>? ORDER BY DATABASE_NAME', {"system": "SYSTEMDB"})
        except DatabaseUnavailable as exc:
            if exc.category == "connection":
                raise
            tenants = []
            warnings.append("The tenant catalog is unavailable to this login/endpoint. Discovery covers the connected tenant and all its accessible company schemas; use a SYSTEMDB SQL endpoint and suitable login to inspect other tenants.")
        names = {row["name"] for row in tenants}
        if name != "SYSTEMDB":
            names.add(name)
        return name, sorted(names), warnings

    def _selected(self, database):
        connector = HanaConnector(replace(self.settings, hana_database=database), self.catalog, self.driver)
        connector.traffic = getattr(self, "traffic", None)
        return connector

    async def databases(self, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid database catalog page. Use offset >= 0 and limit 1–200.")
        current, names, warnings = await self._catalog()
        readable, unavailable = [], []
        for name in names:
            if name == current:
                readable.append(name)
                continue
            try:
                rows = await asyncio.to_thread(self._selected(name)._run, 'SELECT DATABASE_NAME AS "name" FROM SYS.M_DATABASE', {})
                if rows and rows[0]["name"] == name:
                    readable.append(name)
                else:
                    unavailable.append(name)
            except SourceNotConfigured:
                unavailable.append(name)
        return {"databases": [{"name": name, "is_default": int(name == current)} for name in readable[offset:offset+limit]],
                "next_offset": offset+limit if len(readable) > offset+limit else None, "warnings": warnings,
                "unavailable_databases": unavailable, "connected_database": current,
                "catalog_complete": not warnings and not unavailable}

    async def in_database(self, database):
        if not isinstance(database, str) or not 1 <= len(database) <= 128 or "\x00" in database:
            raise ValueError("Choose a database name returned by discover_databases.")
        cached = self._cached_database(database)
        if cached is not None:
            return cached
        current, names, _ = await self._catalog()
        if database == "SYSTEMDB" or database not in names:
            raise SourceNotConfigured("Database is unavailable or the reporting login cannot access it.")
        selected = self if database == current else self._selected(database)
        actual = await asyncio.to_thread(selected._run, 'SELECT DATABASE_NAME AS "name" FROM SYS.M_DATABASE', {})
        if not actual or actual[0]["name"] != database:
            raise SourceNotConfigured("The SAP HANA SQL endpoint did not select the requested tenant. Use the correct tenant SQL port or SYSTEMDB routing endpoint.")
        # Keep the actual tenant as provenance even when the port chose it implicitly.
        selected = self._selected(database)
        if database == current:
            # Avoid databaseName when using a direct tenant/Cloud endpoint.
            selected._connect = self._connect
        return self._remember_database(database, selected)

    async def schemas(self, offset=0, limit=100):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Invalid catalog page. Use a nonnegative offset and limit 1–200.")
        rows = await asyncio.to_thread(self._run, '''SELECT "schema_name",SUM("is_table") AS "table_count",SUM("is_view") AS "view_count" FROM (
            SELECT SCHEMA_NAME AS "schema_name",1 AS "is_table",0 AS "is_view" FROM SYS.TABLES
            UNION ALL SELECT SCHEMA_NAME,0,1 FROM SYS.VIEWS
        ) WHERE "schema_name" NOT IN ('SYS','SYSTEM','PUBLIC','SYS_DATABASES') AND LEFT("schema_name",5)<>'_SYS_'
        GROUP BY "schema_name" ORDER BY "schema_name" LIMIT ? OFFSET ?''', {"size":limit+1,"offset":offset})
        return {"schemas":rows[:limit], "next_offset":offset+limit if len(rows)>limit else None}

    async def tables(self, offset=0, limit=100, kind="all", name_contains="", schema=None):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200 or kind not in ("all", "table", "view") or not isinstance(name_contains, str) or len(name_contains)>128:
            raise ValueError("Invalid table catalog page or filter.")
        if schema is not None and (not isinstance(schema, str) or not 1 <= len(schema) <= 128):
            raise ValueError("Choose a schema name returned by list_schemas.")
        # SYS metadata is privilege-filtered. Business reads still use the login's SELECT grants.
        sql = '''SELECT "schema_name","name","kind" FROM (
            SELECT SCHEMA_NAME AS "schema_name",TABLE_NAME AS "name",'BASE TABLE' AS "kind" FROM SYS.TABLES
            UNION ALL SELECT SCHEMA_NAME,VIEW_NAME,'VIEW' FROM SYS.VIEWS
        ) WHERE "schema_name" NOT IN ('SYS','SYSTEM','PUBLIC','SYS_DATABASES')
        AND LEFT("schema_name",5)<>'_SYS_' '''
        params = {}
        if kind != "all":
            sql += ' AND "kind"=?'
            params["kind"] = "BASE TABLE" if kind == "table" else "VIEW"
        if name_contains:
            sql += ' AND LOCATE("name",?)>0'
            params["name"] = name_contains
        if schema is not None:
            sql += ' AND "schema_name"=?'
            params["schema"] = schema
        sql += ' ORDER BY "schema_name","name" LIMIT ? OFFSET ?'
        params.update(size=limit+1, offset=offset)
        rows = await asyncio.to_thread(self._run, sql, params)
        return {"tables": rows[:limit], "next_offset": offset+limit if len(rows)>limit else None}

    async def describe(self, schema, table):
        if not isinstance(schema, str) or not isinstance(table, str) or not 1 <= len(schema) <= 128 or not 1 <= len(table) <= 128:
            raise ValueError("Use schema and table names from list_tables.")
        params = {"schema": schema, "table": table}
        rows = await asyncio.to_thread(self._run, '''SELECT COLUMN_NAME AS "name",DATA_TYPE_NAME AS "type",IS_NULLABLE AS "nullable",LENGTH AS "precision",SCALE AS "scale" FROM SYS.TABLE_COLUMNS WHERE SCHEMA_NAME=? AND TABLE_NAME=? ORDER BY POSITION''', params)
        if not rows:
            rows = await asyncio.to_thread(self._run, '''SELECT COLUMN_NAME AS "name",DATA_TYPE_NAME AS "type",IS_NULLABLE AS "nullable",LENGTH AS "precision",SCALE AS "scale" FROM SYS.VIEW_COLUMNS WHERE SCHEMA_NAME=? AND VIEW_NAME=? ORDER BY POSITION''', params)
        if not rows:
            raise ValueError("Table not found or the reporting login cannot inspect it.")
        for column in rows:
            kind = column["type"].lower()
            column["type"] = {"integer": "int", "double": "float", "smalldecimal": "decimal", "timestamp": "datetime2", "seconddate": "datetime", "alphanum": "nvarchar", "shorttext": "nvarchar"}.get(kind, kind)
        keys = await asyncio.to_thread(self._run, '''SELECT COLUMN_NAME AS "column_name",REFERENCED_SCHEMA_NAME AS "referenced_schema",REFERENCED_TABLE_NAME AS "referenced_table",REFERENCED_COLUMN_NAME AS "referenced_column",CONSTRAINT_NAME AS "relationship" FROM SYS.REFERENTIAL_CONSTRAINTS WHERE SCHEMA_NAME=? AND TABLE_NAME=? ORDER BY CONSTRAINT_NAME,POSITION''', params)
        return {"schema": schema, "table": table, "columns": rows, "relationships": keys}

    async def fetch(self, query_key, parameters):
        raise SourceNotConfigured("Legacy SQL Server query scripts do not run on SAP HANA. Use discovered HANA tables and structured queries.")

    async def fetch_report(self, query_key, parameters):
        return await self.fetch(query_key, parameters)

    async def sales_catalog(self, company=None):
        if company is not None and (not isinstance(company, str) or not 1 <= len(company) <= 128):
            raise ValueError("Choose a company schema returned by list_schemas.")
        companies, offset = {}, 0
        while True:
            # Filter inside HANA. Paging every SAP table can take hundreds of
            # round trips even when this tenant is not SAP Business One at all.
            sql = '''SELECT SCHEMA_NAME AS "schema_name",TABLE_NAME AS "name" FROM SYS.TABLES
                WHERE TABLE_NAME IN (?,?,?,?) AND SCHEMA_NAME NOT IN ('SYS','SYSTEM','PUBLIC','SYS_DATABASES')
                AND LEFT(SCHEMA_NAME,5)<>'_SYS_' '''
            params = {"invoice":"OINV","invoice_line":"INV1","credit":"ORIN","credit_line":"RIN1"}
            if company is not None:
                sql += ' AND SCHEMA_NAME=?'
                params["company"] = company
            sql += ' ORDER BY SCHEMA_NAME,TABLE_NAME LIMIT ? OFFSET ?'
            params.update(size=201,offset=offset)
            rows = await asyncio.to_thread(self._run, sql, params)
            for table in rows[:200]:
                description = await self.describe(table["schema_name"], table["name"])
                role = {"OINV":"invoice_header", "INV1":"invoice_line", "ORIN":"credit_header", "RIN1":"credit_line"}[table["name"]]
                companies.setdefault(table["schema_name"], {})[role] = {"schema":table["schema_name"], "name":table["name"], "columns":description["columns"]}
            if len(rows) <= 200:
                break
            offset += 200
        return {"vendor":"saphana", "companies":[{"company":name,"tables":tables} for name,tables in companies.items()],
                "business_date":datetime.now(ZoneInfo("Europe/Tirane")).date().isoformat(),"timezone":"Europe/Tirane","base_currency":"ALL",
                "guidance":"This discovery checks SAP Business One OINV/INV1/ORIN/RIN1 names across all accessible company schemas, not all SAP application structures. An empty companies result does not mean the database has no sales data. Use list_schemas for a fast schema/count overview, then list_tables with schema and name_contains to find the relevant tables for other SAP deployments. Do not enumerate the whole catalog just to check connectivity. Inspect actual columns, cancellation flags, amounts, document currencies, local/foreign currency fields and join cardinality before querying invoices/credits. Do not sum headers after joining multiple lines."}
