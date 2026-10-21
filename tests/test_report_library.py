from app.provider import CodexRuntime
import asyncio
import json

from conftest import HEADERS
from test_application import create_member, sign_in_member
from test_excel_reports import subscribe, wait_report


def test_deleting_conversation_preserves_saved_report_snapshot_and_exact_excel_download(client, admin):
    subscribe(client)
    chat = client.post("/api/conversations", headers=HEADERS, json={}).json()
    created = client.post(
        "/api/reports",
        headers=HEADERS,
        json={"title": "Keep this Excel", "conversation_id": chat["id"], "rows": [{"revenue": 120}]},
    ).json()
    report = wait_report(client, created["id"])
    assert report["status"] == "completed"
    url = f"/api/reports/{report['id']}/export/xlsx"
    before = client.get(url).content
    db = client.app.state.db
    assert not db.delete_conversation(chat["id"], "not-the-owner")
    assert db.one("SELECT conversation_id FROM reports WHERE id=?", (report["id"],))["conversation_id"] == chat["id"]
    assert client.delete(f"/api/conversations/{chat['id']}", headers=HEADERS).status_code == 200
    assert client.get(f"/api/conversations/{chat['id']}").status_code == 404
    saved = client.get(f"/api/reports/{report['id']}")
    assert saved.status_code == 200
    assert saved.json()["conversation_id"] == chat["id"]
    assert saved.json()["snapshot_id"] == report["snapshot_id"]
    assert db.one("SELECT id FROM dataset_snapshots WHERE id=?", (report["snapshot_id"],))
    assert any(r["id"] == report["id"] for r in client.get("/api/reports").json())
    after = client.get(url)
    assert after.status_code == 200 and after.content == before


def test_conversation_cards_have_owned_bounded_previews_and_hide_empty_chats(client, admin):
    first = client.post("/api/conversations", headers=HEADERS, json={}).json()
    second = client.post("/api/conversations", headers=HEADERS, json={"title": "Sales question"}).json()
    db = client.app.state.db
    db.execute(
        "INSERT INTO messages VALUES('preview',?,'assistant',?,'completed','2026-10-13')",
        (second["id"], "Preview text " * 40),
    )
    rows = client.get("/api/conversations").json()
    assert not any(c['id'] == first['id'] for c in rows)
    preview = next(c for c in rows if c["id"] == second["id"])
    assert client.get(f"/api/conversations/{first['id']}").status_code == 200
    assert preview["message_count"] == 1 and len(preview["preview"]) == 180
    create_member(client)
    sign_in_member(client)
    assert client.get("/api/conversations").json() == []


def test_upload_only_and_report_only_chats_remain_visible_without_messages(client, admin):
    upload_chat = client.post('/api/conversations',headers=HEADERS,json={}).json()
    report_chat = client.post('/api/conversations',headers=HEADERS,json={}).json()
    untouched = client.post('/api/conversations',headers=HEADERS,json={}).json()
    assert client.post(f"/api/conversations/{upload_chat['id']}/attachments",headers=HEADERS,
                       files={'file':('notes.txt',b'Fixture attachment')}).status_code == 201
    client.app.state.db.execute(
        "INSERT INTO reports(id,user_id,conversation_id,template_id,title,instructions,status,created_at) VALUES('draft-report',?,?,'executive','Keep report','','blocked','now')",
        (admin['id'],report_chat['id']),
    )
    listed = client.get('/api/conversations').json()
    assert {c['id'] for c in listed} == {upload_chat['id'],report_chat['id']}
    assert all(c['message_count'] == 0 for c in listed)
    assert client.get(f"/api/conversations/{untouched['id']}").status_code == 200


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

    monkeypatch.setattr(CodexRuntime, "stream", hold)
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


