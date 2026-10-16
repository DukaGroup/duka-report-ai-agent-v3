"""One public data boundary for every report format and generated presentation.

Internal reconstruction inputs stay in the saved snapshot, never in model context,
workbook script inputs, source sheets or public JSON exports.
"""

import json


def public_snapshot(snapshot):
    provenance = json.loads(snapshot["provenance_json"])
    if "_internal" not in provenance:
        return snapshot
    provenance.pop("_internal")
    return {**snapshot, "provenance_json": json.dumps(provenance, ensure_ascii=False, separators=(",", ":"))}
