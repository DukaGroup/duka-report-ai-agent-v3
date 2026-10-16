"""Currency presentation rules; original reporting snapshots remain unchanged."""

import re
import unicodedata

BASE_CURRENCY = {"code": "ALL", "name": "Albanian lek"}


def is_currency_field(name):
    name = unicodedata.normalize("NFKD", str(name).rsplit(".", 1)[-1])
    key = re.sub(r"[^a-z]", "", name.lower())
    return key in {
        "currency", "currencycode", "currencyname", "ccy", "currencyiso", "currencyisocode",
        "documentcurrency", "documentcurrencycode",
        "doccur", "doccurrency",
        "localcurrency", "localcurrencycode", "basecurrency", "basecurrencycode",
        "monedha", "monedhe", "monedhes", "kodimonedhes", "kodiimonedhes", "kodimonedhe", "monedhakodi",
        "valuta", "valute", "valutacode", "valutakodi",
    }


def currency_fields(rows, columns=(), query=None, labels=None):
    fields = set(c["name"] for c in columns) | {key for row in rows for key in row}
    recognized = {field for field in fields if is_currency_field(field)}
    # A structural query may alias "s.Currency Code" to an arbitrary result name.
    for selection in (query or {}).get("select", []):
        if not selection.get("bucket") and is_currency_field(selection["column"]):
            alias = selection.get("alias") or selection["column"].split(".", 1)[-1]
            if alias in fields:
                recognized.add(alias)
    recognized.update(field for field, label in (labels or {}).items() if field in fields and is_currency_field(label))
    return recognized


def display_currency(value):
    return BASE_CURRENCY["code"] if value is None or isinstance(value, str) and not value.strip() else value


def currency_rows(rows, columns=(), query=None):
    """Normalize only explicit currency fields, never amounts or unrelated empty cells."""
    fields = currency_fields(rows, columns, query)
    if not fields:
        return rows
    return [{**row, **{field: display_currency(row.get(field)) for field in fields}} for row in rows]
