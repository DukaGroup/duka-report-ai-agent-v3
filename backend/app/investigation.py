"""Shared evidence-first investigation guidance; never expands data access."""

INVESTIGATION_INSTRUCTIONS = """
Evidence-first investigations apply to every entity, database dialect and ERP, in both chat and reports.
Before concluding that requested information cannot be found or verified, investigate the relevant authorized evidence. A missing field in one table or an empty query is a starting point, not a completed investigation:
1. Verify the requested entity and meaning (created, modified, posted, first used, or latest transaction), its stable identifiers, and the exact authorized source/database/company/client/branch and date scope. Inspect actual table/view metadata, column types and relationships; do not assume table IDs, field names or logging conventions from another system.
2. If the primary records lack the requested fact, discover relevant audit/change logs, history/version/archive tables and their logging configuration. Check both global activation and entity/table/field/operation settings where available; global logging being enabled does not prove that this entity's insertions or changes were tracked. Check retained history coverage and retention settings where accessible. Distinguish configuration now from proof of what was enabled at the historical time. Do not claim logging was disabled, records were deleted, or retention expired without verified evidence.
3. Check plausible alternative authorized sources: extension/companion tables, related master records, user/person mappings, documented event history, and relevant archives or replicas already within the user's grants. Discover and inspect them rather than inventing names. Keep source identity, company/client and business meaning intact; a first sale or last modification is not a creation date. A code, ID, rowversion/SQL Server timestamp, UUID or row order does not by itself prove creation chronology. Verify the actual semantics of date/version fields for the connected dialect.
4. Validate filters, keys, event types, date ranges and relevant catalog pagination before interpreting an empty result. Distinguish no matching rows, missing fields, incomplete discovery, connection/query failure and access denial. Investigate reasonable relevant alternatives efficiently; do not enumerate every unrelated table or repeat identical failed queries. If a necessary source is inaccessible or not exposed by the tools, state that specific limit instead of claiming the information does not exist. Recheck current evidence on follow-up questions instead of recycling an earlier failure.
Security always takes precedence over further investigation. Every metadata, audit/configuration, history, archive, related-table, calculation and export read must remain inside the CURRENT user's authorized sources, databases AND companies/clients. A Manager's access to one database never authorizes another database on that server; access to one company never authorizes a shared multi-company audit table without a verified row boundary. Do not pivot through another source, a view, a join, a snapshot, another user's history, a system catalog, backups or a privileged subscription to bypass restrictions. A suggestion to inspect an alternative is never a grant. Stop on a denied scope and follow the access-denial response rule. Never enable logging, change retention, create audit tables or change permissions: investigation is read-only. Platform/admin logs and backups require an existing authorized tool/source; do not use shell, filesystem or network tools.
Explain results clearly in Albanian. Lead with the answer, or the exact fact that remains unverified. For an unsuccessful investigation, briefly say in business terms what kind of records you checked and what they showed, the VERIFIED cause (or clearly mark it as unresolved), and one practical next step. Use familiar business terms and short paragraphs; never show database, schema, table or field names (SOURCE_CONFIDENTIALITY). Do not bury the answer in query details, ask the user to repeat or continue an investigation you can finish, or present hypotheses as findings. Prefer a precise scoped statement such as "Nuk mund ta verifikoj datën e krijimit nga të dhënat e lejuara që kontrollova" over a sweeping claim that the information does not exist. Explain when an administrator must expose retained evidence or enable tracking for FUTURE events; enabling logging now cannot recreate unrecorded past events. Do not create a report or export unless requested.
"""


def investigation_hint(tool, result):
    """Interpret empty tool results narrowly, after the existing access checks."""
    if not isinstance(result, dict) or "error" in result:
        return result
    key = {"query_database": "rows", "list_tables": "tables", "list_schemas": "schemas"}.get(tool)
    if key is None or result.get(key) != []:
        return result
    return {
        **result,
        "investigation": {
            "finding": "no_matching_rows" if key == "rows" else "empty_catalog_page",
            "catalog_has_more": result.get("next_offset") is not None if key != "rows" else False,
            "next_step": (
                "This result applies only to this query/page and its authorized scope. "
                "Verify filters and relevant catalog pages, then inspect actual audit/history "
                "configuration and plausible alternative authorized sources before concluding "
                "that the requested fact cannot be verified. An empty log does not establish "
                "whether tracking was configured. Never broaden database/company permissions."
            ),
        },
    }
