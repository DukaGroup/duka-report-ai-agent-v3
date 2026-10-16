"""Keep complete calculation evidence without storing exported rows twice."""

import hashlib
import json

from .workbooks import ReportDataError


def output_manifest(result):
    """Integrity metadata only; never calculate or reinterpret business values."""
    return {
        "datasets": [
            {
                "name": dataset["name"], "columns": dataset["columns"],
                "row_count": len(dataset["rows"]),
                "rows_sha256": hashlib.sha256(json.dumps(
                    dataset["rows"], ensure_ascii=False, allow_nan=False, separators=(",", ":")
                ).encode()).hexdigest(),
            }
            for dataset in result["datasets"]
        ],
        "notes": result["notes"],
    }


def compact_legacy_audit(provenance, rows):
    """Upgrade old snapshots only after verifying every exported row is retained.

    Selected results already live in rows_json and analyses. Complete original
    query inputs and the model's code remain private; output hashes replace the
    redundant result copy. No source query or calculation is rerun.
    """
    audit = provenance.get("_internal", {}).get("calculation_audit", {})
    result = audit.get("result")
    if not isinstance(result, dict):
        return
    names = provenance.get("calculation", {}).get("selected_datasets", [])
    exported = [rows, *[a["rows"] for a in provenance.get("analyses", [])]]
    columns = [provenance.get("columns"), *[a.get("columns") for a in provenance.get("analyses", [])]]
    by_name = {d["name"]: d for d in result.get("datasets", [])}
    if (not names or len(names) != len(set(names)) or len(names) != len(exported)
            or any(name not in by_name or by_name[name]["rows"] != data or by_name[name]["columns"] != fields
                   for name, data, fields in zip(names, exported, columns))):
        raise ReportDataError("Calculation audit outputs do not match the captured report; duplicate data was retained and export stopped.")
    audit["outputs"] = output_manifest(result)
    audit["version"] = 2
    del audit["result"]
