import asyncio
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request, Response

COOKIE = "duka_session"
PASSWORD_SCHEME = "scrypt-v2"


async def password_work(state, function, *args):
    # Queue no more than two expensive KDF operations. A disconnected request
    # retains its slot until the actual thread ends, even after cancellation.
    slots = state.password_slots
    if slots.locked():
        raise HTTPException(429, "Authentication is busy. Try again shortly.", headers={"Retry-After": "1"})
    await slots.acquire()
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    task.add_done_callback(lambda completed: slots.release())
    return await asyncio.shield(task)


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    # OWASP's 16 MiB configuration: N=2^14, r=8, p=5. Keep memory bounded
    # while increasing CPU cost over the legacy p=1 hashes.
    key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=5)
    return f"{PASSWORD_SCHEME}${salt}${key.hex()}"


def verify_password(password, encoded):
    try:
        kind, salt, expected = encoded.split("$")
        if kind not in ("scrypt", PASSWORD_SCHEME):
            return False
        key = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8,
                             p=1 if kind == "scrypt" else 5)
        if kind == "scrypt":
            # Match the new verification work even for an incorrect legacy
            # password; otherwise timing could identify unmigrated accounts.
            hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=4)
        return hmac.compare_digest(key.hex(), expected)
    except (ValueError, TypeError, AttributeError, UnicodeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def public_user(user):
    return {key: user[key] for key in ("id", "email", "name", "role", "active", "created_at")}


def with_introduction(db, user):
    seen = db.one("SELECT 1 FROM user_introductions WHERE user_id=?", (user["id"],))
    return {**user, "intro_pending": not seen}


def create_session(db, settings, response: Response, user_id, expected_hash=None):
    token = secrets.token_urlsafe(32)
    with db.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        user = c.execute("SELECT password_hash FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
        if not user or (expected_hash is not None and user["password_hash"] != expected_hash):
            raise HTTPException(401, "Account credentials changed. Sign in again.")
        c.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
        c.execute("INSERT INTO sessions VALUES(?,?,?)",
                  (token_hash(token), user_id, time.time() + settings.session_hours * 3600))
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
    request.state.traffic_user_id = user["id"]
    return user


def admin_user(request: Request):
    user = current_user(request)
    if user["role"] != "devs":
        raise HTTPException(403, "Administrator access is required.")
    return user


def member_administrator(request: Request):
    user = current_user(request)
    if user["role"] not in ("devs", "president"):
        raise HTTPException(403, "Devs or President access is required to manage members.")
    return user


class LoginLimiter:
    """Atomic, persistent budgets shared by workers, with no stored emails/IPs.

    Count every accepted attempt, including successes. Blocked attempts do not
    extend the five-minute window. Capacity exhaustion fails closed without
    erasing other accounts' budgets.
    """
    limit = 10
    window = 300
    capacity = 10000

    def __init__(self, db):
        self.db = db

    def check(self, *keys):
        keys = list(dict.fromkeys(token_hash(key) for key in keys))
        current = time.time()
        retry = 0
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM auth_attempts WHERE expires_at<=?", (current,))
            rows = {key: c.execute("SELECT attempts,expires_at FROM auth_attempts WHERE key_hash=?", (key,)).fetchone()
                    for key in keys}
            retry = max((max(1, int(row["expires_at"] - current) + 1)
                         for row in rows.values() if row and row["attempts"] >= self.limit), default=0)
            if not retry and (c.execute("SELECT count(*) FROM auth_attempts").fetchone()[0]
                              + sum(row is None for row in rows.values()) > self.capacity):
                retry = self.window
            if not retry:
                for key in keys:
                    c.execute("INSERT INTO auth_attempts VALUES(?,?,?) ON CONFLICT(key_hash) DO UPDATE SET attempts=attempts+1",
                              (key, 1, current + self.window))
        if retry:
            raise HTTPException(429, "Too many sign-in attempts. Try again in five minutes.",
                                headers={"Retry-After": str(retry)})


class AuthBodyLimitMiddleware:
    """Bound auth JSON before parsing, including chunked bodies and false lengths."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST" or not scope["path"].startswith("/api/auth/"):
            return await self.app(scope, receive, send)
        messages, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 16384 or len(messages) >= 1024:
                from fastapi.responses import JSONResponse
                return await JSONResponse({"detail": "Authentication request is too large."}, status_code=413)(scope, receive, send)
            messages.append(message)
            if not message.get("more_body", False):
                break
        iterator = iter(messages)

        async def replay():
            return next(iterator, None) or await receive()

        await self.app(scope, replay, send)
