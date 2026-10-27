"""Legacy tool snapshots are upgraded once without changing member data access."""

import json

import pytest

from app.provider import CONTEXT_CAPABILITY_VERSION
from conftest import HEADERS
from test_claude_subscriptions import claude as claude_fixture, connect_claude, choose, send
from test_excel_reports import subscribe


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
@pytest.mark.parametrize("old_version", [None, "pre-web-tools"])
def test_existing_chat_refreshes_once_and_preserves_history_and_grants(client, admin, claude, provider, old_version):
    subscribe(client) if provider == "chatgpt" else connect_claude(client)
    choose(client, provider)
    cid = client.post("/api/conversations", headers=HEADERS, json={}).json()["id"]
    send(client, cid, "Keep my original conversation.")
    db = client.app.state.db
    original = client.get(f"/api/conversations/{cid}").json()
    old_thread = original["provider_thread_id"]
    tables = ("users", "source_grants", "source_access_policies", "database_grants", "dataset_grants")
    before = {table: db.all("SELECT * FROM " + table) for table in tables}
    if old_version is None:
        db.execute("DELETE FROM model_thread_capabilities WHERE thread_id=?", (old_thread,))
    else:
        db.execute("UPDATE model_thread_capabilities SET version=? WHERE thread_id=?", (old_version, old_thread))

    events = send(client, cid, "si eshte moti ne tirane sot")
    refreshed = client.get(f"/api/conversations/{cid}").json()
    new_thread = refreshed["provider_thread_id"]
    assert new_thread != old_thread
    assert refreshed["messages"][:2] == original["messages"]
    assert any(event["type"] == "snapshot" and event.get("activity") == "refreshing" for event in events)
    assert not next(event for event in events if event["type"] == "route")["switched"]
    assert db.one("SELECT version FROM model_thread_capabilities WHERE thread_id=?", (new_thread,))["version"] == CONTEXT_CAPABILITY_VERSION
    assert before == {table: db.all("SELECT * FROM " + table) for table in tables}
    # The old version marker remains old; an archived branch cannot claim to
    # have today's capabilities just because another native thread was upgraded.
    old = db.one("SELECT version FROM model_thread_capabilities WHERE thread_id=?", (old_thread,))
    assert old is None if old_version is None else old["version"] == old_version

    repeated = send(client, cid, "Keep using this updated conversation.")
    assert client.get(f"/api/conversations/{cid}").json()["provider_thread_id"] == new_thread
    assert not any(event.get("activity") == "refreshing" for event in repeated)
    assert len(db.all("SELECT * FROM model_thread_capabilities WHERE thread_id=?", (new_thread,))) == 1
    assert json.dumps(before) == json.dumps({table: db.all("SELECT * FROM " + table) for table in tables})
