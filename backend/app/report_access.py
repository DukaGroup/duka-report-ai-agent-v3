"""Recheck saved report permissions when reading or downloading, for every provider."""

import json

from .data_access import DataAccess, capture_checks, denied, validate_capture


def saved_report_scope(db, snapshot_id, user_id):
    snapshot = db.one(
        "SELECT provenance_json,dataset_id FROM dataset_snapshots WHERE id=? AND user_id=?",
        (snapshot_id, user_id),
    )
    if not snapshot:
        if snapshot_id:
            denied()
        return [], None
    return capture_checks(json.loads(snapshot["provenance_json"])), snapshot["dataset_id"]


def authorize_saved_report(db, user_id, scope):
    checks, dataset_id = scope
    if not db.one("SELECT 1 FROM users WHERE id=? AND active=1", (user_id,)):
        denied()
    validate_capture(db, user_id, checks)
    if dataset_id:
        # Older registered-script snapshots did not retain a source receipt.
        # They still require the current dataset grant and an unscoped source.
        dataset = db.one("SELECT source_id,enabled FROM datasets WHERE id=?", (dataset_id,))
        access = DataAccess(db)
        if not dataset or not dataset["enabled"]:
            denied()
        if not access.full(user_id) and not db.one(
            "SELECT 1 FROM dataset_grants WHERE dataset_id=? AND user_id=?", (dataset_id, user_id)
        ):
            denied()
        validate_capture(db, user_id, [(dataset["source_id"], None, None)])
