from app.provider import CodexRuntime
import asyncio
import io
import json
import time
import zipfile
from xml.etree import ElementTree as ET

from app.workbooks import excel_report
from app.schemas import ReportRequest
from app.connectors import DatabaseUnavailable
from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_database_chat import call_tool, fixture_source, query_plan

NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def workbook_fixture(rows=None, options=None):
    document = {
        "title": "Monthly performance",
        "summary": "Performance from the supplied snapshot.",
        "sections": [],
        "metrics": [],
        "limitations": [],
    }
    report = {"id": "fixture", "title": document["title"], "content_json": json.dumps(document)}
    data = (
        rows
        if rows is not None
        else [
            {"month": "2026-01-01", "revenue": "100.00", "cost": "60.00"},
            {"month": "2026-02-01", "revenue": "150.00", "cost": "90.00"},
            {"month": "2026-03-01", "revenue": "120.00", "cost": "80.00"},
        ]
    )
    provenance = {
        "source": "Fixture business source",
        "columns": [
            {"name": "month", "type": "date"},
            {"name": "revenue", "type": "decimal"},
            {"name": "cost", "type": "decimal"},
        ],
        "analysis": options
        or {
            "name": "Monthly sales",
            "kind": "trend",
            "dimension": "month",
            "measures": ["revenue"],
            "revenue_column": "revenue",
            "cost_column": "cost",
        },
    }
    snapshot = {
        "rows_json": json.dumps(data),
        "provenance_json": json.dumps(provenance),
        "captured_at": "2026-10-13T10:00:00Z",
    }
    return report, snapshot


def sheet(content, name):
    return ET.fromstring(zipfile.ZipFile(io.BytesIO(content)).read(name))


def cell(xml, address):
    return xml.find(f".//x:c[@r='{address}']", NS)


def cached(xml, address):
    return cell(xml, address).find("x:v", NS).text


def test_workbook_has_native_tables_charts_formulas_and_correct_financial_caches():
    content = excel_report(*workbook_fixture())
    archive = zipfile.ZipFile(io.BytesIO(content))
    assert "xl/charts/chart1.xml" in archive.namelist()
    assert "xl/tables/table1.xml" in archive.namelist()
    xml = sheet(content, "xl/worksheets/sheet2.xml")
    assert float(cached(xml, "D7")) == 50  # Revenue change
    assert float(cached(xml, "E7")) == 0.5  # Revenue growth
    assert float(cached(xml, "F8")) == 370 / 3  # Three-period average
    assert float(cached(xml, "G7")) == 60  # Revenue less matching cost
    assert float(cached(xml, "H7")) == 0.4
    assert "ABS(B6)" in cell(xml, "E7").find("x:f", NS).text
    assert xml.find(".//x:pane", NS).get("state") == "frozen"
    overview = sheet(content, "xl/worksheets/sheet1.xml")
    formulas = [
        (c.find("x:f", NS).text, c.find("x:v", NS).text)
        for c in overview.findall(".//x:c", NS)
        if c.find("x:f", NS) is not None
    ]
    assert any(float(value) == 370 for _, value in formulas)
    assert any(float(value) == 140 for _, value in formulas)
    assert any(abs(float(value) - 140 / 370) < 1e-12 for _, value in formulas)


def test_missing_zero_and_precision_sensitive_inputs_are_not_false_zero_metrics():
    rows = [
        {"month": "2026-01-01", "revenue": "0", "cost": "0"},
        {"month": "2026-02-01", "revenue": None, "cost": "5"},
        {"month": "2026-03-01", "revenue": "1000000000000000000000000000001", "cost": "5"},
    ]
    content = excel_report(*workbook_fixture(rows))
    xml = sheet(content, "xl/worksheets/sheet2.xml")
    assert cached(xml, "H6") == "n.a."
    assert cached(xml, "E7") == "n.a."
    assert cached(xml, "G7") == "n.a."
    assert cell(xml, "B8").get("t") == "s"  # Preserved exact text
    overview = sheet(content, "xl/worksheets/sheet1.xml")
    assert all(
        c.find("x:v", NS).text == "n.a." for c in overview.findall(".//x:c", NS) if c.find("x:f", NS) is not None
    )


