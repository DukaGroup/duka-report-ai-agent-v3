import csv
import asyncio
import io
import json
import hashlib
from uuid import uuid4

from .db import now
from .schemas import ReportDocument, WorkbookScriptRepair, strict_report_schema
from .workbooks import ReportDataError, excel_report
from .connectors import DatabaseUnavailable
from .workbook_locale import EN, SQ
from .currencies import BASE_CURRENCY, currency_fields, currency_rows
from .workbook_runner import WorkbookSandboxUnavailable
from .report_exports import public_snapshot

WORKBOOK_SCRIPT_API = """Always supply workbook.python_script as Python defining only def build(report):.
No imports, filesystem/network operations, raw XlsxWriter objects, eval/exec, private attributes or arbitrary formulas.
Use ordinary variables, for loops, if statements and basic builtins len/range/enumerate/zip/str/int/float/round/abs/min/max/sum/sorted/list/tuple/dict/bool.
report.sheet(name) creates an output sheet with a unique name <=31 characters, excluding reserved Overview/Scope/source sheet names. Up to eight output sheets.
report.analysis_count() returns the full dataset count. report.columns(index) returns source column names. report.currencies(index, currency_column=None) returns real codes, including ALL for blank codes.
For each sheet s:
s.title(text=None) uses the document title by default; s.paragraph(text=None) uses the summary; s.heading(text); s.narrative() includes summary, sections, metrics and limitations.
s.widths([38,24,...]) sets widths of 1–100 columns, each 8–60 characters; s.space(rows=1) inserts 0–20 rows.
s.metric(dataset, column, label, currency=None, operation='sum', currency_column=None) displays a validated source sum/count/average/min/max. count counts result rows, not business transactions. Sum invoice-count aggregate columns for transaction totals.
s.compare(left_dataset,left_column,right_dataset,right_column,label,currency=None,operation='difference',currency_column=None) compares source sums; operations difference/percent_change/ratio. left=current and right=prior for growth; difference can subtract credit notes from invoice totals. Dataset indexes must reflect actual query scopes. No invented ratios, forecasts or exchange rates.
s.table(dataset,columns=None,currency=None,currency_column=None) writes every matching row of that dataset, in aligned columns with translated headers. No row sampling/limit arguments. Full source sheets are ALWAYS added by the backend, independent of your script. Avoid unnecessarily duplicating huge source tables in output views.
s.chart(dataset,category,measures,title,chart_type='column',currency=None,currency_column=None) creates line/column/bar/area using 1–4 numeric source fields. It shows at most 1000 categories with an explicit scope note; all source rows remain in Excel. Separate money, counts and percentages into suitable charts. Chart placement and text/table rows advance automatically, preventing overlaps.
Select one actual currency for metrics/charts when datasets contain several; iterate report.currencies(index) and label currencies separately. Never combine EUR/USD with ALL. If more than one currency column exists, select the actual currency_column explicitly.
Only use field names from the dataset descriptors. Translate all authored titles, labels and explanations into the user's requested language; preserve exact source column identifiers in helper arguments. Follow available template colors/structure and column ordering; output text stays readable without merged cells crossing tables.
Create a useful main output with headline metrics, relevant comparisons and charts, then concise explanations. Keep required supporting breakdowns. Do not create duplicate dashboards. s.narrative() is available to include the generated report analysis.
All reports must preserve the requested scope throughout narrative, metrics, tables, charts and source sheets. Never add excluded records or unsolicited reconciliation datasets. Use model-authored captured results as supplied; no backend accounting rule selects or recalculates them. Decide any presentation arithmetic explicitly in your script and avoid aggregating non-additive measures. Disclose missing historical evidence without certifying a reconstruction as an original export.
For example: def build(report):\n    s = report.sheet('Sales review')\n    s.title()\n    s.metric(0, 'revenue', 'Sales', currency='ALL')\n    s.narrative()
For normal new reports, generate a custom layout using report.sheet and the helpers above. report.default_layout() is a compatibility helper; use it only when the user explicitly requests the standard/legacy layout.
"""


def data_metadata(rows, columns=None):
    """Transport metadata only: never invent a numeric or business summary."""
    return {
        "row_count": len(rows),
        "row_count_meaning": "Result rows, not a business transaction count.",
        "columns": columns or [],
        "calculation_policy": "Business totals and derived values must come from model-authored calculation outputs or explicitly model-selected query aggregates, never preview rows.",
    }


def bounded_sample(rows):
    sample = list(rows) if len(rows) <= 100 else rows[:20] + rows[-20:]
    while sample and len(json.dumps(sample, allow_nan=False).encode()) > 10000:
        sample.pop()
    return sample


