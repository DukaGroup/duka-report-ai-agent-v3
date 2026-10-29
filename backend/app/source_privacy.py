"""Keep data-source identifiers out of user-facing answers.

The model is instructed to answer in business terms. This is the backstop:
connection, database, schema and table names that a conversation touched are
replaced before the text is saved or streamed to the browser.
"""

import json
import re

PLACEHOLDER = "[burim i brendshëm]"
# Words that are also ordinary text (the assistant is called Hana) are never
# treated as private identifiers, even when a source or schema uses them.
GENERIC = {
    "hana", "sap", "sql", "sqlserver", "sql server", "server", "database", "data", "live", "test", "demo",
    "main", "default", "public", "sales", "company", "companies", "customer", "item", "items", "all",
}
MAX_TERM = 160
TERM_KEYS = ("source_id", "database", "schema", "table")


def usable(term):
    if not isinstance(term, str):
        return False
    term = term.strip()
    return 3 <= len(term) <= MAX_TERM and not term.isdigit() and term.casefold() not in GENERIC


def add_table(terms, name):
    if not usable(name):
        return
    terms.add(name)
    # Business Central tables are "Company$Table"; the company part is a business
    # name the user may ask about, so only the table part is private.
    prefix, separator, suffix = name.rpartition("$")
    if separator and prefix and usable(suffix):
        terms.add(suffix)


def tool_terms(tool, arguments, result):
    """Identifiers a tool call exposed to the model, from arguments and results."""
    terms = set()
    for item in [arguments, *(arguments.get("inputs") or [] if isinstance(arguments, dict) else [])]:
        if not isinstance(item, dict):
            continue
        for key in TERM_KEYS:
            if key == "table":
                add_table(terms, item.get(key))
            elif usable(item.get(key)):
                terms.add(item[key].strip())
        query = item.get("query")
        if isinstance(query, dict):
            for table in query.get("tables") or []:
                if isinstance(table, dict):
                    add_table(terms, table.get("name"))
                    if usable(table.get("schema")):
                        terms.add(table["schema"])
        for analysis in item.get("analyses") or []:
            if isinstance(analysis, dict):
                terms |= tool_terms(tool, analysis, None)
    if isinstance(result, dict):
        if usable(result.get("database")):
            terms.add(result["database"])
        for row in result.get("databases") or []:
            if isinstance(row, dict) and usable(row.get("name")):
                terms.add(row["name"])
        for row in result.get("schemas") or []:
            if isinstance(row, dict) and usable(row.get("schema_name")):
                terms.add(row["schema_name"])
        for source in result.get("sources") or []:
            if isinstance(source, dict):
                terms |= tool_terms(tool, {}, source)
                for key in ("id", "name"):
                    if usable(source.get(key)):
                        terms.add(source[key])
        for match in result.get("matches") or []:
            if isinstance(match, dict):
                for key in ("source_id", "database"):
                    if usable(match.get(key)):
                        terms.add(match[key])
                schema = (match.get("company") or {}).get("schema")
                if usable(schema):
                    terms.add(schema)
    return terms


def tool_names(tool, result):
    """Business company names returned to the model; these stay visible."""
    names = set()
    if isinstance(result, dict):
        for match in result.get("matches") or []:
            company = match.get("company") if isinstance(match, dict) else None
            if isinstance(company, dict) and isinstance(company.get("name"), str):
                names.add(company["name"].split(" · ")[0].strip())
        for company in (result.get("access_scope") or {}).get("companies") or []:
            if isinstance(company, dict) and isinstance(company.get("name"), str):
                names.add(company["name"].split(" · ")[0].strip())
    return names


