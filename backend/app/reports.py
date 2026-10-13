import csv
import asyncio
import io
import json
from decimal import Decimal, InvalidOperation

from .db import now
from .schemas import ReportDocument, strict_report_schema
from .workbooks import ReportDataError, excel_report
from .connectors import DatabaseUnavailable


def numeric_summary(rows, columns=None):
    """Compute simple numeric totals deterministically, before asking for narrative."""
    sums = {}
    numeric_columns = {
        c.get("name")
        for c in columns or []
        if c.get("type", "").lower()
        in ("decimal", "numeric", "money", "smallmoney", "number", "integer", "float", "real", "int", "bigint")
    }
    for row in rows:
        for key, value in row.items():
            if not isinstance(value, bool) and (
                isinstance(value, (int, float)) or (isinstance(value, str) and key in numeric_columns)
            ):
                try:
                    number = Decimal(str(value))
                    if number.is_finite():
                        sums[key] = sums.get(key, Decimal(0)) + number
                except InvalidOperation:
                    pass
    return {
        "row_count": len(rows),
        "row_count_meaning": "Result rows, not transaction counts. Use a business COUNT metric for transaction counts.",
        "numeric_column_sums": {k: str(v) for k, v in sums.items()},
        "note": "Sums include every numeric column, including identifiers; only use totals meaningful for the report.",
    }


def save_excel(manager, report, snapshot, content=None):
    directory = manager.settings.data_dir / "reports"
    directory.mkdir(exist_ok=True, mode=0o700)
    path = directory / (report["id"] + ".xlsx")
    temporary = directory / (report["id"] + ".tmp")
    try:
        temporary.write_bytes(content if content is not None else excel_report(report, snapshot))
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


async def generate_report(db, manager, report_id, user_id, analyses=()):
    report = db.one("SELECT * FROM reports WHERE id=? AND user_id=?", (report_id, user_id))
    thread_id = None
    stage = "gathering"
    try:
        db.execute("UPDATE reports SET status='running',stage='gathering' WHERE id=?", (report_id,))
        snapshot = db.one("SELECT * FROM dataset_snapshots WHERE id=? AND user_id=?", (report["snapshot_id"], user_id))
        rows = json.loads(snapshot["rows_json"])
        provenance = json.loads(snapshot["provenance_json"])
        additional = []
        analysis_errors = []
        for analysis in analyses:
            try:
                result = await manager.connectors.database_call(
                    user_id, provenance["source_id"], "query", query=analysis["query"]
                )
            except DatabaseUnavailable as exc:
                if analysis.get("required") or exc.category != "query":
                    raise
                # A broken optional view must not erase successful, complete source results.
                analysis_errors.append(
                    {
                        "name": analysis["name"],
                        "error": str(exc),
                        "database_error_code": exc.code,
                        "query": analysis["query"],
                    }
                )
                continue
            if result["truncated"]:
                raise ReportDataError("An additional analysis exceeded the row limit. Aggregate or narrow its filters.")
            additional.append(
                {
                    "source": provenance["source"],
                    "rows": result["rows"],
                    "columns": result["columns"],
                    "query": result["query"],
                    "scope": result["scope"],
                    "options": {k: v for k, v in analysis.items() if k != "query"},
                }
            )
        if additional or analysis_errors:
            provenance["analyses"] = additional
            provenance["analysis_errors"] = analysis_errors
            snapshot["provenance_json"] = json.dumps(provenance, allow_nan=False)
            db.execute(
                "UPDATE dataset_snapshots SET provenance_json=? WHERE id=?",
                (snapshot["provenance_json"], snapshot["id"]),
            )
        db.execute("UPDATE reports SET stage='analyzing' WHERE id=?", (report_id,))
        stage = "analyzing"
        template = db.one("SELECT * FROM report_templates WHERE id=?", (report["template_id"],))
        prompt = json.dumps(
            {
                "task": "Write a thorough business report in English unless instructions explicitly request another language. Use only the supplied data and calculated summaries. Analyze relevant performance, trends, comparisons, breakdowns, exceptions and financial metrics supported by these sources. State scope, missing inputs and limitations; never infer unavailable costs, VAT rates, currency, or invent forecasts. Return only the required JSON document. An Excel workbook with these data and deterministic formulas will be generated automatically.",
                "title": report["title"],
                "instructions": report["instructions"],
                "template": template["name"],
                "sections": json.loads(template["sections_json"]),
                "provenance": {k: v for k, v in provenance.items() if k != "analyses"},
                "computed_summary": numeric_summary(rows, provenance.get("columns", [])),
                "data": rows,
                "additional_analyses": [
                    {**a, "computed_summary": numeric_summary(a["rows"], a.get("columns", []))} for a in additional
                ],
            },
            ensure_ascii=False,
        )
        runtime = manager.for_user(user_id)
        thread_id = await runtime.thread(None, report["model"])
        manager.report_threads[report_id] = thread_id
        fragments = ""
        async for event in runtime.stream(thread_id, prompt, report["model"], strict_report_schema()):
            if event["type"] == "delta":
                fragments += event["text"]
            if event["type"] == "done":
                if event["status"] != "completed":
                    raise ValueError("Report generation was interrupted.")
                fragments = event.get("text") or fragments
        document = ReportDocument.model_validate_json(fragments)
        for failure in analysis_errors:
            note = f"Unavailable analysis: {failure['name']}. {failure['error']}"
            if failure.get("database_error_code"):
                note += f" Database error code: {failure['database_error_code']}."
            document.limitations.append(note)
        db.execute("UPDATE reports SET stage='excel' WHERE id=?", (report_id,))
        stage = "excel"
        report["content_json"] = document.model_dump_json()
        # Build in a worker; publish only after the cancellable await returns.
        content = await asyncio.to_thread(excel_report, report, snapshot)
        save_excel(manager, report, snapshot, content)
        db.execute(
            "UPDATE reports SET status='completed', stage='completed', content_json=?, completed_at=? WHERE id=?",
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
                    "analyzing": "ChatGPT could not finish the report narrative. Check your subscription and retry.",
                    "excel": "Excel workbook creation failed. Retry the report or contact the administrator.",
                }[stage],
                now(),
                report_id,
            ),
        )
        db.audit(user_id, "report.failed", report_id, {"stage": stage, "error_kind": type(exc).__name__})
    finally:
        manager.report_threads.pop(report_id, None)


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