def complete_columns(rows, columns):
    """Make every displayed field visible to the translation step."""
    result = list(columns or [])
    known = {c["name"] for c in result}
    for key in dict.fromkeys(k for row in rows for k in row):
        if key in known:
            continue
        values = [r.get(key) for r in rows if r.get(key) is not None]
        result.append(
            {
                "name": key,
                "type": "number"
                if values and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
                else "text",
            }
        )
    return result


def save_excel(manager, report, snapshot, content=None):
    directory = manager.settings.data_dir / "reports"
    directory.mkdir(exist_ok=True, mode=0o700)
    path = directory / (report["id"] + ".xlsx")
    temporary = directory / (report["id"] + "." + uuid4().hex + ".tmp")
    try:
        temporary.write_bytes(content if content is not None else excel_report(report, snapshot))
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


async def generate_report(db, manager, report_id, user_id, analyses=()):
    worker_acquired = False
    report = db.one("SELECT * FROM reports WHERE id=? AND user_id=?", (report_id, user_id))
    thread_id = None
    stage = "gathering"
    try:
        db.execute("UPDATE reports SET status='running',stage='gathering',error=NULL,completed_at=NULL WHERE id=?", (report_id,))
        snapshot = db.one("SELECT * FROM dataset_snapshots WHERE id=? AND user_id=?", (report["snapshot_id"], user_id))
        rows = await asyncio.to_thread(json.loads, snapshot["rows_json"])
        provenance = await asyncio.to_thread(json.loads, snapshot["provenance_json"])
        from .calculation_audit import compact_legacy_audit
        await asyncio.to_thread(compact_legacy_audit, provenance, rows)
        provenance["columns"] = await asyncio.to_thread(complete_columns, rows, provenance.get("columns", []))
        additional = list(provenance.get("analyses", []))
        analysis_errors = []
        for analysis in analyses:
            source_id = analysis.get("source_id") or provenance["source_id"]
            source = manager.connectors.authorized_source(user_id, source_id)
            database = analysis.get("database")
            if database is None and source_id == provenance["source_id"]:
                database = provenance.get("database")
            try:
                result = await manager.connectors.database_call(
                    user_id, source_id, "report_query", database=database, query=analysis["query"]
                )
            except DatabaseUnavailable as exc:
                if exc.category == "limit":
                    raise ReportDataError(str(exc)) from exc
                raise
            if result["truncated"]:
                raise ReportDataError("A requested breakdown is incomplete. No partial report was generated.")
            additional.append(
                {
                    "source": source["name"],
                    "source_id": source_id,
                    "database": result.get("database"),
                    "rows": result["rows"],
                    "columns": result["columns"],
                    "query": result["query"],
                    "scope": result["scope"],
                    "options": {k: v for k, v in analysis.items() if k != "query"},
                }
            )
        for item in additional:
            item["columns"] = await asyncio.to_thread(complete_columns, item["rows"], item.get("columns", []))
        provenance["analyses"] = additional
        provenance["analysis_errors"] = analysis_errors
        snapshot["provenance_json"] = await asyncio.to_thread(json.dumps, provenance, allow_nan=False, ensure_ascii=False, separators=(",", ":"))
        if (
            len(snapshot["provenance_json"].encode()) + len(snapshot["rows_json"].encode())
            > manager.settings.report_max_bytes
        ):
            raise ReportDataError(
                "The complete report exceeds the configured export limits. Ask an administrator to increase them; no partial report was generated."
            )
        db.execute(
            "UPDATE dataset_snapshots SET provenance_json=? WHERE id=?",
            (snapshot["provenance_json"], snapshot["id"]),
        )
        # The saved snapshot retains private audit evidence for validation. It
        # must never be sent to the narrative model or its repair prompts.
        from .balance_workbook import balance_contract
        await asyncio.to_thread(balance_contract, snapshot)
        public = public_snapshot(snapshot)
        provenance = json.loads(public["provenance_json"])
        additional = list(provenance.get("analyses", []))
        db.execute("UPDATE reports SET stage='analyzing' WHERE id=?", (report_id,))
        stage = "analyzing"
        template = db.one("SELECT * FROM report_templates WHERE id=?", (report["template_id"],))
        user_request = db.one(
            "SELECT m.content FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            "WHERE c.id=? AND c.user_id=? AND m.role='user' ORDER BY m.created_at DESC,m.rowid DESC LIMIT 1",
            (report["conversation_id"], user_id),
        )
        prompt = json.dumps(
            {
                "task": "Write a thorough business report in the language of user_request, or the report instructions when no original user request is supplied. Honor an explicit user request for a different language. Ignore the language of this task, JSON keys and database labels. Use only the supplied query results and model-authored calculation outputs, within the user's requested scope and exclusions. Analyze relevant performance, trends, breakdowns, exceptions and financial metrics supported by these sources. Comparisons outside that scope, later adjustments, revised balances and reconciliation require an explicit user request; asking for detail does not authorize them. State scope, missing inputs and limitations; never infer unavailable costs, VAT rates, exchange rates, or invent forecasts. Follow the supplied confirmed currency context. Return only the required JSON document. Write the workbook script yourself. The backend renders your chosen operations and preserves captured results; it supplies no hidden accounting formulas. Never infer full-data totals from samples. If a required total was not captured, state that limitation instead of inventing it.",
                "user_request": user_request["content"] if user_request else None,
                "base_currency": BASE_CURRENCY,
                "workbook_script_api": WORKBOOK_SCRIPT_API,
                "currency_instructions": "Albanian lek (ALL) is the confirmed workspace base currency. Blank, null or whitespace-only currency codes mean ALL, not an unknown currency. Samples display these codes as ALL; the original snapshot remains unchanged. Use ALL in base-currency headings, monetary totals, chart axes and explanations. Preserve explicit foreign currencies and distinguish document amounts from local-currency amounts. Do not combine incompatible currencies or invent conversion rates. Counts, quantities and percentages are not currencies.",
                "currency_columns": sorted(currency_fields(rows, provenance.get("columns", []), provenance.get("query"))),
                "workbook_translation_instructions": "Always fill workbook with the same language as the original user request. Translate every sheet name, table heading, chart title/legend/axis, explanatory note, calculation label and narrative. Supply analyses for index 0 (primary) and every additional analysis, with a translated name, scope, query_explanation, and columns mapping every exact source column to its translated human-readable label. Do not translate source values, identifiers, amounts, or formulas. For en/sq the backend has built-in labels; for any other language supply every standard label key translated in workbook.labels. Preserve {rows} and {missing} placeholders. Language must be an ISO code. A format reference controls style/layout, but all text still follows the user's language.",
                "standard_workbook_labels": {"en": EN, "sq": SQ},
                "format_reference": provenance.get("format_reference"),
                "source_warnings": provenance.get("warnings", []),
                "empty_result_instructions": "A successful database query with zero matching rows is a valid empty-period report, not a connection failure. State the exact filters and that no matching records were returned. Never invent sales or change the requested date to find populated records.",
                "title": report["title"],
                "instructions": report["instructions"],
                "template": template["name"],
                "sections": json.loads(template["sections_json"]),
                "provenance": {k: v for k, v in provenance.items() if k != "analyses"},
                "data_metadata": data_metadata(rows, provenance.get("columns", [])),
                "data": currency_rows(bounded_sample(rows), provenance.get("columns", []), provenance.get("query")),
                "data_view": "Bounded sample for narrative/layout only; complete tables are preserved for your workbook script. No backend numeric summary is supplied. Use captured model-calculation summary datasets or explicit query aggregates for population totals; never sum these samples.",
                "additional_analyses": [
                    {
                        **{k: v for k, v in a.items() if k != "rows"},
                        "rows": currency_rows(bounded_sample(a["rows"]), a.get("columns", []), a.get("query")),
                        "currency_columns": sorted(currency_fields(a["rows"], a.get("columns", []), a.get("query"))),
                        "data_metadata": data_metadata(a["rows"], a.get("columns", [])),
                        "data_view": "Sample for narrative only. All result rows are exported to Excel.",
                    }
                    for a in additional
                ],
            },
            ensure_ascii=False,
        )
        # The immutable serialized snapshot is all the workbook worker needs.
        # Release the gathered row dictionaries before it allocates Excel cells.
        rows = provenance = additional = result = item = None
        runtime = await manager.acquire_worker(user_id, "report", report_id, report["model"])
        worker_acquired = True
        thread_id = await runtime.thread(None, report["model"])
        manager.report_threads[report_id] = thread_id
        setting = db.one("SELECT reasoning_effort FROM report_settings WHERE report_id=?", (report_id,))
        effort_options = {"reasoning_effort": setting["reasoning_effort"]} if setting and setting["reasoning_effort"] is not None else {}
        fragments = ""
        async for event in runtime.stream(thread_id, prompt, report["model"], strict_report_schema(), **effort_options):
            if event["type"] == "delta":
                fragments += event["text"]
            if event["type"] == "done":
                if event["status"] != "completed":
                    raise ValueError("Report generation was interrupted.")
                fragments = event.get("text") or fragments
        document = ReportDocument.model_validate_json(fragments)
        if document.workbook is None:
            raise ReportDataError("Workbook translations are missing. Retry report generation.")
        async def workbook_phase(value):
            db.execute("UPDATE reports SET stage=? WHERE id=?", (value, report_id))

        stage = "excel"
        for attempt in range(3):
            await workbook_phase("excel")
            report["content_json"] = document.model_dump_json()
            db.execute('UPDATE reports SET content_json=? WHERE id=?',(report['content_json'],report_id))
            try:
                content, verified = await manager.workbook_runner.build(report, snapshot, workbook_phase)
                db.audit(user_id, "report.workbook_validated", report_id, {
                    "attempt": attempt+1, "script_sha256": hashlib.sha256(document.workbook.python_script.encode()).hexdigest(), **verified,
                })
                break
            except WorkbookSandboxUnavailable:
                raise
            except ReportDataError as exc:
                db.audit(user_id, "report.script_retry", report_id, {"attempt": attempt+1,"validation_error":str(exc),"error_kind":type(exc).__name__})
                if attempt == 2:
                    raise ReportDataError("Workbook script could not pass execution and validation after three attempts. No downloadable report was published.") from exc
                await workbook_phase("repairing")
                repair = json.dumps({"task": "Repair only the workbook Python script using the documented helpers. Preserve report language, data scope, full breakdowns and currencies. Return only the required JSON.",
                                     "validation_error": str(exc), "workbook_script_api": WORKBOOK_SCRIPT_API,
                                     "previous_script": document.workbook.python_script}, ensure_ascii=False)
                fixed = ""
                async for event in runtime.stream(thread_id, repair, report["model"], strict_report_schema(WorkbookScriptRepair), **effort_options):
                    if event["type"] == "delta":
                        fixed += event["text"]
                    if event["type"] == "done":
                        if event["status"] != "completed":
                            raise ReportDataError("Report generation was interrupted by the user.")
                        fixed = event.get("text") or fixed
                document.workbook.python_script = WorkbookScriptRepair.model_validate_json(fixed).python_script
        save_excel(manager, report, snapshot, content)
        db.execute(
            "UPDATE reports SET status='completed', stage='completed', error=NULL, content_json=?, completed_at=? WHERE id=?",
            (document.model_dump_json(), now(), report_id),
        )
        db.audit(user_id, "report.completed", report_id)
    except asyncio.CancelledError:
        db.execute(
            "UPDATE reports SET status='failed',stage='interrupted',error=?,completed_at=? WHERE id=?",
            ("Report generation was interrupted by the user.", now(), report_id),
        )
        db.audit(user_id, "report.interrupted", report_id)
        raise
    except ReportDataError as exc:
        db.execute(
            "UPDATE reports SET status='failed',stage='failed',error=?,completed_at=? WHERE id=?",
            (str(exc), now(), report_id),
        )
        db.audit(user_id, "report.failed", report_id)
    except Exception as exc:
        # Credentials/provider exceptions never become report content or audit payloads.
        db.execute(
            "UPDATE reports SET status='failed',stage='failed', error=?,completed_at=? WHERE id=?",
            (
                {
                    "gathering": "Report data collection failed. Check source status and query permissions.",
                    "analyzing": "The selected model could not finish the report narrative. Check your subscription and retry.",
                    "excel": "Excel workbook creation failed. Retry the report or contact the administrator.",
                }[stage],
                now(),
                report_id,
            ),
        )
        db.audit(user_id, "report.failed", report_id, {"stage": stage, "error_kind": type(exc).__name__})
    finally:
        manager.report_threads.pop(report_id, None)
        if worker_acquired:
            await manager.release_worker(user_id, "report", report_id)


def markdown_report(report, snapshot):
    doc = json.loads(report["content_json"])
    lines = [f"# {doc['title']}", "", doc["summary"], ""]
    if doc["metrics"]:
        lines += ["## Key metrics", ""]
        for metric in doc["metrics"]:
            lines.append(f"- **{metric['label']}: {metric['value']}** — {metric['explanation']}")
        lines.append("")
    for section in doc["sections"]:
        lines += [f"## {section['heading']}", "", section["body"], ""]
    if doc["limitations"]:
        lines += ["## Limitations", ""] + [f"- {x}" for x in doc["limitations"]] + [""]
    provenance = json.loads(snapshot["provenance_json"])
    lines += [
        "## Data provenance",
        "",
        f"Source: {provenance.get('source', 'Provided data')}",
        f"Captured: {snapshot['captured_at']}",
        f"Rows: {len(json.loads(snapshot['rows_json']))}",
    ]
    return "\n".join(lines)


def csv_snapshot(snapshot):
    rows = json.loads(snapshot["rows_json"])
    output = io.StringIO(newline="")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        # Protect spreadsheet users from formulas in untrusted text values.
        writer.writerow(
            {
                k: "'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v
                for k, v in row.items()
            }
        )
    return output.getvalue()