def test_empty_trash_permanently_removes_owned_reports_files_and_snapshots_only(client, admin):
    subscribe(client)
    chat = client.post("/api/conversations", headers=HEADERS, json={}).json()
    reports = []
    for title in ["Purge this report", "Keep this report"]:
        created = client.post("/api/reports", headers=HEADERS,
                              json={"title": title, "conversation_id": chat["id"], "rows": [{"revenue": 120}]}).json()
        reports.append(wait_report(client, created["id"]))
    purged, kept = reports
    directory = client.app.state.settings.data_dir / "reports"
    file = directory / (purged["id"] + ".xlsx")
    temporary = directory / (purged["id"] + ".leftover.tmp")
    temporary.write_bytes(b"incomplete")
    kept_content = client.get(f"/api/reports/{kept['id']}/export/xlsx").content
    assert client.delete(f"/api/reports/{purged['id']}", headers=HEADERS).status_code == 200
    cookie = client.cookies.get("duka_session")
    create_member(client)
    sign_in_member(client)
    foreign = client.post("/api/reports", headers=HEADERS, json={"title": "Another user's trash"}).json()
    assert client.delete(f"/api/reports/{foreign['id']}", headers=HEADERS).status_code == 200
    foreign_file = directory / (foreign["id"] + ".xlsx")
    foreign_file.write_bytes(b"foreign cache")
    client.cookies.set("duka_session", cookie)
    assert client.delete("/api/reports/trash").status_code == 403
    response = client.delete("/api/reports/trash", headers=HEADERS)
    assert response.status_code == 200 and response.json()["deleted_count"] == 1
    db = client.app.state.db
    assert not file.exists() and not temporary.exists()
    assert not db.one("SELECT id FROM reports WHERE id=?", (purged["id"],))
    assert not db.one("SELECT id FROM dataset_snapshots WHERE id=?", (purged["snapshot_id"],))
    assert db.one("SELECT id FROM reports WHERE id=?", (foreign["id"],)) and foreign_file.exists()
    assert client.get(f"/api/reports/{kept['id']}/export/xlsx").content == kept_content
    assert client.get(f"/api/conversations/{chat['id']}").status_code == 200
    assert client.post(f"/api/reports/{purged['id']}/restore", headers=HEADERS).status_code == 404
    assert client.get(f"/api/reports/{purged['id']}/export/xlsx").status_code == 404
    assert client.get("/api/reports?deleted=true").json() == []
    assert client.delete("/api/reports/trash", headers=HEADERS).json()["deleted_count"] == 0


def test_empty_trash_preserves_snapshots_referenced_by_another_report(client, admin):
    subscribe(client)
    first = client.post("/api/reports", headers=HEADERS, json={"title": "Shared snapshot", "rows": [{"revenue": 1}]}).json()
    assert wait_report(client, first["id"])["status"] == "completed"
    second = client.post("/api/reports", headers=HEADERS, json={"title": "Retained report"}).json()
    db = client.app.state.db
    db.execute("UPDATE reports SET snapshot_id=? WHERE id=?", (first["snapshot_id"], second["id"]))
    assert client.delete(f"/api/reports/{first['id']}", headers=HEADERS).status_code == 200
    assert client.delete("/api/reports/trash", headers=HEADERS).status_code == 200
    assert db.one("SELECT id FROM dataset_snapshots WHERE id=?", (first["snapshot_id"],))
    assert client.get(f"/api/reports/{second['id']}").status_code == 200


def test_empty_trash_failure_keeps_reports_and_snapshots_recoverable(client, admin, monkeypatch):
    from pathlib import Path

    subscribe(client)
    created = client.post("/api/reports", headers=HEADERS, json={"title": "Filesystem error", "rows": [{"revenue": 1}]}).json()
    assert wait_report(client, created["id"])["status"] == "completed"
    assert client.delete(f"/api/reports/{created['id']}", headers=HEADERS).status_code == 200
    original = Path.unlink

    def unavailable(path, *args, **kwargs):
        if path.name == created["id"] + ".xlsx":
            raise PermissionError("private storage path")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unavailable)
    response = client.delete("/api/reports/trash", headers=HEADERS)
    assert response.status_code == 503 and "private storage path" not in response.text
    assert client.app.state.db.one("SELECT id FROM dataset_snapshots WHERE id=?", (created["snapshot_id"],))
    assert client.get("/api/reports?deleted=true").json()[0]["id"] == created["id"]
    assert client.post(f"/api/reports/{created['id']}/restore", headers=HEADERS).status_code == 200


def test_empty_trash_refuses_running_reports_even_if_the_database_is_inconsistent(client, admin):
    created = client.post("/api/reports", headers=HEADERS, json={"title": "Bad state"}).json()
    client.app.state.db.execute("UPDATE reports SET deleted_at='now',status='running' WHERE id=?", (created["id"],))
    assert client.delete("/api/reports/trash", headers=HEADERS).status_code == 409
    assert client.app.state.db.one("SELECT id FROM reports WHERE id=?", (created["id"],))
