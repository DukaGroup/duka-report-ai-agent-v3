"""Exercise the isolated Excel path beyond both former annual-export limits."""

import json

import pytest

from app.config import Settings
from app.workbook_runner import WorkbookRunner
from test_workbook_scripts import scripted_fixture


@pytest.mark.asyncio
async def test_annual_snapshot_over_50mb_and_100000_rows_builds_and_verifies_in_full(tmp_path):
    settings = Settings(data_dir=tmp_path, env_file=None)
    settings.prepare()
    count = 100_001
    rows = [{"month": "2025-01-01", "revenue": index, "cost": 1,
             "Përshkrimi": "Përshkrim " + "x" * 500 + str(index)} for index in range(count)]
    report, snapshot, document = scripted_fixture("""def build(report):
    s = report.sheet('Annual sales')
    s.title()
    s.metric(0, 'revenue', 'Sales ALL', currency='ALL')
""", rows)
    document["workbook"]["analyses"][0]["columns"].append({"column": "Përshkrimi", "label": "Description"})
    report["content_json"] = json.dumps(document, ensure_ascii=False)
    snapshot["rows_json"] = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    assert len(snapshot["rows_json"].encode()) > 50_000_000
    assert len(snapshot["rows_json"].encode()) < settings.report_max_bytes
    assert settings.report_max_rows >= count
    # Release the fixture dictionary copy too: the runner uses only the snapshot.
    del rows
    content, verified = await WorkbookRunner(settings).build(report, snapshot)
    assert content.startswith(b'PK')
    assert verified == {"source_rows": [count], "verified_calculations": 1}
    assert list((tmp_path / 'excel-jobs').iterdir()) == []
