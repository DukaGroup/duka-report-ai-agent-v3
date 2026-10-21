"""Server-owned database/company grants, shared by every provider and export."""

import asyncio
import hashlib
import json


def denied(message="Database or company access was not granted."):
    from .connectors import SourceNotConfigured

    raise SourceNotConfigured(message)


def company_unit(label, **scope):
    identity = {key: value for key, value in scope.items() if key != "chart"}
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]
    return {"id": key, "name": str(label), **scope}


async def discover_companies(connector):
    """Read ERP identity catalogs, never infer row access from a display name."""
    from .connectors import SourceNotConfigured

    hana = connector.dialect == "hana"
    sql = (
        "SELECT SCHEMA_NAME AS \"schema_name\",TABLE_NAME AS \"name\" FROM SYS.TABLES WHERE TABLE_NAME IN ('T001','OADM')"
        if hana
        else "SELECT TABLE_SCHEMA AS schema_name,TABLE_NAME AS name FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' AND TABLE_NAME IN ('Company','T001','OADM')"
    )
    candidates = await asyncio.to_thread(connector._run_full, sql, {})
    units, errors = [], []
    for table in candidates:
        schema, name = table["schema_name"], table["name"]
        try:
            fields = {c["name"] for c in (await connector.describe(schema, name))["columns"]}
            if name == "T001" and {"MANDT", "BUKRS", "BUTXT"} <= fields:
                rows = await connector.report_query(
                    {
                        "tables": [{"schema": schema, "name": name, "alias": "c"}],
                        "select": [
                            {"column": "c." + field}
                            for field in ["MANDT", "BUKRS", "BUTXT"] + (["KTOPL"] if "KTOPL" in fields else [])
                        ],
                    }
                )
                for row in rows["rows"]:
                    units.append(
                        company_unit(
                            f"{row['BUTXT']} · {row['BUKRS']} · SAP {row['MANDT']}",
                            kind="sap_fi",
                            schema=schema,
                            client=str(row["MANDT"]),
                            company=str(row["BUKRS"]),
                            chart=str(row.get("KTOPL") or ""),
                        )
                    )
            elif name == "OADM" and "CompnyName" in fields:
                rows = await connector.report_query(
                    {"tables": [{"schema": schema, "name": name, "alias": "c"}], "select": [{"column": "c.CompnyName"}]}
                )
                if len(rows["rows"]) != 1:
                    raise ValueError("Ambiguous company identity")
                units.append(company_unit(rows["rows"][0]["CompnyName"] or schema, kind="schema", schema=schema))
            elif name == "Company" and "Name" in fields:
                rows = await connector.report_query(
                    {"tables": [{"schema": schema, "name": name, "alias": "c"}], "select": [{"column": "c.Name"}]}
                )
                for row in rows["rows"]:
                    if isinstance(row["Name"], str) and row["Name"]:
                        units.append(
                            company_unit(row["Name"], kind="table_prefix", schema=schema, prefix=row["Name"] + "$")
                        )
        except (ValueError, SourceNotConfigured):
            errors.append(f"Company identities could not be verified in schema {schema}.")
    ambiguous = {
        u["schema"]
        for u in units
        if u["kind"] == "schema"
        and any(other["schema"] == u["schema"] and other["kind"] != "schema" for other in units)
    }
    if ambiguous:
        errors.extend(
            "Mixed company identity schemes require a narrower reporting source in schema " + schema + "."
            for schema in sorted(ambiguous)
        )
    unique = {u["id"]: u for u in units if not (u["kind"] == "schema" and u["schema"] in ambiguous)}
    return {
        "companies": sorted(unique.values(), key=lambda u: (u["name"], u["id"])),
        "complete": not errors,
        "warnings": errors,
        "note": ""
        if units
        else "No supported company identity catalog was found; database access covers the complete database.",
    }


