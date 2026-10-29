import pytest

from app.db import now
from conftest import HEADERS
from test_application import create_member
from test_conversation_trash import populated
from test_report_selection import report


def purge(client, identifiers, headers=HEADERS):
    return client.post("/api/conversations/bulk-purge", headers=headers,
                       json={"conversation_ids": identifiers})


def test_direct_purge_removes_only_confirmed_conversations_and_retains_saved_reports(client, admin):
    selected, kept = populated(client), populated(client)
    db = client.app.state.db
    path, snapshot = report(client, admin["id"], "preserved")
    db.execute("UPDATE reports SET conversation_id=? WHERE id='preserved'", (selected,))
    assert purge(client, [selected], {}).status_code == 403
    assert purge(client, [selected, selected]).json()["deleted_count"] == 1
    assert not db.one("SELECT id FROM conversations WHERE id=?", (selected,))
    assert not db.one("SELECT id FROM messages WHERE conversation_id=?", (selected,))
    assert db.one("SELECT id FROM conversations WHERE id=?", (kept,))
    assert not db.all("SELECT * FROM conversation_trash")
    assert db.one("SELECT conversation_id FROM reports WHERE id='preserved'")["conversation_id"] is None
    assert path.read_bytes() == b"preserved"
    assert db.one("SELECT id FROM dataset_snapshots WHERE id=?", (snapshot,))
    assert purge(client, [selected]).status_code == 404
    with db.connect() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("invalid", ["missing", "foreign", "trashed"])
def test_invalid_exact_selection_never_partially_purges(client, admin, invalid):
    selected = populated(client)
    db = client.app.state.db
    if invalid == "foreign":
        member = create_member(client)
        db.execute("INSERT INTO conversations VALUES(?,?,?,?,?,?,?)", (
            invalid, member["id"], "Private", None, None, now(), now()))
    elif invalid == "trashed":
        invalid = populated(client)
        db.execute("INSERT INTO conversation_trash VALUES(?,?)", (invalid, now()))
    response = purge(client, [selected, invalid])
    assert response.status_code == 404
    assert db.one("SELECT id FROM conversations WHERE id=?", (selected,))
    assert db.one("SELECT id FROM messages WHERE conversation_id=?", (selected,))


def test_retiring_old_bin_restores_existing_history_once_without_deletion(client, admin):
    identifier = populated(client)
    db = client.app.state.db
    db.execute("INSERT INTO conversation_trash VALUES(?,?)", (identifier, now()))
    before = db.all("SELECT * FROM messages")
    db.execute("INSERT INTO traffic_events(created_at,direction,action,status,bytes) VALUES(?,?,?,?,?)",
               (now(), "model-backend", "migration-fixture", "error", 13))
    db.execute("UPDATE traffic_totals SET events=0,bytes=0,errors=0")
    db.execute("DELETE FROM schema_migrations WHERE version=17")
    db.initialize()
    db.initialize()
    assert not db.all("SELECT * FROM conversation_trash")
    totals = db.all("SELECT direction,count(*) AS events,sum(bytes) AS bytes,sum(status='error') AS errors FROM traffic_events GROUP BY direction")
    assert db.all("SELECT direction,events,bytes,errors FROM traffic_totals WHERE events>0 ORDER BY direction") == totals
    assert db.all("SELECT * FROM messages") == before
    assert client.get("/api/conversations/" + identifier).status_code == 200
    assert len(db.all("SELECT * FROM audit_events WHERE action='conversation.trash_retired'")) == 1