def test_database_text_cannot_inject_formulas_or_external_links():
    content = excel_report(
        *workbook_fixture(
            [{"product": '=HYPERLINK("https://bad.invalid")', "revenue": 12}],
            {"name": "Customer's sales", "measures": ["revenue"]},
        )
    )
    archive = zipfile.ZipFile(io.BytesIO(content))
    xml = sheet(content, "xl/worksheets/sheet2.xml")
    formulas = [c.find("x:f", NS).text for c in xml.findall(".//x:c", NS) if c.find("x:f", NS) is not None]
    assert not formulas
    assert b"HYPERLINK" in archive.read("xl/sharedStrings.xml")
    assert not any("externalLink" in name for name in archive.namelist())
    overview = sheet(content, "xl/worksheets/sheet1.xml")
    assert any("Customer''s" in f.text for f in overview.findall(".//x:f", NS))


def subscribe(client):
    client.post("/api/subscription/login", headers=HEADERS)
    for _ in range(100):
        if client.get("/api/subscription").json()["connected"]:
            return
        time.sleep(0.01)
    raise AssertionError("Fixture login did not complete.")


def wait_report(client, identifier):
    for _ in range(200):
        report = client.get(f"/api/reports/{identifier}").json()
        if report["status"] in ("completed", "failed"):
            return report
        time.sleep(0.01)
    raise AssertionError("Report did not finish.")


def test_multi_analysis_report_links_to_chat_and_excel_is_owner_only(client, admin):
    source, _ = fixture_source(client)
    subscribe(client)
    conversation = client.post("/api/conversations", headers=HEADERS, json={}).json()
    client.app.state.db.execute(
        "UPDATE conversations SET provider_thread_id=? WHERE id=?", ("fixture-origin", conversation["id"])
    )
    arguments = {
        "source_id": source["id"],
        "query": query_plan(),
        "title": "Automatic Excel",
        "instructions": "",
        "analyses": [{"name": "Comparable period", "query": query_plan(), "measures": ["revenue"]}],
    }
    response = client.portal.call(
        client.app.state.manager.tool_call,
        admin["id"],
        {
            "tool": "create_database_report",
            "namespace": "duka_reporting",
            "threadId": "fixture-origin",
            "arguments": arguments,
        },
    )
    result = json.loads(response["contentItems"][0]["text"])
    # The queued report gets no download link; it only exists once finished.
    assert "excel_download" not in result
    download = f"/api/reports/{result['report_id']}/export/xlsx"
    report = wait_report(client, result["report_id"])
    assert report["status"] == "completed", report
    assert report["conversation_id"] == conversation["id"]
    listed = next(r for r in client.get("/api/reports").json() if r["id"] == report["id"])
    assert listed["conversation_id"] == conversation["id"] and listed["stage"] == "completed"
    exported = client.get(download)
    assert exported.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(exported.content))
    assert "xl/worksheets/sheet3.xml" in archive.namelist()
    snapshot = client.app.state.db.one("SELECT * FROM dataset_snapshots WHERE id=?", (report["snapshot_id"],))
    assert len(json.loads(snapshot["provenance_json"])["analyses"]) == 1
    # Files survive report completion and are never exposed as public static assets.
    assert (client.app.state.settings.data_dir / "reports" / (report["id"] + ".xlsx")).exists()
    create_member(client)
    sign_in_member(client)
    assert client.get(download).status_code == 404
    assert client.post(f"/api/reports/{report['id']}/stop", headers=HEADERS).status_code == 404


def test_report_locks_chat_until_explicit_interrupt_and_cancels_job(client, admin, monkeypatch):
    subscribe(client)
    started = asyncio.Event()
    release = asyncio.Event()

    async def held_stream(*args, **kwargs):
        started.set()
        await release.wait()
        yield {"type": "done", "status": "completed", "text": "unused"}

    monkeypatch.setattr(CodexRuntime, "stream", held_stream)
    conversation = client.post("/api/conversations", headers=HEADERS, json={}).json()
    created = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Slow report", "conversation_id": conversation["id"], "rows": [{"revenue": 10}]},
    ).json()
    client.portal.call(started.wait)
    path = f"/api/conversations/{conversation['id']}/messages"
    assert client.post(path, headers=HEADERS, json={"content": "Too early"}).status_code == 409
    assert client.get(f"/api/conversations/{conversation['id']}").json()["messages"] == []
    assert client.post(f"/api/conversations/{conversation['id']}/stop", headers=HEADERS).status_code == 200
    report = client.get(f"/api/reports/{created['id']}").json()
    assert report["status"] == "failed" and report["stage"] == "interrupted"
    assert created["id"] not in client.app.state.report_jobs
    assert client.get(f"/api/reports/{created['id']}/export/xlsx").status_code == 409
    assert not (client.app.state.settings.data_dir / "reports" / (created["id"] + ".xlsx")).exists()