class DataAccess:
    def __init__(self, db):
        self.db = db

    def full(self, user):
        row = self.db.one("SELECT role FROM users WHERE id=? AND active=1", (user,))
        return bool(row and row["role"] in ("devs", "president"))

    def scoped(self, user, source):
        return not self.full(user) and bool(
            self.db.one("SELECT 1 FROM source_access_policies WHERE user_id=? AND source_id=?", (user, source))
        )

    def rule(self, user, source, database):
        if not self.scoped(user, source):
            return None
        row = self.db.one(
            "SELECT * FROM database_grants WHERE user_id=? AND source_id=? AND database_name=?",
            (user, source, database),
        )
        if not row:
            denied()
        return None if row["all_companies"] else json.loads(row["companies_json"])

    def stamp(self, user, source, database):
        role = self.db.one("SELECT role,active FROM users WHERE id=?", (user,))
        if not self.db.one("SELECT 1 FROM data_sources WHERE id=? AND enabled=1", (source,)):
            denied()
        grant = self.db.one("SELECT 1 FROM source_grants WHERE user_id=? AND source_id=?", (user, source))
        if not role or not role["active"] or (not self.full(user) and not grant):
            denied()
        rule = (
            self.db.all(
                "SELECT database_name,all_companies,companies_json FROM database_grants WHERE user_id=? AND source_id=? ORDER BY database_name",
                (user, source),
            )
            if database is None and self.scoped(user, source)
            else self.rule(user, source, database)
        )
        version = self.db.one("SELECT revision FROM data_access_versions WHERE user_id=?", (user,))
        return hashlib.sha256(
            json.dumps([source, database, rule, version["revision"] if version else 0], sort_keys=True).encode()
        ).hexdigest()

    def saved(self, user):
        rows = self.db.all(
            "SELECT d.* FROM database_grants d JOIN source_grants g ON g.user_id=d.user_id AND g.source_id=d.source_id WHERE d.user_id=? ORDER BY d.source_id,d.database_name",
            (user,),
        )
        legacy = self.db.all(
            "SELECT g.source_id FROM source_grants g WHERE g.user_id=? AND NOT EXISTS(SELECT 1 FROM source_access_policies p WHERE p.user_id=g.user_id AND p.source_id=g.source_id)",
            (user,),
        )
        return {
            "databases": [
                {
                    "source_id": r["source_id"],
                    "database": r["database_name"],
                    "all_companies": bool(r["all_companies"]),
                    "company_ids": [u["id"] for u in json.loads(r["companies_json"])],
                }
                for r in rows
            ],
            "legacy_source_ids": [r["source_id"] for r in legacy],
            "all_access": self.full(user),
        }

    def replace(self, c, user, selections, legacy=()):
        # Used inside user creation/update transactions after live catalog validation.
        c.execute("DELETE FROM source_grants WHERE user_id=?", (user,))
        c.execute("DELETE FROM source_access_policies WHERE user_id=?", (user,))
        c.execute("DELETE FROM database_grants WHERE user_id=?", (user,))
        for source in sorted({s["source_id"] for s in selections} | set(legacy)):
            c.execute("INSERT INTO source_grants VALUES(?,?)", (source, user))
            if source not in legacy:
                c.execute("INSERT INTO source_access_policies VALUES(?,?)", (user, source))
        self.bump(c, user)
        for item in selections:
            c.execute(
                "INSERT INTO database_grants VALUES(?,?,?,?,?)",
                (
                    user,
                    item["source_id"],
                    item["database"],
                    int(item["all_companies"]),
                    json.dumps(item["companies"], ensure_ascii=False),
                ),
            )

    @staticmethod
    def bump(c, user):
        c.execute(
            "INSERT INTO data_access_versions(user_id,revision) SELECT id,1 FROM users WHERE id=? ON CONFLICT(user_id) DO UPDATE SET revision=revision+1",
            (user,),
        )


def metadata_allowed(units, schema, table=None):
    return any(
        u["schema"] == schema and (table is None or u["kind"] != "table_prefix" or table.startswith(u["prefix"]))
        for u in units
    )


async def verified_base_table(connector, schema, table):
    rows = await connector.tables(schema=schema, name_contains=table, kind="table", limit=200)
    if not any(t["schema_name"] == schema and t["name"] == table and t["kind"] == "BASE TABLE" for t in rows["tables"]):
        denied(
            "This object has no verified database/company access boundary. Use base tables or a reporting source approved by Devs."
        )
    return await connector.describe(schema, table)


