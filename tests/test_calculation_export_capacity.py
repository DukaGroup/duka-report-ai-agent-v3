"""Export size counts selected model results once, retaining private query evidence."""

import copy
import hashlib
import json

import pytest

from app.calculation_audit import compact_legacy_audit, output_manifest
from app.reports import generate_report
from app.workbooks import ReportDataError
from test_excel_reports import subscribe, wait_report
from test_model_calculations import setup, invoke


def packed(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def test_new_calculation_export_keeps_all_inputs_and_outputs_without_duplicate_rows(client, admin):
    _, ledger, chat, thread, plan = setup(client, admin)
    result = invoke(client, admin, thread, "calculate_data", plan)
    service = client.app.state.manager.calculation_service
    rows, provenance = service.export(admin["id"], chat, result["calculation_id"], ["Eligible documents", "Balances"])
    private = provenance["_internal"]["calculation_audit"]
    assert "result" not in private and private["version"] == 2
    assert len(rows) == 601 and len(private["inputs"]["ledger"]) == 604
    assert private["inputs"]["ledger"] == ledger.rows
    assert len(provenance["analyses"][0]["rows"]) == 1
    detail = next(d for d in private["outputs"]["datasets"] if d["name"] == "Eligible documents")
    assert detail["row_count"] == 601
    assert detail["rows_sha256"] == hashlib.sha256(packed(rows).encode()).hexdigest()
    assert "rows" not in detail


def test_existing_failed_report_can_retry_under_limit_without_requery_or_truncation(client, admin):
    subscribe(client)
    _, ledger, _, thread, plan = setup(client, admin)
    calculated = invoke(client, admin, thread, "calculate_data", plan)
    created = invoke(client, admin, thread, "create_calculation_report", {
        "calculation_id": calculated["calculation_id"], "calculation_datasets": ["Eligible documents", "Balances"],
        "title": "Complete detail", "instructions": "Preserve every selected row.",
    })
    report = wait_report(client, created["report_id"])
    assert report["status"] == "completed", report
    state = client.app.state
    snapshot = state.db.one("SELECT * FROM dataset_snapshots WHERE id=?", (report["snapshot_id"],))
    legacy = json.loads(snapshot["provenance_json"])
    full_result = json.loads(state.db.one("SELECT result_json FROM calculation_runs WHERE id=?", (calculated["calculation_id"],))["result_json"])
    audit = legacy["_internal"]["calculation_audit"]
    audit.pop("outputs")
    audit.update(version=1, result=full_result)
    compact = copy.deepcopy(legacy)
    original_rows = json.loads(snapshot["rows_json"])
    compact_legacy_audit(compact, original_rows)
    old_size = len(packed(legacy).encode()) + len(snapshot["rows_json"].encode())
    new_size = len(packed(compact).encode()) + len(snapshot["rows_json"].encode())
    assert new_size < old_size
    state.settings.report_max_bytes = (new_size + old_size) // 2
    state.db.execute("UPDATE dataset_snapshots SET provenance_json=? WHERE id=?", (packed(legacy), snapshot["id"]))
    state.db.execute("UPDATE reports SET status='failed',stage='failed',error='Export limit' WHERE id=?", (report["id"],))
    client.portal.call(generate_report, state.db, state.manager, report["id"], admin["id"])
    retried = state.db.one("SELECT * FROM reports WHERE id=?", (report["id"],))
    assert retried["status"] == "completed", retried["error"]
    assert retried["error"] is None
    saved = state.db.one("SELECT * FROM dataset_snapshots WHERE id=?", (snapshot["id"],))
    assert saved["rows_json"] == snapshot["rows_json"]
    upgraded = json.loads(saved["provenance_json"])
    assert upgraded["_internal"]["calculation_audit"]["inputs"] == legacy["_internal"]["calculation_audit"]["inputs"]
    assert "result" not in upgraded["_internal"]["calculation_audit"]
    assert len(ledger.calls) == 1  # Neither source data nor model calculations were rerun.
    assert len(saved["provenance_json"].encode()) + len(saved["rows_json"].encode()) <= state.settings.report_max_bytes


def test_mismatched_legacy_rows_are_never_silently_removed_and_upgrade_is_idempotent():
    rows = [{"id": "A", "amount": "123.45"}]
    fields = [{"name": "id", "type": "text"}, {"name": "amount", "type": "decimal"}]
    result = {"datasets": [{"name": "Detail", "columns": fields, "rows": rows}], "notes": []}
    provenance = {"calculation": {"selected_datasets": ["Detail"]}, "columns": fields, "analyses": [],
                  "_internal": {"calculation_audit": {"inputs": {"source": rows}, "result": copy.deepcopy(result)}}}
    with pytest.raises(ReportDataError, match="do not match"):
        compact_legacy_audit(provenance, [{"id": "A", "amount": "999"}])
    assert "result" in provenance["_internal"]["calculation_audit"]
    compact_legacy_audit(provenance, rows)
    saved = packed(provenance)
    compact_legacy_audit(provenance, rows)
    assert packed(provenance) == saved
    assert provenance["_internal"]["calculation_audit"]["outputs"] == output_manifest(result)