def test_extra_analyses_require_authorized_database_source(client, admin):
    request = ReportRequest.model_validate(
        {"title": "Bad input", "rows": [{"revenue": 1}], "analyses": [{"query": query_plan()}]}
    )
    assert client.post("/api/reports", headers=HEADERS, json=request.model_dump()).status_code == 422


def test_incomplete_export_cannot_publish_a_partial_workbook(client, admin):
    source, connector = fixture_source(client)
    subscribe(client)
    original = connector.report_query

    async def query(query):
        result = await original(query)
        if query.get("limit") == 1:
            result["truncated"] = True
        return result

    connector.report_query = query
    result = call_tool(
        client,
        admin,
        "create_database_report",
        {
            "source_id": source["id"],
            "query": query_plan(),
            "title": "Too much detail",
            "analyses": [{"query": query_plan(limit=1)}],
        },
    )
    report = wait_report(client, result["report_id"])
    assert report["status"] == "failed"
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 409


def test_unavailable_requested_view_stops_report_instead_of_omitting_it(client, admin):
    source, connector = fixture_source(client)
    subscribe(client)
    original = connector.report_query

    async def query(query):
        if query["tables"][0]["name"] == "BrokenView":
            raise DatabaseUnavailable("A referenced object is unavailable.", category="query", code=208)
        return await original(query)

    connector.report_query = query
    broken = query_plan(tables=[{"schema": "dbo", "name": "BrokenView", "alias": "s"}])
    result = call_tool(
        client,
        admin,
        "create_database_report",
        {
            "source_id": source["id"],
            "query": query_plan(metrics=[{"function": "sum", "column": "s.Amount", "alias": "Sales incl VAT"}]),
            "title": "Recover usable analyses",
            "analyses": [
                {"name": "POS summary", "query": broken},
                {"name": "Working breakdown", "query": query_plan()},
            ],
        },
    )
    assert "error" not in result, result
    report = wait_report(client, result["report_id"])
    assert report["status"] == "failed"
    assert client.get(f"/api/reports/{report['id']}/export/xlsx").status_code == 409


def test_required_or_connection_failure_never_becomes_optional_missing_data(client, admin):
    source, connector = fixture_source(client)
    subscribe(client)
    original = connector.report_query

    async def query(query):
        if query["tables"][0]["name"] == "BrokenView":
            raise DatabaseUnavailable("An object is unavailable.", category="query", code=208)
        return await original(query)

    connector.report_query = query
    broken = query_plan(tables=[{"name": "BrokenView", "alias": "s"}])
    result = call_tool(
        client,
        admin,
        "create_database_report",
        {
            "source_id": source["id"],
            "query": query_plan(),
            "title": "Required source",
            "analyses": [{"name": "Required analysis", "required": True, "query": broken}],
        },
    )
    report = wait_report(client, result["report_id"])
    assert report["status"] == "failed"
    assert "data collection" in report["error"]
    event = client.app.state.db.one(
        "SELECT detail_json FROM audit_events WHERE action='report.failed' AND target_id=?", (report["id"],)
    )
    assert json.loads(event["detail_json"]) == {"stage": "gathering", "error_kind": "DatabaseUnavailable"}


def test_tool_validation_identifies_bad_fields_without_returning_private_inputs(client, admin):
    result = call_tool(
        client,
        admin,
        "create_database_report",
        {
            "source_id": "unknown",
            "title": "Validation",
            "query": query_plan(tables=[{"name": "Sales", "alias": "bad alias"}]),
            "SQLSERVER_PASSWORD": "private-fixture-password",
        },
    )
    assert "error" in result and result["validation_errors"]
    assert any(e["field"] == "query.tables.0.alias" for e in result["validation_errors"])
    assert "private-fixture-password" not in json.dumps(result)
