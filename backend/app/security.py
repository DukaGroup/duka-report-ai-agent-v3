import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Response

COOKIE = "duka_session"


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f"scrypt${salt}${key.hex()}"


def verify_password(password, encoded):
    try:
        kind, salt, expected = encoded.split("$")
        if kind != "scrypt":
            return False
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(key.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(user):
    return {key: user[key] for key in ("id", "email", "name", "role", "active", "created_at")}


def create_session(db, settings, response: Response, user_id):
    token = secrets.token_urlsafe(32)
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
    db.execute(
        "INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user_id, time.time() + settings.session_hours * 3600)
    )
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="strict",
        max_age=settings.session_hours * 3600,
        path="/",
    )


def current_user(request: Request):
    token = request.cookies.get(COOKIE, "")
    user = request.app.state.db.one(
        "SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
        (token_hash(token), time.time()),
    )
    if not user:
        raise HTTPException(401, "Sign in to your workspace first.")
    return user


def admin_user(request: Request):
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access is required.")
    return user


class LoginLimiter:
    def __init__(self):
        self.attempts = defaultdict(deque)

    def check(self, key):
        current = time.monotonic()
        # Keep the unauthenticated limiter bounded even with changing remote addresses.
        if len(self.attempts) > 10000:
            self.attempts.clear()
        bucket = self.attempts[key]
        while bucket and bucket[0] < current - 300:
            bucket.popleft()
        if len(bucket) >= 10:
            raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.")
        bucket.append(current)
