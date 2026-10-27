"""Password recovery is local and Devs assisted; recovery tokens are never logged."""

import secrets
import time

from fastapi import Depends, HTTPException, Request, Response
from pydantic import Field, SecretStr

from .schemas import InputModel, Credentials
from .security import admin_user, current_user, create_session, hash_password, password_work, token_hash, verify_password


class PasswordChange(InputModel):
    current_password: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=256)


class PasswordRecovery(Credentials):
    token: SecretStr = Field(min_length=1, max_length=256)


async def revoke_work(state, user_id):
    for chat in state.db.all("SELECT id FROM conversations WHERE user_id=?", (user_id,)):
        await state.chat_jobs.stop(chat["id"])
    await state.stop_user_reports(user_id)
    await state.manager.release(user_id)


def register_accounts(app, settings):
    @app.post("/api/auth/password")
    async def change_password(body: PasswordChange, request: Request, response: Response, user=Depends(current_user)):
        state, db = app.state, app.state.db
        state.limiter.check("password:" + user["id"])
        if not await password_work(state, verify_password, body.current_password.get_secret_value(), user["password_hash"]):
            raise HTTPException(422, "The current password is incorrect.")
        encoded = await password_work(state, hash_password, body.new_password.get_secret_value())
        with db.connect() as c:
            # Compare the current hash within the write transaction: concurrent resets
            # must not be overwritten using a password that has just been revoked.
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT password_hash FROM users WHERE id=? AND active=1", (user["id"],)).fetchone()
            if not row or row["password_hash"] != user["password_hash"]:
                raise HTTPException(422, "The current password is incorrect.")
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, user["id"]))
            c.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
            c.execute("DELETE FROM password_resets WHERE user_id=?", (user["id"],))
        await revoke_work(state, user["id"])
        create_session(db, settings, response, user["id"], expected_hash=encoded)
        db.audit(user["id"], "user.password_changed", user["id"])
        return {"ok": True}

    @app.post("/api/admin/users/{identifier}/password-reset")
    async def issue_reset(identifier: str, request: Request, user=Depends(admin_user)):
        db = app.state.db
        if not db.one("SELECT id FROM users WHERE id=? AND active=1", (identifier,)):
            raise HTTPException(404, "Active member not found.")
        token = secrets.token_urlsafe(32)
        expiry = time.time() + 1800
        db.execute(
            "INSERT INTO password_resets VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET token_hash=excluded.token_hash,expires_at=excluded.expires_at",
            (identifier, token_hash(token), expiry),
        )
        db.audit(user["id"], "user.password_reset_issued", identifier)
        return {"token": token, "expires_at": expiry}

    @app.post("/api/auth/password-reset")
    async def reset_password(body: PasswordRecovery, request: Request):
        state, db = app.state, app.state.db
        state.limiter.check("recovery:ip:" + request.client.host, "recovery:account:" + body.email)
        if len(body.password) < 12:
            raise HTTPException(422, "Use a password with at least 12 characters.")
        encoded = await password_work(state, hash_password, body.password)
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT u.id FROM users u JOIN password_resets p ON p.user_id=u.id WHERE u.email=? AND u.active=1 AND p.token_hash=? AND p.expires_at>?",
                (body.email, token_hash(body.token.get_secret_value()), time.time()),
            ).fetchone()
            if not row:
                raise HTTPException(422, "The recovery code is invalid or expired.")
            identifier = row["id"]
            c.execute("UPDATE users SET password_hash=? WHERE id=?", (encoded, identifier))
            c.execute("DELETE FROM password_resets WHERE user_id=?", (identifier,))
            c.execute("DELETE FROM sessions WHERE user_id=?", (identifier,))
        await revoke_work(state, identifier)
        db.audit(identifier, "user.password_reset", identifier)
        return {"ok": True}
