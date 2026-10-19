"""Resolve a user-supplied company without exposing the restricted catalog.

Only this server-side lookup crosses member grant boundaries, and only for ERP
identity catalogs. Business queries continue through the ordinary access layer.
"""

import asyncio
import re
import unicodedata

from .connectors import SQLServerConnector, SourceNotConfigured
from .data_access import DataAccess, discover_companies
from .source_secrets import SecretsUnavailable


def name_words(value):
    text = unicodedata.normalize("NFKD", value.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    words = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    # ERP names commonly spell initials as D&D, D & D, or DD.
    return re.sub(r"\b(\w)\s+(?=\w\b)", r"\1", " ".join(words))


def match_score(query, label):
    candidate = name_words(label)
    if candidate == query:
        return 2
    if len(query) >= 2 and candidate.startswith(query + " "):
        return 1
    return 0


async def resolve_company_access(registry, user_id, company):
    """Return decisions and authorized matches only; never restricted identities."""
    if not isinstance(company, str) or not 2 <= len(company.strip()) <= 160:
        raise ValueError("Provide a company name between 2 and 160 characters.")
    query = name_words(company)
    if len(query) < 2:
        raise ValueError("Provide a specific company name.")
    db = registry.db

    def member_state():
        return db.one(
            "SELECT u.role,u.active,COALESCE(v.revision,0) AS revision FROM users u "
            "LEFT JOIN data_access_versions v ON v.user_id=u.id WHERE u.id=?", (user_id,)
        )

    initial = member_state()
    if not initial or not initial["active"]:
        raise SourceNotConfigured("Member access is unavailable.")
    sources = db.all(
        "SELECT id,name,kind FROM data_sources WHERE enabled=1 AND kind IN ('sqlserver','saphana')"
    )
    semaphore = asyncio.Semaphore(4)
    failures = (SourceNotConfigured, SecretsUnavailable, ValueError)

    async def inspect_database(source, connector, database):
        async with semaphore:
            try:
                active = await connector.in_database(database)
                catalog = await discover_companies(active)
                return source, database, catalog["companies"], catalog["complete"]
            except failures:
                # Never pass connection errors, schema names or credentials to the model.
                return source, database, [], False

    async def inspect_source(source):
        try:
            connector = registry.resolve_connector(source["id"])
            if not isinstance(connector, SQLServerConnector):
                return [], False
            databases, offset, complete = [], 0, True
            while True:
                async with semaphore:
                    page = await connector.databases(offset=offset, limit=200)
                databases.extend(d["name"] for d in page["databases"])
                complete = complete and page.get("catalog_complete", True) and not page.get("warnings")
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            results = await asyncio.gather(
                *(inspect_database(source, connector, name) for name in dict.fromkeys(databases))
            )
            return results, bool(complete and all(r[3] for r in results))
        except failures:
            return [], False

    inventory = await asyncio.gather(*(inspect_source(source) for source in sources))
    if initial != member_state() or sources != db.all(
        "SELECT id,name,kind FROM data_sources WHERE enabled=1 AND kind IN ('sqlserver','saphana')"
    ):
        raise SourceNotConfigured("Database/company access changed. Retry the access check.")

    access = DataAccess(db)
    companies, locations, company_identities = [], [], []
    for entries, _ in inventory:
        for source, database, units, _ in entries:
            try:
                access.stamp(user_id, source["id"], database)
                rule = access.rule(user_id, source["id"], database)
                allowed = None if rule is None else {unit["id"] for unit in rule}
                database_allowed = True
            except SourceNotConfigured:
                allowed, database_allowed = set(), False
            location = {"source_id": source["id"], "database": database}
            score = max(match_score(query, database), match_score(query, source["name"]))
            if score:
                locations.append((score, database_allowed, location))
            for unit in units:
                identity = (database_allowed and (allowed is None or unit["id"] in allowed),
                            {**location, "company": unit})
                company_identities.append(identity)
                score = match_score(query, unit["name"].split(" · ")[0])
                if score:
                    companies.append((score, *identity))

    candidates = companies or locations
    qualifier = None
    if not candidates:
        # A branch/city can follow a short company name: "Gotech Fier" is
        # not itself an ERP company ("Gotech Live"). Consider this only AFTER
        # checking the full name across the private inventory, so an explicit
        # restricted company cannot be replaced by an accessible parent alias.
        words = query.split()
        for length in range(len(words) - 1, 0, -1):
            prefix = " ".join(words[:length])
            if len(prefix) < 2:
                continue
            candidates = [
                (1, permitted, match) for permitted, match in company_identities
                if match_score(prefix, match["company"]["name"].split(" · ")[0])
            ]
            if candidates:
                qualifier = {"company_name": prefix, "remaining_text": " ".join(words[length:])}
                break
    authorized = [item[2] for item in candidates if item[1]]
    restricted = any(not item[1] for item in candidates)
    complete = all(item[1] for item in inventory)
    if restricted and not authorized:
        return {"status": "denied", "message": "Qasja nuk lejohet.", "matches": []}
    if restricted:
        # An alias shared by an allowed and a restricted company is not authority
        # to silently substitute the allowed company for the user's intended one.
        status = "ambiguous"
    elif authorized and qualifier:
        # This verifies only the candidate company grant. The model must verify
        # the remaining scope in that company's authorized business metadata.
        status = "scope_required"
    elif authorized:
        status = "allowed"
    else:
        status = "not_found" if complete else "unavailable"
    return {"status": status, "matches": authorized, "catalog_complete": complete,
            **({"requested_name": company.strip(), "qualifier": qualifier} if qualifier else {})}
