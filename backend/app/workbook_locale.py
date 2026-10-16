"""Presentation labels only: source identifiers, values and formulas stay intact."""

from .balance_labels import EN as BALANCE_EN, SQ as BALANCE_SQ

EN = {
    "unavailable_analysis": "Unavailable analysis",
    "analysis_omitted": "The source query failed; this optional analysis was omitted.",
    "analysis_row_limit": "This optional analysis exceeded the 500-row result limit. No partial rows or totals from it were included.",
    "database_error_code": "Database error code",
    "overview": "Overview",
    "report_data": "Report data",
    "data": "Data",
    "source": "Source",
    "provided_data": "Provided data",
    "snapshot_captured": "Snapshot captured",
    "calculated_results": "Calculated results",
    "change": "change",
    "growth": "growth %",
    "average3": "3-period average",
    "share": "share %",
    "profit_detail": "Profit (revenue minus cost)",
    "margin": "Margin %",
    "profit": "Profit",
    "no_rows": "No rows match these filters.",
    "chart_limit": "first 40 categories",
    "rows_missing": "Rows: {rows}. Missing cells: {missing}.",
    "numeric_precision": "Numbers with more than 15 significant digits are kept as exact text; calculations depending on them are unavailable.",
    "trend_note": "Growth compares adjacent observed periods, using absolute previous value as denominator. Missing periods are not assumed to be zero.",
    "totals_note": "Totals apply only to the additive measures selected for this result; ratios and identifiers must not be summed.",
    "query_filters": "Query and filters",
    "scope": "Scope",
    "provided_rows": "Provided rows only.",
    "data_limitations": "Data limitations",
    "not_available": "n.a.",
    "snapshot_comment": "Immutable reporting snapshot",
    "table_name": "ReportData",
    "format_reference": "Format reference",
    "base_currency": "Workspace base currency",
    "blank_currency_note": "Blank currency codes are displayed as ALL (Albanian lek). Explicit foreign currencies are unchanged; no conversion is applied. Original codes remain in the source snapshot.",
}

SQ = {
    "unavailable_analysis": "Analiza e padisponueshme",
    "analysis_omitted": "Pyetja e burimit dështoi; kjo analizë opsionale u la jashtë.",
    "analysis_row_limit": "Kjo analizë opsionale tejkaloi kufirin prej 500 rreshtash. Asnjë rresht apo total i pjesshëm prej saj nuk u përfshi.",
    "database_error_code": "Kodi i gabimit të databazës",
    "overview": "Përmbledhje",
    "report_data": "Të dhënat e raportit",
    "data": "Të dhëna",
    "source": "Burimi",
    "provided_data": "Të dhënat e ofruara",
    "snapshot_captured": "Të dhënat u ruajtën më",
    "calculated_results": "Rezultatet e llogaritura",
    "change": "ndryshimi",
    "growth": "rritja %",
    "average3": "mesatarja e 3 periudhave",
    "share": "pjesa %",
    "profit_detail": "Fitimi (të ardhurat minus kostot)",
    "margin": "Marzhi %",
    "profit": "Fitimi",
    "no_rows": "Nuk ka rreshta që përputhen me filtrat.",
    "chart_limit": "40 kategoritë e para",
    "rows_missing": "Rreshta: {rows}. Qeliza pa të dhëna: {missing}.",
    "numeric_precision": "Numrat me më shumë se 15 shifra domethënëse ruhen si tekst i saktë; llogaritjet që varen prej tyre nuk janë të disponueshme.",
    "trend_note": "Rritja krahason periudhat e njëpasnjëshme të vrojtuara, me vlerën absolute të periudhës së mëparshme si emërues. Periudhat pa të dhëna nuk trajtohen si zero.",
    "totals_note": "Totalet vlejnë vetëm për treguesit mbledhës të zgjedhur; raportet, përqindjet dhe identifikuesit nuk mblidhen.",
    "query_filters": "Pyetja dhe filtrat",
    "scope": "Shtrirja",
    "provided_rows": "Vetëm rreshtat e ofruar.",
    "data_limitations": "Kufizimet e të dhënave",
    "not_available": "n.d.",
    "snapshot_comment": "Kopje e pandryshueshme e të dhënave të raportit",
    "table_name": "TeDhenat",
    "format_reference": "Modeli i paraqitjes",
    "base_currency": "Monedha bazë e hapësirës",
    "blank_currency_note": "Kodet bosh të monedhës shfaqen si ALL (lek shqiptar). Monedhat e huaja ruhen; nuk zbatohet konvertim. Kodet origjinale mbeten në kopjen e të dhënave burimore.",
}


def presentation(document):
    spec = document.get("workbook") or {}
    language = (spec.get("language") or "en").lower().split("-")[0]
    labels = dict(SQ if language == "sq" else EN)
    supplied = {item["key"]: item["value"] for item in spec.get("labels", [])}
    if language not in ("en", "sq") and set(EN) - supplied.keys():
        raise ValueError("Workbook translations are incomplete. Retry report generation.")
    labels.update({k: v for k, v in supplied.items() if k in EN})
    sheets = {item["index"]: item for item in spec.get("analyses", [])}
    return language, labels, sheets

# Mandatory balance views follow the same language and translation contract.
EN.update({'balance_'+k:v for k,v in BALANCE_EN.items()})
SQ.update({'balance_'+k:v for k,v in BALANCE_SQ.items()})
