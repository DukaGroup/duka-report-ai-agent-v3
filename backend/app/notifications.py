"""Owner-scoped Web Push delivery independent of open pages and AI providers."""

import asyncio
import base64
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, HTTPException, Request
from pydantic import Field, SecretStr, field_validator

from .db import now
from .completion import REPORTS_READY, REPORT_COUNT, COMPLETED_AT
from .schemas import InputModel
from .security import COOKIE, current_user, token_hash


def endpoint_hash(endpoint):
    return hashlib.sha256(endpoint.encode()).hexdigest()


def valid_endpoint(endpoint):
    try:
        url = urlsplit(endpoint)
        host = url.hostname or ""
        allowed = host in (
            "fcm.googleapis.com",
            "web.push.apple.com",
            "updates.push.services.mozilla.com",
        ) or host.endswith((".push.services.mozilla.com", ".notify.windows.com", ".push.apple.com"))
        if not (
            url.scheme == "https"
            and allowed
            and url.port in (None, 443)
            and not url.username
            and not url.password
            and not url.fragment
            and url.path
        ):
            raise ValueError()
    except ValueError:
        raise ValueError("Unsupported browser push endpoint.") from None
    return endpoint


def decode_key(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class PushKeys(InputModel):
    p256dh: SecretStr = Field(min_length=80, max_length=128)
    auth: SecretStr = Field(min_length=20, max_length=32)


class PushSubscription(InputModel):
    endpoint: SecretStr = Field(min_length=20, max_length=4096)
    expirationTime: float | None = None
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def endpoint_valid(cls, value):
        valid_endpoint(value.get_secret_value())
        return value


class PushRemoval(InputModel):
    endpoint: SecretStr = Field(min_length=20, max_length=4096)


class PushNotifications:
    def __init__(self, settings, db):
        self.db = db
        self.key_path = settings.data_dir / "web-push-private.pem"
        self.subject = next(
            (o for o in settings.allowed_origins if o.startswith("https://")), "mailto:notifications@localhost"
        )
        self.task = None
        self.wake = asyncio.Event()

    def public_key(self):
        if not self.key_path.exists():
            if self.db.one("SELECT endpoint_hash FROM web_push_subscriptions LIMIT 1"):
                raise OSError("Restore the original Web Push key from the private data backup.")
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
            )
            try:
                fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as output:
                    output.write(pem)
            except FileExistsError:
                pass
        key = serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)
        public = key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return base64.urlsafe_b64encode(public).rstrip(b"=").decode()

    def enqueue(self, message_id=None):
        # Recover a crash between saving a completed reply and queuing its alert.
        cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with self.db.connect() as c:
            c.execute(
                "INSERT OR IGNORE INTO web_push_deliveries(message_id,endpoint_hash,status,attempts,next_attempt) "
                "SELECT r.id,p.endpoint_hash,'queued',0,0 FROM chat_runs r "
                "JOIN messages m ON m.id=r.id JOIN conversations v ON v.id=r.conversation_id "
                "JOIN web_push_subscriptions p ON p.user_id=r.user_id JOIN sessions s ON s.token_hash=p.session_hash "
                "JOIN users u ON u.id=r.user_id "
                "WHERE r.status='completed' AND m.status='completed' AND u.active=1 AND s.expires_at>? "
                f"AND p.created_at<={COMPLETED_AT} AND {COMPLETED_AT}>? AND (? IS NULL OR r.id=?) "
                f"AND {REPORTS_READY}",
                (time.time(), cutoff, message_id, message_id),
            )
        self.wake.set()

    def start(self):
        self.enqueue()
        self.task = asyncio.create_task(self._worker())

    def send(self, subscription, payload):
        from pywebpush import webpush

        # Only encrypted, generic notification data goes through browser push services.
        return webpush(
            subscription_info=subscription,
            data=json.dumps(payload),
            vapid_private_key=str(self.key_path),
            vapid_claims={"sub": self.subject},
            ttl=3600,
            timeout=8,
        )

    async def deliver(self):
        rows = self.db.all(
            "SELECT d.*,p.subscription_json,p.user_id,m.conversation_id FROM web_push_deliveries d "
            "JOIN web_push_subscriptions p ON p.endpoint_hash=d.endpoint_hash "
            "JOIN sessions s ON s.token_hash=p.session_hash JOIN users u ON u.id=p.user_id "
            "JOIN messages m ON m.id=d.message_id JOIN conversations v ON v.id=m.conversation_id "
            "WHERE d.status='queued' AND d.next_attempt<=? AND s.expires_at>? AND u.active=1 "
            f"AND m.status='completed' AND v.user_id=p.user_id AND {REPORTS_READY} LIMIT 20",
            (time.time(), time.time()),
        )
        for row in rows:
            subscription = json.loads(row["subscription_json"])
            payload = {
                "type": "reply-completed",
                "userId": row["user_id"],
                "conversationId": row["conversation_id"],
                "messageId": row["message_id"],
            }
            try:
                valid_endpoint(subscription["endpoint"])
                await asyncio.to_thread(self.send, subscription, payload)
                self.db.execute(
                    "UPDATE web_push_deliveries SET status='sent' WHERE message_id=? AND endpoint_hash=?",
                    (row["message_id"], row["endpoint_hash"]),
                )
            except Exception as exc:
                code = getattr(exc, "status_code", None)
                if code is None and getattr(exc, "response", None) is not None:
                    code = exc.response.status_code
                if code in (404, 410):
                    self.db.execute("DELETE FROM web_push_subscriptions WHERE endpoint_hash=?", (row["endpoint_hash"],))
                else:
                    attempts = row["attempts"] + 1
                    self.db.execute(
                        "UPDATE web_push_deliveries SET attempts=?,next_attempt=?,status=? WHERE message_id=? AND endpoint_hash=?",
                        (
                            attempts,
                            time.time() + min(600, 5 * 4**attempts),
                            "failed" if attempts >= 5 else "queued",
                            row["message_id"],
                            row["endpoint_hash"],
                        ),
                    )
                # Never log subscription endpoints, encryption keys or push-service responses.

    async def _worker(self):
        while True:
            self.wake.clear()
            try:
                await self.deliver()
                await asyncio.wait_for(self.wake.wait(), timeout=5)
            except TimeoutError:
                pass
            except Exception:
                await asyncio.sleep(5)

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


