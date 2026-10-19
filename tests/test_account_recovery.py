import json
import time


from app.security import token_hash, verify_password
from conftest import HEADERS
from test_application import create_member, sign_in_member


def test_change_password_revokes_old_sessions_and_preserves_grants(client, admin):
    member = create_member(client)
    db = client.app.state.db
    source = client.post(
        "/api/admin/sources", headers=HEADERS, json={"name": "Existing source", "kind": "sqlserver"}
    ).json()
    db.execute("INSERT INTO source_grants VALUES(?,?)", (source["id"], member["id"]))
    sign_in_member(client)
    previous_cookie = client.cookies.get("duka_session")
    assert (
        client.post(
            "/api/auth/password",
            headers=HEADERS,
            json={"current_password": "wrong", "new_password": "new-secure-password"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/auth/password",
            headers=HEADERS,
            json={"current_password": "member-long-password", "new_password": "short"},
        ).status_code
        == 422
    )
    response = client.post(
        "/api/auth/password",
        headers=HEADERS,
        json={"current_password": "member-long-password", "new_password": "new-secure-password"},
    )
    assert response.status_code == 200
    assert client.get("/api/auth/status").json()["user"]["id"] == member["id"]
    assert client.cookies.get("duka_session") != previous_cookie
    assert not db.one("SELECT * FROM sessions WHERE token_hash=?", (token_hash(previous_cookie),))
    assert db.one("SELECT * FROM source_grants WHERE user_id=?", (member["id"],))
    assert verify_password(
        "new-secure-password", db.one("SELECT password_hash FROM users WHERE id=?", (member["id"],))["password_hash"]
    )
    assert (
        client.post(
            "/api/auth/login", headers=HEADERS, json={"email": member["email"], "password": "member-long-password"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", headers=HEADERS, json={"email": member["email"], "password": "new-secure-password"}
        ).status_code
        == 200
    )


def test_recovery_codes_are_owner_bound_single_use_expire_and_never_widen_access(client, admin):
    member = create_member(client)
    db = client.app.state.db
    source = client.post(
        "/api/admin/sources", headers=HEADERS, json={"name": "Existing source", "kind": "sqlserver"}
    ).json()
    with db.connect() as c:
        c.execute("INSERT INTO source_grants VALUES(?,?)", (source["id"], member["id"]))
        c.execute("INSERT INTO source_access_policies VALUES(?,?)", (member["id"], source["id"]))
        c.execute(
            "INSERT INTO database_grants VALUES(?,?,?,?,?)",
            (member["id"], source["id"], "Finance", 0, '[{"id":"a","kind":"schema","schema":"A"}]'),
        )
    before = {
        t: db.all("SELECT * FROM " + t)
        for t in ("source_grants", "source_access_policies", "database_grants", "dataset_grants")
    }
    first = client.post(f"/api/admin/users/{member['id']}/password-reset", headers=HEADERS).json()
    second = client.post(f"/api/admin/users/{member['id']}/password-reset", headers=HEADERS).json()
    assert first["token"] != second["token"]
    assert db.one("SELECT token_hash FROM password_resets WHERE user_id=?", (member["id"],))[
        "token_hash"
    ] == token_hash(second["token"])
    admin_cookie = client.cookies.get("duka_session")
    sign_in_member(client)
    assert client.post(f"/api/admin/users/{admin['id']}/password-reset", headers=HEADERS).status_code == 403
    member_cookie = client.cookies.get("duka_session")
    body = {"email": member["email"], "token": first["token"], "password": "recovered-long-password"}
    assert client.post("/api/auth/password-reset", headers=HEADERS, json=body).status_code == 422
    body.update(token=second["token"], email=admin["email"])
    assert client.post("/api/auth/password-reset", headers=HEADERS, json=body).status_code == 422
    body["email"] = member["email"]
    db.execute("UPDATE password_resets SET expires_at=? WHERE user_id=?", (time.time() - 1, member["id"]))
    assert client.post("/api/auth/password-reset", headers=HEADERS, json=body).status_code == 422
    db.execute("UPDATE password_resets SET expires_at=? WHERE user_id=?", (time.time() + 100, member["id"]))
    assert client.post("/api/auth/password-reset", headers=HEADERS, json=body).status_code == 200
    assert client.get("/api/auth/status").json()["user"] is None
    assert not db.one("SELECT * FROM sessions WHERE token_hash=?", (token_hash(member_cookie),))
    assert db.one("SELECT * FROM sessions WHERE token_hash=?", (token_hash(admin_cookie),))
    assert client.post("/api/auth/password-reset", headers=HEADERS, json=body).status_code == 422
    assert (
        client.post(
            "/api/auth/login", headers=HEADERS, json={"email": member["email"], "password": body["password"]}
        ).status_code
        == 200
    )
    assert before == {t: db.all("SELECT * FROM " + t) for t in before}
    # Traffic/audit never retain the raw recovery code or passwords.
    client.portal.call(client.app.state.traffic.flush)
    logs = json.dumps(db.all("SELECT * FROM audit_events")) + json.dumps(db.all("SELECT * FROM traffic_events"))
    assert second["token"] not in logs and body["password"] not in logs


def test_recovery_requires_devs_and_rejects_inactive_members(client, admin):
    member = create_member(client)
    client.patch(f"/api/admin/users/{member['id']}", headers=HEADERS, json={"active": False})
    assert client.post(f"/api/admin/users/{member['id']}/password-reset", headers=HEADERS).status_code == 404
    assert (
        client.post(
            "/api/auth/password-reset",
            headers=HEADERS,
            json={"email": member["email"], "token": "x", "password": "long-recovery-password"},
        ).status_code
        == 422
    )
    client.post("/api/auth/logout", headers=HEADERS)
    assert client.post(f"/api/admin/users/{member['id']}/password-reset", headers=HEADERS).status_code == 401


def test_password_change_retains_both_provider_connections_and_their_chats(client, admin, monkeypatch):
    from test_claude_subscriptions import claude, connect_claude, choose
    from test_excel_reports import subscribe

    claude.__wrapped__(client, monkeypatch)
    subscribe(client)
    connect_claude(client)
    chats = []
    for provider in ("chatgpt", "claude"):
        choose(client, provider)
        chat = client.post("/api/conversations", headers=HEADERS, json={}).json()
        assert (
            client.post(
                f"/api/conversations/{chat['id']}/messages", headers=HEADERS, json={"content": "Keep this chat"}
            ).status_code
            == 200
        )
        chats.append((provider, chat["id"]))
    assert (
        client.post(
            "/api/auth/password",
            headers=HEADERS,
            json={"current_password": "a-long-test-password", "new_password": "new-private-test-password"},
        ).status_code
        == 200
    )
    for provider, cid in chats:
        assert client.get(f"/api/subscription?provider={provider}").json()["connected"]
        choose(client, provider)
        assert (
            client.post(
                f"/api/conversations/{cid}/messages",
                headers=HEADERS,
                json={"content": "Continue after password change"},
            ).status_code
            == 200
        )
        assert len(client.get(f"/api/conversations/{cid}").json()["messages"]) == 4
