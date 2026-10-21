"""A report request finishes only after all of its captured exports are ready."""

REPORT_COUNT = "(SELECT count(*) FROM chat_report_jobs j WHERE j.message_id=m.id)"
REPORTS_READY = (
    "NOT EXISTS(SELECT 1 FROM chat_report_jobs j JOIN reports p ON p.id=j.report_id "
    "WHERE j.message_id=m.id AND (p.status<>'completed' OR p.deleted_at IS NOT NULL))"
)
REPORTS_PENDING = (
    "EXISTS(SELECT 1 FROM chat_report_jobs j JOIN reports p ON p.id=j.report_id "
    "WHERE j.message_id=m.id AND p.status IN ('queued','running') AND p.deleted_at IS NULL)"
)
REPORT_COMPLETED_AT = (
    "(SELECT max(p.completed_at) FROM chat_report_jobs j JOIN reports p ON p.id=j.report_id WHERE j.message_id=m.id)"
)
COMPLETED_AT = f"max(r.updated_at,coalesce({REPORT_COMPLETED_AT},r.updated_at))"


def report_completion(db, message_id):
    return db.one(
        f"SELECT {REPORT_COUNT} AS report_count,{REPORTS_READY} AS ready,"
        f"{REPORTS_PENDING} AS pending FROM messages m WHERE m.id=?",
        (message_id,),
    ) or {"report_count": 0, "ready": True, "pending": False}