def register_notifications(app):
    @app.get("/api/notifications/config")
    async def config(request: Request, user=Depends(current_user)):
        try:
            key = request.app.state.notifications.public_key()
        except (OSError, ValueError):
            raise HTTPException(503, "Njoftimet e pajisjes nuk janë të disponueshme.") from None
        return {"public_key": key}

    @app.post("/api/notifications/subscriptions")
    async def subscribe(body: PushSubscription, request: Request, user=Depends(current_user)):
        endpoint = body.endpoint.get_secret_value()
        keys = {"p256dh": body.keys.p256dh.get_secret_value(), "auth": body.keys.auth.get_secret_value()}
        try:
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode_key(keys["p256dh"]))
            if len(decode_key(keys["auth"])) != 16:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "Çelësat e njoftimeve nuk janë të vlefshëm.") from None
        db = request.app.state.db
        identifier = endpoint_hash(endpoint)
        with db.connect() as c:
            count = c.execute(
                "SELECT count(*) FROM web_push_subscriptions WHERE user_id=? AND endpoint_hash<>?",
                (user["id"], identifier),
            ).fetchone()[0]
            if count >= 10:
                raise HTTPException(409, "Janë aktivizuar njoftimet në shumë pajisje.")
            c.execute(
                "INSERT INTO web_push_subscriptions VALUES(?,?,?,?,?) ON CONFLICT(endpoint_hash) DO UPDATE SET "
                "user_id=excluded.user_id,session_hash=excluded.session_hash,subscription_json=excluded.subscription_json,created_at=excluded.created_at",
                (
                    identifier,
                    user["id"],
                    token_hash(request.cookies.get(COOKIE, "")),
                    json.dumps({"endpoint": endpoint, "keys": keys}),
                    now(),
                ),
            )
        return {"enabled": True}

    @app.delete("/api/notifications/subscriptions")
    async def unsubscribe(body: PushRemoval, request: Request, user=Depends(current_user)):
        request.app.state.db.execute(
            "DELETE FROM web_push_subscriptions WHERE endpoint_hash=? AND user_id=? AND session_hash=?",
            (endpoint_hash(body.endpoint.get_secret_value()), user["id"], token_hash(request.cookies.get(COOKIE, ""))),
        )
        return {"enabled": False}

    @app.get("/api/notifications/messages/{message_id}")
    async def check(message_id: str, request: Request, user=Depends(current_user)):
        row = request.app.state.db.one(
            f"SELECT m.id,m.conversation_id,{REPORT_COUNT} AS report_count FROM messages m JOIN conversations c ON c.id=m.conversation_id "
            f"WHERE m.id=? AND m.role='assistant' AND m.status='completed' AND c.user_id=? AND {REPORTS_READY}",
            (message_id, user["id"]),
        )
        if not row:
            raise HTTPException(404, "Përgjigjja nuk është e disponueshme.")
        result = {"userId": user["id"], "conversationId": row["conversation_id"], "messageId": row["id"]}
        if row["report_count"]:
            result["reportCount"] = row["report_count"]
        return result
