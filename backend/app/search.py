"""Owner-scoped workspace search. No credential profiles or raw system logs."""

import asyncio
from fastapi import Depends, HTTPException, Request

from .security import current_user
from .connectors import SourceNotConfigured
from .report_access import saved_report_scope, authorize_saved_report


def pattern(query):
    return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def workspace_search(db, user, query):
    value = pattern(query)
    rows = db.all(
        "SELECT c.id,c.title,m.id AS message_id,m.content FROM conversations c "
        "LEFT JOIN messages m ON m.id=(SELECT id FROM messages WHERE conversation_id=c.id "
        "ORDER BY (content LIKE ? ESCAPE '\\') DESC,created_at DESC,rowid DESC LIMIT 1) "
        "WHERE c.user_id=? AND c.id NOT IN (SELECT conversation_id FROM conversation_trash) "
        "AND (c.title LIKE ? ESCAPE '\\' OR EXISTS(SELECT 1 FROM messages WHERE conversation_id=c.id "
        "AND content LIKE ? ESCAPE '\\')) ORDER BY c.updated_at DESC LIMIT 20", (value, user["id"], value, value))
    results, seen = [], set()
    for row in rows:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        text = row["content"] or ""
        index = text.casefold().find(query.casefold())
        start = max(0, index - 60)
        results.append({"kind": "conversation", "id": row["id"], "title": row["title"],
                        "message_id": row["message_id"], "excerpt": text[start:start+220]})
        if len(results) >= 20:
            break
    reports = db.all(
        "SELECT id,title,instructions,snapshot_id FROM reports WHERE user_id=? AND deleted_at IS NULL "
        "AND (title LIKE ? ESCAPE '\\' OR instructions LIKE ? ESCAPE '\\' OR content_json LIKE ? ESCAPE '\\') "
        "ORDER BY created_at DESC LIMIT 80", (user["id"], value, value, value))
    count = 0
    for report in reports:
        try:
            authorize_saved_report(db, user["id"], saved_report_scope(db, report["snapshot_id"], user["id"]))
        except SourceNotConfigured:
            continue
        results.append({"kind": "report", "id": report["id"], "title": report["title"], "excerpt": report["instructions"][:220]})
        count += 1
        if count >= 20:
            break
    if user["role"] == "devs":
        for source in db.all("SELECT id,name,description FROM data_sources WHERE name LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\' LIMIT 20", (value, value)):
            results.append({"kind": "source", "id": source["id"], "title": source["name"], "excerpt": source["description"][:220]})
    if user["role"] in ("devs", "president"):
        for member in db.all("SELECT id,name,email FROM users WHERE active=1 AND (name LIKE ? ESCAPE '\\' OR email LIKE ? ESCAPE '\\') LIMIT 20", (value,value)):
            results.append({"kind":"member","id":member["id"],"title":member["name"],"excerpt":member["email"]})
    if user["role"] == "devs":
        for event in db.all("SELECT id,action,status FROM traffic_events WHERE action LIKE ? ESCAPE '\\' OR detail_json LIKE ? ESCAPE '\\' OR payload_json LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 10", (value,value,value)):
            results.append({"kind":"traffic","id":str(event["id"]),"title":event["action"],"excerpt":event["status"]})
        for event in db.all("SELECT id,event,message FROM system_logs WHERE message LIKE ? ESCAPE '\\' OR event LIKE ? ESCAPE '\\' ORDER BY id DESC LIMIT 10", (value,value)):
            results.append({"kind":"log","id":str(event["id"]),"title":event["event"],"excerpt":event["message"][:220]})
    return {"results": results}


def register_search(app):
    @app.get("/api/search")
    async def search(request: Request, q: str = "", user=Depends(current_user)):
        query = q.strip()
        if len(query) > 200:
            raise HTTPException(422, "Search text must be at most 200 characters.")
        if len(query) < 2:
            return {"results": []}
        result = await asyncio.to_thread(workspace_search, request.app.state.db, user, query)
        for item in result["results"]:
            if item["kind"] in ("log", "traffic"):
                item["excerpt"] = request.app.state.traffic.redact_text(item["excerpt"])
        return result
