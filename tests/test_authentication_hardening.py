"""Adversarial authentication checks; all accounts, tokens and keys are fixtures."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import threading
import time
from types import SimpleNamespace

from fastapi import HTTPException, Response
import pytest

from app.config import Settings
from app.db import Database
from app.deployment_security import bootstrap_token, verify_bootstrap
from app.schemas import Credentials
from app.security import LoginLimiter, create_session, password_work, token_hash, verify_password
from conftest import HEADERS
from test_application import create_member
from test_deployment_security import production_settings
from app.main import create_app
from fastapi.testclient import TestClient


def limiter_db(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.initialize()
    return db


def test_limits_survive_reconstruction_and_do_not_store_account_or_ip(tmp_path):
    db = limiter_db(tmp_path)
    for _ in range(10):
        LoginLimiter(db).check("login:account:private@example.test", "login:ip:192.0.2.1")
    with pytest.raises(HTTPException) as error:
        LoginLimiter(db).check("login:account:private@example.test", "login:ip:192.0.2.2")
    assert error.value.status_code == 429
    assert 1 <= int(error.value.headers["Retry-After"]) <= 300
    stored = json.dumps(db.all("SELECT * FROM auth_attempts"))
    assert "private@example.test" not in stored and "192.0.2." not in stored
    assert len(db.all("SELECT * FROM auth_attempts")) == 2


def test_rate_limit_expires_and_blocked_requests_do_not_extend_it(tmp_path, monkeypatch):
    db = limiter_db(tmp_path)
    monkeypatch.setattr("app.security.time.time", lambda: 1000)
    limiter = LoginLimiter(db)
    for _ in range(10):
        limiter.check("fixture")
    monkeypatch.setattr("app.security.time.time", lambda: 1299)
    with pytest.raises(HTTPException):
        limiter.check("fixture")
    assert db.one("SELECT expires_at FROM auth_attempts")["expires_at"] == 1300
    monkeypatch.setattr("app.security.time.time", lambda: 1300)
    limiter.check("fixture")
    assert db.one("SELECT attempts FROM auth_attempts")["attempts"] == 1


def test_limiter_capacity_does_not_erase_existing_limits(tmp_path):
    db = limiter_db(tmp_path)
    limiter = LoginLimiter(db)
    limiter.capacity = 2
    for _ in range(10):
        limiter.check("protected")
    limiter.check("other")
    for key in ("overflow", "protected"):
        with pytest.raises(HTTPException) as error:
            limiter.check(key)
        assert error.value.status_code == 429
    assert len(db.all("SELECT * FROM auth_attempts")) == 2
    assert db.one("SELECT attempts FROM auth_attempts WHERE key_hash=?", (token_hash("protected"),))["attempts"] == 10


def test_concurrent_workers_cannot_overrun_the_shared_budget(tmp_path):
    db = limiter_db(tmp_path)

    def attempt(_):
        try:
            LoginLimiter(db).check("same-account")
            return True
        except HTTPException as error:
            assert error.status_code == 429
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(30))) == 10
    assert db.one("SELECT attempts FROM auth_attempts")["attempts"] == 10


def test_changing_ips_and_email_case_cannot_bypass_account_budget(client, admin):
    state = client.app.state
    for index in range(10):
        state.limiter.check("login:account:" + admin["email"], "login:ip:192.0.2." + str(index))
    result = client.post("/api/auth/login", headers=HEADERS,
                         json={"email": "  ADMIN@EXAMPLE.COM ", "password": "a-long-test-password"})
    assert result.status_code == 429 and "Retry-After" in result.headers
    assert client.get("/api/auth/status").json()["user"]["id"] == admin["id"]


def test_ip_budget_also_limits_guesses_against_many_accounts(client, admin):
    for index in range(10):
        response = client.post("/api/auth/login", headers=HEADERS,
                               json={"email": f"missing{index}@example.test", "password": "wrong"})
        assert response.status_code == 401
    assert client.post("/api/auth/login", headers=HEADERS,
                       json={"email": admin["email"], "password": "a-long-test-password"}).status_code == 429


def test_recovery_has_an_independent_account_budget(client, admin):
    for index in range(10):
        client.app.state.limiter.check("recovery:account:" + admin["email"], "recovery:ip:" + str(index))
    assert client.post("/api/auth/password-reset", headers=HEADERS, json={
        "email": admin["email"], "password": "recovered-password", "token": "unknown",
    }).status_code == 429
    assert client.post("/api/auth/login", headers=HEADERS, json={
        "email": admin["email"], "password": "a-long-test-password",
    }).status_code == 200


def test_unicode_setup_tokens_fail_as_auth_errors_not_server_errors(tmp_path):
    settings = production_settings(tmp_path)
    with TestClient(create_app(settings), base_url=settings.allowed_origins[0]) as client:
        token = bootstrap_token(settings)
        assert not verify_bootstrap(settings, "ë" * 43)
        result = client.post("/api/auth/setup", headers={"X-Duka-Request": "1", "Origin": settings.allowed_origins[0]},
                             json={"email": "owner@example.test", "name": "Owner", "password": "long-test-password",
                                   "setup_token": "ë" * 43})
        assert result.status_code == 403 and token not in result.text
        assert client.app.state.db.one("SELECT count(*) AS n FROM users")["n"] == 0


@pytest.mark.parametrize("field", ["email", "password"])
def test_invalid_unicode_auth_fields_are_rejected_without_echoing_values(client, field):
    body = {"email": "private@example.test", "password": "private-password"}
    body[field] = "\ud800"
    result = client.post("/api/auth/login", headers={**HEADERS, "Content-Type": "application/json"},
                         content=json.dumps(body).encode())
    assert result.status_code == 422 and "private-password" not in result.text
    assert not verify_password("\ud800", "scrypt-v2$" + "01" * 16 + "$00")


@pytest.mark.parametrize("path", ["login", "setup", "password-reset", "password"])
def test_auth_body_size_is_bounded_before_json_parsing(client, path):
    response = client.post("/api/auth/" + path, headers={**HEADERS, "Content-Type": "application/json"},
                           content=b'{"padding":"' + b"x" * 17000 + b'"}')
    assert response.status_code == 413
    assert response.headers["Cache-Control"] == "no-store"


def test_auth_body_limit_counts_streamed_bytes(client):
    response = client.post("/api/auth/login", headers={**HEADERS, "Content-Type": "application/json"},
                           content=iter([b"x" * 9000, b"x" * 9000]))
    assert response.status_code == 413


def test_deactivation_destroys_recovery_codes_even_after_reactivation(client, admin):
    member = create_member(client)
    token = client.post(f"/api/admin/users/{member['id']}/password-reset", headers=HEADERS).json()["token"]
    assert client.patch(f"/api/admin/users/{member['id']}", headers=HEADERS, json={"active": False}).status_code == 200
    assert not client.app.state.db.one("SELECT * FROM password_resets WHERE user_id=?", (member["id"],))
    assert client.patch(f"/api/admin/users/{member['id']}", headers=HEADERS, json={"active": True}).status_code == 200
    assert client.post("/api/auth/password-reset", headers=HEADERS, json={
        "email": member["email"], "token": token, "password": "new-private-password",
    }).status_code == 422


@pytest.mark.parametrize("change", ["disable", "replace_password"])
def test_password_change_cannot_recreate_session_after_concurrent_revocation(client, admin, monkeypatch, change):
    async def revoke_during_cleanup(state, identifier):
        if change == "disable":
            state.db.execute("UPDATE users SET active=0 WHERE id=?", (identifier,))
        else:
            state.db.execute("UPDATE users SET password_hash='newer-verifier' WHERE id=?", (identifier,))

    monkeypatch.setattr("app.accounts.revoke_work", revoke_during_cleanup)
    result = client.post("/api/auth/password", headers=HEADERS, json={
        "current_password": "a-long-test-password", "new_password": "new-private-password",
    })
    assert result.status_code == 401 and "set-cookie" not in result.headers
    assert not client.app.state.db.one("SELECT * FROM sessions WHERE user_id=?", (admin["id"],))


def test_session_creation_requires_current_credentials(client, admin):
    db, settings = client.app.state.db, client.app.state.settings
    before = db.all("SELECT * FROM sessions")
    with pytest.raises(HTTPException) as error:
        create_session(db, settings, Response(), admin["id"], expected_hash="old-verifier")
    assert error.value.status_code == 401 and db.all("SELECT * FROM sessions") == before


def test_session_tokens_are_hashed_expire_and_logout_is_session_scoped(client, admin):
    db = client.app.state.db
    first = client.cookies.get("duka_session")
    result = client.post("/api/auth/login", headers=HEADERS,
                         json={"email": admin["email"], "password": "a-long-test-password"})
    assert result.status_code == 200
    second = client.cookies.get("duka_session")
    assert first != second
    assert "SameSite=strict" in result.headers["set-cookie"] and "HttpOnly" in result.headers["set-cookie"]
    assert first not in json.dumps(db.all("SELECT * FROM sessions"))
    assert client.post("/api/auth/logout", headers=HEADERS).status_code == 200
    client.cookies.set("duka_session", second)
    assert client.get("/api/conversations").status_code == 401
    client.cookies.set("duka_session", first)
    assert client.get("/api/conversations").status_code == 200
    db.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
    assert client.get("/api/conversations").status_code == 401
    client.cookies.set("duka_session", "forged-token")
    assert client.get("/api/conversations").status_code == 401


@pytest.mark.parametrize("hours", [0, -1, 169])
def test_unsafe_session_lifetimes_fail_before_creating_storage(tmp_path, hours):
    settings = replace(Settings(), data_dir=tmp_path / "data", env_file=None, session_hours=hours)
    with pytest.raises(ValueError, match="SESSION_HOURS"):
        settings.prepare()
    assert not settings.data_dir.exists()


async def test_cancelled_password_work_keeps_slot_until_worker_ends():
    state = SimpleNamespace(password_slots=asyncio.Semaphore(1))
    started, finish = threading.Event(), threading.Event()

    def expensive():
        started.set()
        assert finish.wait(5)

    task = asyncio.create_task(password_work(state, expensive))
    try:
        for _ in range(100):
            if started.is_set():
                break
            await asyncio.sleep(0.01)
        assert started.is_set()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(HTTPException) as error:
            await password_work(state, lambda: None)
        assert error.value.status_code == 429
    finally:
        finish.set()
    for _ in range(100):
        if not state.password_slots.locked():
            break
        await asyncio.sleep(0.01)
    assert await password_work(state, lambda: "complete") == "complete"


def test_passwords_preserve_full_unicode_and_are_not_truncated():
    from app.security import hash_password
    password = "ë🔐" * 50
    assert Credentials(email="TEST@example.test", password=password).email == "test@example.test"
    encoded = hash_password(password)
    assert verify_password(password, encoded)
    assert not verify_password(password[:-1], encoded)
