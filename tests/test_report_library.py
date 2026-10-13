import asyncio
import json

from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_excel_reports import subscribe, wait_report


def test_conversation_cards_have_owned_bounded_previews_and_empty_chats(client, admin):
    first = client.post("/api/conversations", headers=HEADERS, json={}).json()
    second = client.post("/api/conversations", headers=HEADERS, json={"title": "Sales question"}).json()
    db = client.app.state.db
    db.execute(
        "INSERT INTO messages VALUES('preview',?,'assistant',?,'completed','2026-10-13')",
        (second["id"], "Preview text " * 40),
    )
    rows = client.get("/api/conversations").json()
    empty = next(c for c in rows if c["id"] == first["id"])
    preview = next(c for c in rows if c["id"] == second["id"])
    assert empty["message_count"] == 0 and empty["preview"] is None
    assert preview["message_count"] == 1 and len(preview["preview"]) == 180
    create_member(client)
    sign_in_member(client)
    assert client.get("/api/conversations").json() == []


def test_report_delete_is_owned_recoverable_and_hides_downloads(client, admin):
    subscribe(client)
    chat = client.post("/api/conversations", headers=HEADERS, json={}).json()
    created = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Library report", "conversation_id": chat["id"], "rows": [{"revenue": 120}]},
    ).json()
    report = wait_report(client, created["id"])
    assert report["status"] == "completed"
    identifier = report["id"]
    filename = client.app.state.settings.data_dir / "reports" / (identifier + ".xlsx")
    assert filename.exists()
    cookie = client.cookies.get("duka_session")
    create_member(client)
    sign_in_member(client)
    assert client.delete(f"/api/reports/{identifier}", headers=HEADERS).status_code == 404
    assert client.post(f"/api/reports/{identifier}/restore", headers=HEADERS).status_code == 404
    client.cookies.set("duka_session", cookie)
    assert client.delete(f"/api/reports/{identifier}").status_code == 403
    assert client.delete(f"/api/reports/{identifier}", headers=HEADERS).status_code == 200
    assert not client.get("/api/reports").json()
    assert client.get(f"/api/reports/{identifier}").status_code == 404
    assert client.get(f"/api/reports/{identifier}/export/xlsx").status_code == 404
    trash = client.get("/api/reports?deleted=true").json()
    assert trash[0]["id"] == identifier and trash[0]["deleted_at"]
    assert filename.exists()  # Restore retains the exact immutable artifact.
    assert client.get(f"/api/conversations/{chat['id']}").status_code == 200
    assert client.post(f"/api/reports/{identifier}/restore", headers=HEADERS).status_code == 200
    assert client.get("/api/reports?deleted=true").json() == []
    assert client.get(f"/api/reports/{identifier}/export/xlsx").status_code == 200
    assert client.get(f"/api/reports/{identifier}").json()["snapshot_id"] == report["snapshot_id"]
    assert client.post(f"/api/reports/{identifier}/restore", headers=HEADERS).status_code == 404
    events = client.app.state.db.all("SELECT action,detail_json FROM audit_events WHERE target_id=?", (identifier,))
    assert {"report.deleted", "report.restored"} <= {e["action"] for e in events}
    assert all("revenue" not in json.loads(e["detail_json"]) for e in events)


def test_running_report_requires_interrupt_before_deletion(client, admin, monkeypatch):
    subscribe(client)
    started = asyncio.Event()

    async def hold(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
        yield {}

    monkeypatch.setattr(client.app.state.manager.for_user(admin["id"]), "stream", hold)
    created = client.post(
        "/api/reports", headers=HEADERS, json={"title": "In progress", "rows": [{"revenue": 1}]}
    ).json()
    client.portal.call(started.wait)
    identifier = created["id"]
    assert client.delete(f"/api/reports/{identifier}", headers=HEADERS).status_code == 409
    assert client.get(f"/api/reports/{identifier}").json()["deleted_at"] is None
    assert client.post(f"/api/reports/{identifier}/stop", headers=HEADERS).status_code == 200
    assert client.delete(f"/api/reports/{identifier}", headers=HEADERS).status_code == 200


def test_existing_database_migration_preserves_reports_and_trash(client, admin):
    created = client.post("/api/reports", headers=HEADERS, json={"title": "Existing report"}).json()
    db = client.app.state.db
    # Simulate the existing v5 application database, before the new trash column.
    db.execute("ALTER TABLE reports DROP COLUMN deleted_at")
    db.execute("DELETE FROM schema_migrations WHERE version>=6")
    db.initialize()
    assert client.get(f"/api/reports/{created['id']}").json()["title"] == "Existing report"
    assert client.delete(f"/api/reports/{created['id']}", headers=HEADERS).status_code == 200
    db.initialize()
    assert client.get("/api/reports?deleted=true").json()[0]["id"] == created["id"]
    assert client.post(f"/api/reports/{created['id']}/restore", headers=HEADERS).status_code == 200