async def table_scope(connector, units, schema, table):
    matching = None if units is None else [u for u in units if metadata_allowed([u], schema, table)]
    if matching == []:
        denied()
    description = await verified_base_table(connector, schema, table)
    if units is None:
        return None
    if any(u["kind"] == "schema" for u in matching):
        return None
    prefixes = [u for u in matching if u["kind"] == "table_prefix"]
    if prefixes:
        # A company name may itself contain '$'. Match the most specific live
        # physical prefix so Alpha cannot read Alpha$Subsidiary's tables.
        identities = await connector.report_query(
            {"tables": [{"schema": schema, "name": "Company", "alias": "c"}], "select": [{"column": "c.Name"}]}
        )
        candidates = [
            r["Name"] + "$"
            for r in identities["rows"]
            if isinstance(r["Name"], str) and table.startswith(r["Name"] + "$")
        ]
        if not candidates or max(candidates, key=len) not in {u["prefix"] for u in prefixes}:
            denied()
        return None
    fields = {c["name"] for c in description["columns"]}
    client = "MANDT" if "MANDT" in fields else "RCLNT" if "RCLNT" in fields else None
    company = "BUKRS" if "BUKRS" in fields else "RBUKRS" if "RBUKRS" in fields else None
    if client and company:
        return [{client: u["client"], company: u["company"]} for u in matching]
    if client and table == "T000":
        return [{client: u["client"]} for u in matching]
    if client and "KTOPL" in fields and table in ("SKA1", "SKAT", "T004", "T004T"):
        identities = await connector.report_query(
            {
                "tables": [{"schema": schema, "name": "T001", "alias": "c"}],
                "select": [{"column": "c." + column} for column in ("MANDT", "BUKRS", "KTOPL")],
            }
        )
        charts = {(str(row["MANDT"]), str(row["BUKRS"])): row["KTOPL"] for row in identities["rows"]}
        scopes = [
            {client: u["client"], "KTOPL": charts[(u["client"], u["company"])]}
            for u in matching
            if charts.get((u["client"], u["company"]))
        ]
        if not scopes:
            denied("Company chart access could not be verified.")
        return scopes
    if table in ("TCURC", "TCURT", "T005", "T005T", "T006", "T006A"):
        return [{client: u["client"]} for u in matching] if client else None
    denied(
        "This table has no verified company row boundary. Ask Devs to provide a company-scoped reporting source or grant complete database access."
    )


async def restricted_call(connector, operation, arguments, units):
    """Enforce a company boundary before data reaches a model or calculation."""
    if operation in ("query", "report_query"):
        from .database_tools import DatabaseQuery

        plan = DatabaseQuery.model_validate(arguments["query"])
        scopes = {}
        for table in plan.tables:
            scope = await table_scope(connector, units, table.schema_name, table.name)
            if scope is not None:
                scopes[table.alias] = scope
        return await getattr(connector, operation)(plan.model_dump(by_alias=True), row_scopes=scopes)
    if operation == "describe":
        schema, table = arguments["schema"], arguments["table"]
        await table_scope(connector, units, schema, table)
        result = await connector.describe(schema, table)
        result["relationships"] = [
            r
            for r in result.get("relationships", [])
            if units is None or metadata_allowed(units, r["referenced_schema"], r["referenced_table"])
        ]
        return result
    if operation in ("tables", "schemas"):
        result = await getattr(connector, operation)(**arguments)
        if operation == "tables":
            result["tables"] = [
                r
                for r in result["tables"]
                if r["kind"] == "BASE TABLE" and (units is None or metadata_allowed(units, r["schema_name"], r["name"]))
            ]
        else:
            result["schemas"] = [
                {**r, "table_count": None, "view_count": None}
                for r in result["schemas"]
                if units is None or metadata_allowed(units, r["schema_name"])
            ]
        return result
    if operation == "sap_context":
        if units is not None and not metadata_allowed(units, arguments["schema"]):
            denied()
        result = await connector.sap_context(**arguments)
        if units is None:
            return result
        allowed = {
            (u["client"], u["company"]) for u in units if u["kind"] == "sap_fi" and u["schema"] == arguments["schema"]
        }
        result["companies"] = [r for r in result["companies"] if (r["client"], r["company"]) in allowed]
        result["company_count"] = len(result["companies"])
        return result
    if operation == "sales_catalog":
        result = await connector.sales_catalog(**arguments)
        if units is None:
            return result
        result["companies"] = [
            r
            for r in result["companies"]
            if any(
                (u["kind"] == "schema" and u["schema"] == r["company"])
                or (u["kind"] == "table_prefix" and u["prefix"] == r["company"] + "$")
                for u in units
            )
        ]
        result["unavailable_tables"] = []
        result["recommended_company"] = result["companies"][0]["company"] if len(result["companies"]) == 1 else None
        result["multiple_companies"] = len(result["companies"]) > 1
        return result
    denied("This operation has no verified company access boundary.")


def capture_checks(provenance):
    """Small permission receipts, retained after large report rows are released."""
    checks = []
    for item in [provenance, *provenance.get("analyses", [])]:
        if item.get("source_id"):
            checks.append((item["source_id"], item.get("database"), item.get("access_stamp")))
    audit = provenance.get("_internal", {}).get("calculation_audit", {}).get("provenance", {})
    captures = {item["name"]: item for item in audit.get("inputs", [])}
    for item in audit.get("plan", {}).get("inputs", []):
        if item["kind"] == "database":
            captured = captures.get(item["name"], {})
            checks.append(
                (item["source_id"], captured.get("database", item.get("database")), captured.get("access_stamp"))
            )
    return checks


def validate_capture(db, user, checks):
    access = DataAccess(db)
    for source, database, stamp in checks:
        current = access.stamp(user, source, database)
        if (stamp is not None or access.scoped(user, source)) and stamp != current:
            denied(
                "Database/company access changed during report preparation. Recreate the report with the current grants."
            )
