"""Retained operational events for Devs; no OS journals or raw exceptions."""

import json

from fastapi import Depends, HTTPException, Request

from .db import now
from .log_writer import PersistentLog
from .security import admin_user

LEVELS = ("info", "warning", "error")
COMPONENTS = ("application", "database", "model", "reports")


class SystemLog(PersistentLog):
    interval = 0.5

    def __init__(self, db, redactor):
        super().__init__(db)
        self.redactor = redactor

    def record(self, level, component, event, message, *, source_id=None, details=None):
        if level not in LEVELS or component not in COMPONENTS:
            return
        metadata, _ = self.redactor.payload(details or {})
        self.pending.append(
            (
                now(),
                level,
                component,
                self.redactor.redact_text(event)[:160],
                self.redactor.redact_text(message)[:2000],
                source_id,
                metadata,
            )
        )

    def write_batch(self, batch):
        with self.db.connect() as connection:
            connection.executemany(
                "INSERT INTO system_logs(created_at,level,component,event,message,source_id,details_json) "
                "VALUES(?,?,?,?,?,?,?)",
                batch,
            )


def register_system_logs(app):
    @app.get("/api/admin/system-logs")
    async def system_logs(
        request: Request,
        level: str = "",
        component: str = "",
        before: int = 0,
        limit: int = 100,
        user=Depends(admin_user),
    ):
        if (
            level
            and level not in LEVELS
            or component
            and component not in COMPONENTS
            or before < 0
            or before > 9223372036854775807
            or not 1 <= limit <= 200
        ):
            raise HTTPException(422, "Invalid log filter or page size.")
        log = request.app.state.system_logs
        await log.flush()
        clauses, params = [], []
        for name, value in (("level", level), ("component", component)):
            if value:
                clauses.append(name + "=?")
                params.append(value)
        if before:
            clauses.append("l.id<?")
            params.append(before)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = log.db.all(
            "SELECT l.*,s.name AS source_name FROM system_logs l LEFT JOIN data_sources s "
            "ON s.id=l.source_id" + where + " ORDER BY l.id DESC LIMIT ?",
            (*params, limit + 1),
        )
        events = rows[:limit]
        for row in events:
            row["message"] = log.redactor.redact_text(row["message"])
            row["details"] = json.loads(log.redactor.payload(json.loads(row.pop("details_json")))[0])
        return {
            "events": events,
            "next_before": events[-1]["id"] if len(rows) > limit else None,
            "capacity": log.capacity,
            "note": "Redacted application events only. Startup failures before application initialization "
            "and full Nginx/systemd output remain in the server journal.",
        }