def response_result(response):
    try:
        return json.loads(response["contentItems"][0]["text"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


class SourceTerms:
    """Private identifiers per (user, conversation), seeded from saved state."""

    def __init__(self, db):
        self.db = db
        self.scopes = {}

    def scope(self, user, conversation):
        key = (user, conversation)
        if key not in self.scopes:
            terms, keep = set(), set()
            for row in self.db.all("SELECT id,name FROM data_sources"):
                terms.update(value for value in (row["id"], row["name"]) if usable(value))
            for row in self.db.all("SELECT database_name FROM database_grants WHERE user_id=?", (user,)):
                if usable(row["database_name"]):
                    terms.add(row["database_name"])
            for row in self.db.all(
                "SELECT request_json FROM model_tool_journal WHERE user_id=? AND scope_id=?", (user, conversation)
            ):
                try:
                    request = json.loads(row["request_json"])
                except ValueError:
                    continue
                terms |= tool_terms(request.get("tool"), request.get("arguments") or {}, None)
            self.scopes[key] = (terms, keep)
        return self.scopes[key]

    def observe(self, user, conversation, tool, arguments, response):
        terms, keep = self.scope(user, conversation)
        result = response_result(response)
        terms |= tool_terms(tool, arguments if isinstance(arguments, dict) else {}, result)
        keep |= tool_names(tool, result)

    def forget(self, user, conversation):
        self.scopes.pop((user, conversation), None)


def tidy(text):
    # "[x].[x]", "`[x]`" and repeated placeholders read as one reference.
    text = re.sub(r"`\s*(\[burim i brendshëm\])\s*`", r"\1", text)
    joined = re.escape(PLACEHOLDER) + r"(?:\s*[./$]\s*" + re.escape(PLACEHOLDER) + r")+"
    return re.sub(joined, PLACEHOLDER, text)


def word(character):
    return character.isalnum() or character in "_$"


class Redactor:
    """Replace private identifiers, also across streamed chunk boundaries."""

    def __init__(self, terms, keep=(), visible_text=""):
        self.terms, self.keep = terms, keep
        self.visible = visible_text.casefold()
        self.pattern, self.active, self.size = None, [], -1
        self.raw, self.emitted = "", 0

    def compile(self):
        size = len(self.terms) + len(self.keep)
        if size != self.size:
            self.size = size
            kept = {name.casefold() for name in self.keep}
            # A name the user typed or a business company name is not hidden from them.
            self.active = sorted(
                (t for t in self.terms if usable(t) and t.casefold() not in kept and t.casefold() not in self.visible),
                key=len, reverse=True,
            )
            self.pattern = (
                re.compile(r"(?<![\w$])(?:" + "|".join(map(re.escape, self.active)) + r")(?![\w$])")
                if self.active else None
            )
        return self.pattern

    def redact(self, text):
        pattern = self.compile()
        return tidy(pattern.sub(PLACEHOLDER, text)) if pattern is not None and text else text

    def span(self, start, end):
        # Search the whole buffer so word boundaries outside the span still count.
        out, cursor = [], start
        if self.pattern is not None:
            for match in self.pattern.finditer(self.raw, start, end):
                out += [self.raw[cursor:match.start()], PLACEHOLDER]
                cursor = match.end()
        out.append(self.raw[cursor:end])
        return tidy("".join(out))

    def feed(self, chunk):
        """Return the redacted text that is safe to show now."""
        self.raw += chunk
        safe = len(self.raw)
        if self.compile() is not None:
            # Hold back only a trailing fragment that may still become a private
            # name (or a complete name whose word may continue in the next chunk).
            longest = len(self.active[0])
            for start in range(max(self.emitted, len(self.raw) - longest), len(self.raw)):
                if start and word(self.raw[start - 1]):
                    continue
                tail = self.raw[start:]
                if any(term.startswith(tail) for term in self.active):
                    safe = start
                    break
            for match in self.pattern.finditer(self.raw, self.emitted):
                if match.start() < safe < match.end():
                    safe = match.end()
        out = self.span(self.emitted, safe)
        self.emitted = safe
        return out

    def flush(self):
        self.compile()
        out = self.span(self.emitted, len(self.raw))
        self.emitted = len(self.raw)
        return out

    def reset(self, text):
        self.raw, self.emitted = text, len(text)
        return self.redact(text)
