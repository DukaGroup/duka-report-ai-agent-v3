"""Devs-only management of shared native subscription connections."""

import asyncio
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import Field, field_validator

from .db import now, uid
from .schemas import InputModel, SubscriptionLoginCode
from .security import admin_user


class NewSubscription(InputModel):
    provider: Literal["chatgpt", "claude"]
    label: str = Field(min_length=1, max_length=100)

    @field_validator("label")
    @classmethod
    def clean_label(cls, value):
        if not value.strip():
            raise ValueError("Enter a subscription label.")
        return value.strip()


class AccountOrder(InputModel):
    provider: Literal["chatgpt", "claude"]
    account_ids: list[str] = Field(min_length=1, max_length=1000)


class EditSubscription(InputModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    enabled: bool | None = None
    position: int | None = Field(default=None, ge=0, le=10000)


def register_subscriptions(app):
    async def invalidate(identifier, account):
        manager = app.state.manager
        async with manager.worker_lock:
            idle = [
                key
                for key, runtime in manager.workers.items()
                if getattr(runtime, "account_record", None)
                and runtime.account_record["id"] == identifier
                and key not in manager.worker_leases
            ]
            for key in idle:
                await manager.workers.pop(key).close()
        with app.state.db.connect() as c:
            c.execute(
                "UPDATE conversations SET provider_thread_id=NULL WHERE provider_thread_id IN (SELECT thread_id FROM subscription_thread_accounts WHERE account_id=?)",
                (identifier,),
            )
            c.execute(
                "DELETE FROM conversation_provider_threads WHERE thread_id IN (SELECT thread_id FROM subscription_thread_accounts WHERE account_id=?)",
                (identifier,),
            )
            if identifier.startswith("legacy-"):
                condition = (
                    "model LIKE 'claude:%'"
                    if account["provider"] == "claude"
                    else "(model IS NULL OR model NOT LIKE 'claude:%')"
                )
                c.execute(
                    "UPDATE conversations SET provider_thread_id=NULL WHERE provider_thread_id NOT IN (SELECT thread_id FROM subscription_thread_accounts) AND "
                    + condition
                )
                c.execute(
                    "DELETE FROM conversation_provider_threads WHERE provider=? AND thread_id NOT IN (SELECT thread_id FROM subscription_thread_accounts)",
                    (account["provider"],),
                )

    @asynccontextmanager
    async def changing(identifier):
        manager = app.state.manager
        account = manager.pool.get(identifier)
        async with manager.worker_lock:
            if identifier in manager.account_changes or any(
                getattr(manager.workers.get(k), "account_record", None)
                and manager.workers[k].account_record["id"] == identifier
                for k in manager.worker_leases
            ):
                raise HTTPException(409, "Stop responses using this subscription before changing it.")
            manager.account_changes.add(identifier)
        try:
            yield account
        finally:
            manager.account_changes.discard(identifier)

    @app.get("/api/admin/subscriptions")
    async def accounts(user=Depends(admin_user)):
        pool = app.state.manager.pool
        semaphore = asyncio.Semaphore(4)

        async def status(account):
            async with semaphore:
                try:
                    result = await pool.control(account).account()
                except Exception:
                    result = {"connected": False, "error": "Subscription status could not be read."}
                return {
                    key: account[key]
                    for key in ("id", "provider", "label", "position", "enabled", "unavailable_reason", "retry_at")
                } | result

        return await asyncio.gather(*(status(a) for a in pool.accounts()))

    @app.post("/api/admin/subscriptions", status_code=201)
    async def add(body: NewSubscription, user=Depends(admin_user)):
        pool = app.state.manager.pool
        existing = pool.accounts(body.provider)
        identifier = uid()
        app.state.db.execute(
            "INSERT INTO subscription_accounts(id,provider,label,credential_key,position,created_at) VALUES(?,?,?,?,?,?)",
            (
                identifier,
                body.provider,
                body.label.strip(),
                "accounts/" + identifier,
                max((a["position"] for a in existing), default=-1) + 1,
                now(),
            ),
        )
        app.state.db.audit(user["id"], "subscription.added", identifier, {"provider": body.provider})
        return {"id": identifier, "provider": body.provider, "label": body.label.strip()}

    @app.patch("/api/admin/subscriptions/{identifier}")
    async def edit(identifier: str, body: EditSubscription, user=Depends(admin_user)):
        async with changing(identifier):
            for name, value in body.model_dump(exclude_none=True).items():
                app.state.db.execute(
                    f"UPDATE subscription_accounts SET {name}=? WHERE id=?",
                    (value.strip() if name == "label" else value, identifier),
                )
        app.state.db.audit(user["id"], "subscription.updated", identifier)
        return {"ok": True}

    @app.post("/api/admin/subscription-order")
    async def order(body: AccountOrder, user=Depends(admin_user)):
        manager = app.state.manager
        async with manager.worker_lock:
            accounts = manager.pool.accounts(body.provider)
            if len(body.account_ids) != len(set(body.account_ids)) or set(body.account_ids) != {
                a["id"] for a in accounts
            }:
                raise HTTPException(422, "Include each subscription for this provider exactly once.")
            with app.state.db.connect() as c:
                c.executemany("UPDATE subscription_accounts SET position=? WHERE id=?", enumerate(body.account_ids))
        app.state.db.audit(user["id"], "subscription.reordered", body.provider)
        return {"ok": True}

    @app.post("/api/admin/subscriptions/{identifier}/retry")
    async def retry(identifier: str, user=Depends(admin_user)):
        async with changing(identifier):
            app.state.manager.pool.reset(identifier)
        app.state.db.audit(user["id"], "subscription.retry_enabled", identifier)
        return {"ok": True}

    @app.post("/api/admin/subscriptions/{identifier}/login")
    async def login(identifier: str, user=Depends(admin_user)):
        async with changing(identifier) as account:
            await invalidate(identifier, account)
            result = await app.state.manager.pool.control(account).begin_login()
            app.state.manager.pool.reset(identifier)
        app.state.db.audit(user["id"], "subscription.login_started", identifier)
        return {**result, "provider": account["provider"], "subscription_id": identifier}

    @app.post("/api/admin/subscriptions/{identifier}/login/code")
    async def code(identifier: str, body: SubscriptionLoginCode, user=Depends(admin_user)):
        account = app.state.manager.pool.get(identifier)
        if account["provider"] != "claude":
            raise HTTPException(422, "Only Claude uses a pasted authorization code.")
        return await app.state.manager.pool.control(account).finish_login(body.login_id, body.code.get_secret_value())

    @app.post("/api/admin/subscriptions/{identifier}/disconnect")
    async def disconnect(identifier: str, user=Depends(admin_user)):
        async with changing(identifier) as account:
            await app.state.manager.pool.control(account).logout()
            app.state.manager.pool.reset(identifier)
            # Old native IDs remain associated with the old credential home.
            # Clear only this account's contexts, retaining all local messages.
            await invalidate(identifier, account)
        app.state.db.audit(user["id"], "subscription.disconnected", identifier)
        return {"ok": True}
