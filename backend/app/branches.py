"""Restore archived chat transcripts atomically, retaining the displaced version."""

import asyncio
import json

from fastapi import Depends, HTTPException

from .db import now
from .security import current_user


def register_branches(app):
    def owned(cid, user):
        if not app.state.db.one("SELECT id FROM conversations WHERE id=? AND user_id=? AND id NOT IN (SELECT conversation_id FROM conversation_trash)", (cid, user)):
            raise HTTPException(404, "Conversation not found.")

    @app.get("/api/conversations/{cid}/versions")
    async def versions(cid: str, user=Depends(current_user)):
        owned(cid, user["id"])
        rows = app.state.db.all(
            "SELECT id,created_at,snapshot_json FROM conversation_branches WHERE conversation_id=? ORDER BY created_at DESC,rowid DESC",
            (cid,),
        )
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "message_count": len(json.loads(row["snapshot_json"])["messages"]),
                "preview": next(
                    (m["content"][:180] for m in json.loads(row["snapshot_json"])["messages"] if m["role"] == "user"),
                    "",
                ),
            }
            for row in rows
        ]

    @app.post("/api/conversations/{cid}/versions/{identifier}/restore")
    async def restore(cid: str, identifier: str, user=Depends(current_user)):
        owned(cid, user["id"])
        state, db = app.state, app.state.db
        lock = state.locks.setdefault(cid, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Stop the current response before restoring a version.")
        async with lock:
            owned(cid, user["id"])
            with db.connect() as c:
                c.execute("BEGIN IMMEDIATE")
                if (
                    c.execute(
                        "SELECT id FROM reports WHERE conversation_id=? AND status IN ('queued','running')", (cid,)
                    ).fetchone()
                    or c.execute(
                        "SELECT id FROM chat_runs WHERE conversation_id=? AND status IN ('queued','running','paused')",
                        (cid,),
                    ).fetchone()
                ):
                    raise HTTPException(409, "Stop the current response and reports before restoring a version.")
                branch = c.execute(
                    "SELECT snapshot_json FROM conversation_branches WHERE id=? AND conversation_id=?",
                    (identifier, cid),
                ).fetchone()
                if not branch:
                    raise HTTPException(404, "Conversation version not found.")
                snapshot = json.loads(branch["snapshot_json"])
                current = [
                    dict(r)
                    for r in c.execute(
                        "SELECT rowid AS message_order,* FROM messages WHERE conversation_id=? ORDER BY created_at,rowid",
                        (cid,),
                    )
                ]
                if current:
                    db.archive_chat_branch(c, cid, current[0], current)
                reports = snapshot.get("active_report_ids", snapshot.get("report_ids", []))
                calculations = snapshot.get("active_calculation_ids", snapshot.get("calculation_ids", []))
                c.execute("UPDATE reports SET conversation_id=NULL WHERE conversation_id=?", (cid,))
                c.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
                for m in snapshot["messages"]:
                    c.execute(
                        "INSERT INTO messages VALUES(?,?,?,?,?,?)",
                        (
                            m["id"],
                            cid,
                            m["role"],
                            m["content"],
                            "interrupted" if m["status"] == "streaming" else m["status"],
                            m["created_at"],
                        ),
                    )
                for link in snapshot.get("attachments", []):
                    if c.execute(
                        "SELECT id FROM attachments WHERE id=? AND user_id=?", (link["attachment_id"], user["id"])
                    ).fetchone():
                        c.execute(
                            "INSERT OR IGNORE INTO message_attachments VALUES(?,?)",
                            (link["message_id"], link["attachment_id"]),
                        )
                for revision in snapshot.get("revisions", []):
                    c.execute(
                        "INSERT OR IGNORE INTO message_revisions VALUES(?,?,?,?,?,?,?,?)",
                        tuple(
                            revision[k]
                            for k in (
                                "id",
                                "conversation_id",
                                "user_message_id",
                                "previous_content",
                                "assistant_content",
                                "assistant_status",
                                "attachment_ids_json",
                                "created_at",
                            )
                        ),
                    )
                for rid in reports:
                    c.execute(
                        "UPDATE reports SET conversation_id=? WHERE id=? AND user_id=? AND conversation_id IS NULL",
                        (cid, rid, user["id"]),
                    )
                for calc in calculations:
                    c.execute(
                        "DELETE FROM archived_calculations WHERE calculation_id IN (SELECT id FROM calculation_runs WHERE id=? AND conversation_id=? AND user_id=?)",
                        (calc, cid, user["id"]),
                    )
                c.execute("DELETE FROM conversation_provider_threads WHERE conversation_id=?", (cid,))
                c.execute("UPDATE conversations SET provider_thread_id=NULL,updated_at=? WHERE id=?", (now(), cid))
            db.audit(user["id"], "conversation.version_restored", cid, {"version_id": identifier})
        return {"ok": True}
