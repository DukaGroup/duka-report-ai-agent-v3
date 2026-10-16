"""Read SAP client/company identity evidence without selecting a business scope."""

import asyncio

from .connectors import SourceNotConfigured


async def inspect_context(connector, schema):
    if connector.dialect != "hana":
        raise SourceNotConfigured("SAP FI context inspection requires a SAP HANA source.")
    if not isinstance(schema, str) or not 1 <= len(schema) <= 128 or "\x00" in schema:
        raise ValueError("Choose a schema returned by list_schemas.")
    quoted = '"' + schema.replace('"', '""') + '"'
    company_fields = {c["name"] for c in (await connector.describe(schema, "T001"))["columns"]}
    required = {"MANDT", "BUKRS", "BUTXT", "WAERS"}
    if not required <= company_fields:
        raise SourceNotConfigured("SAP company identity and local-currency metadata are unavailable.")
    columns = ["MANDT", "BUKRS", "BUTXT", "WAERS"]
    if "KTOPL" in company_fields:
        columns.append("KTOPL")
    companies = await asyncio.to_thread(
        connector._run_full,
        "SELECT " + ",".join('"' + c + '"' for c in columns) + f' FROM {quoted}."T001"',
        [],
    )
    # Client purpose is separate evidence: the same company can exist in both
    # production and test clients. Never infer purpose from a client number.
    clients, warnings = [], []
    try:
        fields = {c["name"] for c in (await connector.describe(schema, "T000"))["columns"]}
        if not {"MANDT", "MTEXT"} <= fields:
            raise ValueError("Missing client identity metadata")
        columns = ["MANDT", "MTEXT"] + (["CCCATEGORY"] if "CCCATEGORY" in fields else [])
        clients = await asyncio.to_thread(
            connector._run_full,
            "SELECT " + ",".join('"' + c + '"' for c in columns) + f' FROM {quoted}."T000"',
            [],
        )
        if "CCCATEGORY" not in fields:
            warnings.append("T000 client-role category is unavailable; client descriptions alone may be insufficient.")
    except (ValueError, SourceNotConfigured):
        warnings.append("T000 client-purpose metadata could not be read. Production scope is unverified; inspect other evidence before selecting clients.")
    client_index = {}
    for row in clients:
        key = str(row["MANDT"])
        if key in client_index:
            raise SourceNotConfigured("Duplicate SAP client metadata; identity cannot be verified.")
        client_index[key] = row
    seen, results = set(), []
    for row in companies:
        key = (str(row["MANDT"]), str(row["BUKRS"]))
        if key in seen:
            raise SourceNotConfigured("Duplicate SAP company metadata; identity cannot be verified.")
        seen.add(key)
        client = client_index.get(key[0], {})
        results.append({
            "client": key[0], "company": key[1], "company_name": row["BUTXT"],
            "local_currency": row["WAERS"], "chart_of_accounts": row.get("KTOPL"),
            "client_name": client.get("MTEXT"), "client_category": client.get("CCCATEGORY"),
            "client_metadata_available": bool(client),
        })
        if not client:
            warnings.append("A company has no readable T000 client record; its client purpose is unverified.")
    return {
        "schema": schema, "companies": results, "company_count": len(results),
        "truncated": False, "warnings": list(dict.fromkeys(warnings)),
        "scope": "Identity evidence from T001 and T000, not accounting balances or a certified production-environment selection.",
        "selection_guidance": (
            "Inspect company names, client descriptions and role categories together. "
            "A company appearing in several clients is not evidence of separate real-world businesses. "
            "Use verified production scope for ordinary business requests. Include test, training, demo or copied "
            "contexts only when explicitly requested. Preserve an explicit client choice and label its purpose. "
            "If evidence conflicts or multiple production contexts overlap, investigate rather than combining them."
        ),
    }
