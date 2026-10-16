"""Bounded admin traffic with redacted payload previews and no auth material."""

import asyncio
import contextlib
import json
import re
import time
from collections import deque

from .db import now, uid

DIRECTIONS = (
    "frontend-backend", "backend-frontend", "backend-model", "model-backend",
    "backend-database", "database-backend", "backend-excel", "excel-backend",
)


class TrafficLog:
    def __init__(self, db, capacity=10000):
        self.db, self.capacity = db, capacity
        self.pending = deque(maxlen=capacity)
        self.lock = asyncio.Lock()
        self.task = None
        self.secrets = set()
        self.requests = {}

    def protect_settings(self, settings):
        for prefix in ("sqlserver_", "hana_"):
            for key in ("host", "user", "password"):
                value = getattr(settings, prefix+key, "")
                if value:
                    self.secrets.add(str(value))

    def redact_text(self, value):
        for secret in sorted(self.secrets, key=len, reverse=True):
            if value == secret:
                return "[REDACTED]"
            if len(secret) >= 4:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?im)\b(?:[A-Z0-9_]*SQLSERVER_|[A-Z0-9_]*HANA_)[A-Z_]+\s*=.*$", "[REDACTED CONNECTION SETTING]", value)
        value = re.sub(r'(?i)([\"\']?(?:password|passwd|access_token|refresh_token|id_token|authorization|cookie|api_key|client_secret)[\"\']?\s*[:=]\s*)(?:\"[^\"]*(?:\"|$)|\'[^\']*(?:\'|$)|[^,\s}]+)', r'\1[REDACTED]', value)
        value = re.sub(r'(?i)Bearer\s+[A-Za-z0-9._~+/-]+=*|\bsk-[A-Za-z0-9_-]+|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]', value)
        value = re.sub(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----.*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|$)', '[REDACTED PRIVATE KEY]', value, flags=re.S)
        return value

    def payload(self, value, truncated=False):
        cut = [truncated]
        def safe(value, depth=0):
            if depth > 14:
                cut[0] = True
                return '[DEPTH LIMIT]'
            if isinstance(value, dict):
                result = {}
                for index,(key,item) in enumerate(value.items()):
                    if index >= 100:
                        cut[0] = True
                        break
                    name = re.sub(r'[^a-z0-9]', '', str(key).lower())
                    blocked = (any(word in name for word in ('password','passwd','token','secret','authorization','cookie','apikey','authurl','verificationuri','verificationurl','usercode','devicecode','credential'))
                               or name.startswith(('sqlserver','hana','dukaconnection')) or name in ('headers','connectionstring'))
                    result[self.redact_text(str(key))[:200]] = '[REDACTED]' if blocked else safe(item, depth+1)
                return result
            if isinstance(value, (list,tuple)):
                if len(value) > 100:
                    cut[0] = True
                return [safe(item,depth+1) for item in value[:100]]
            if isinstance(value, str):
                # Tool results and model prompts often contain embedded JSON.
                if value.lstrip().startswith(('{','[')) and len(value) <= 262144:
                    try:
                        return safe(json.loads(value), depth+1)
                    except (ValueError,TypeError):
                        pass
                value = self.redact_text(value)
                if len(value) > 20000:
                    cut[0] = True
                    value = value[:20000]
                return value
            if value is None or isinstance(value,(int,float,bool)):
                return value
            return self.redact_text(str(value))
        encoded = json.dumps(safe(value), ensure_ascii=False, default=str)
        if len(encoded.encode()) > 65536:
            cut[0] = True
            preview = encoded[:30000]
            encoded = json.dumps({'preview':preview},ensure_ascii=False)
            while len(encoded.encode()) > 65536:
                preview = preview[:len(preview)//2]
                encoded = json.dumps({'preview':preview},ensure_ascii=False)
        return encoded, cut[0]

    def record(self, direction, action, status, *, correlation_id=None, user_id=None, size=0, duration_ms=None, detail=None, payload=None, truncated=False):
        body,cut = self.payload(payload,truncated) if payload is not None else (None,False)
        metadata,_ = self.payload(detail or {})
        self.pending.append((now(), direction, self.redact_text(action)[:160], status, self.redact_text(correlation_id) if correlation_id else None, user_id,
                             max(0, size), duration_ms, metadata,body,int(cut)))

    def protocol(self, direction, message, size, scope, user_id):
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        method = message.get("method") or "rpc/response"
        key = (user_id,scope,message.get('id'))
        original = method
        if direction == 'backend-model' and message.get('method') and 'id' in message:
            if len(self.requests) >= 2048:
                self.requests.pop(next(iter(self.requests)))
            self.requests[key] = method
        elif direction == 'model-backend' and not message.get('method'):
            original = self.requests.pop(key,method)
        detail = {"worker": scope or "subscription", "request_id": message.get("id"),
                  "thread_id": params.get("threadId"), "turn_id": params.get("turnId"), "request_method":original}
        if isinstance(params.get("delta"), str):
            detail["text_characters"] = len(params["delta"])
        if method == "item/tool/call":
            detail["tool"] = params.get("tool")
        if "error" in message:
            detail["error_code"] = (message.get("error") or {}).get("code")
        body = {'capture':'excluded','reason':'Authentication protocol contents are not recorded.'} if original.startswith(('account/','initialize')) else message
        self.record(direction, method, "error" if "error" in message else "sent" if direction == "backend-model" else "received",
                    correlation_id=f"{user_id}:{scope or 'subscription'}:{message.get('id', params.get('threadId', ''))}", user_id=user_id, size=size, detail=detail,payload=body)

    def start(self):
        self.task = asyncio.create_task(self._writer())

    async def _writer(self):
        while True:
            await asyncio.sleep(0.25)
            try:
                await self.flush()
            except Exception:
                # Observability must not interrupt chats or expose driver exceptions.
                continue

    async def flush(self):
        async with self.lock:
            batch = [self.pending.popleft() for _ in range(len(self.pending))]
            if not batch:
                return

            def write():
                with self.db.connect() as connection:
                    connection.executemany(
                        "INSERT INTO traffic_events(created_at,direction,action,status,correlation_id,user_id,bytes,duration_ms,detail_json,payload_json,payload_truncated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        batch,
                    )
                    connection.execute(
                        "DELETE FROM traffic_events WHERE id < COALESCE((SELECT id FROM traffic_events ORDER BY id DESC LIMIT 1 OFFSET ?),0)",
                        (self.capacity - 1,),
                    )
            try:
                await asyncio.to_thread(write)
            except Exception:
                self.pending.extendleft(reversed(batch))
                raise

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.flush()


class TrafficMiddleware:
    """Count the entire response stream, including SSE, without buffering its body."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or (path == "/api/health" or path.startswith("/api/admin/traffic")):
            return await self.app(scope, receive, send)
        log = getattr(scope["app"].state, "traffic", None)
        if log is None:
            return await self.app(scope, receive, send)
        started, correlation = time.perf_counter(), uid()
        received, sent, status = 0, 0, 500
        request_body, response_body = bytearray(), bytearray()
        response_type = ''
        request_type = dict(scope.get('headers',[])).get(b'content-type',b'').decode(errors='replace')
        excluded = path.startswith(('/api/auth','/api/subscription','/api/admin/sources','/api/admin/users'))
        def capture(buffer, body, content_type):
            if not excluded and ('json' in content_type or content_type.startswith('text/')):
                buffer.extend(body[:max(0,65536-len(buffer))])
        def body_preview(buffer, content_type):
            if excluded:
                return {'capture':'excluded','reason':'Authentication and connection configuration contents are not recorded.'}
            if not buffer:
                return {'capture':'empty-or-binary','content_type':content_type}
            text = buffer.decode('utf-8',errors='replace')
            if 'ndjson' in content_type:
                lines = []
                for line in text.splitlines():
                    try:
                        lines.append(json.loads(line))
                    except ValueError:
                        break
                return {'messages':lines}
            try:
                return json.loads(text)
            except ValueError:
                return {'text_preview':text}
        # Never log URL query strings, arbitrary paths, cookies or authorization headers.
        action = scope["method"] + " /api/" + (path.split("/")[2] if path.split("/")[2] in {
            "auth", "subscription", "conversations", "reports", "admin", "sources", "datasets", "voice", "report-templates"
        } else "[unmatched]")
        log.record("frontend-backend", action, "started", correlation_id=correlation)

        async def read():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            capture(request_body,message.get("body",b""),request_type)
            return message

        async def write(message):
            nonlocal sent, status, response_type
            if message["type"] == "http.response.start":
                status = message["status"]
                response_type = dict(message.get("headers",[])).get(b"content-type",b"").decode(errors="replace")
            sent += len(message.get("body", b""))
            capture(response_body,message.get("body",b""),response_type)
            await send(message)

        outcome = "ok"
        try:
            await self.app(scope, read, write)
        except BaseException:
            outcome = "interrupted" if status == 200 else "error"
            raise
        finally:
            route = getattr(scope.get("route"), "path", "/api/[unmatched]")
            log.record("frontend-backend", scope["method"] + " " + route, 'sent', correlation_id=correlation,
                       user_id=scope.get("state", {}).get("traffic_user_id"),size=received,
                       payload=body_preview(request_body,request_type),truncated=received>len(request_body) and bool(request_body))
            log.record("backend-frontend", scope["method"] + " " + route,
                       "error" if status >= 400 else outcome, correlation_id=correlation,
                       user_id=scope.get("state", {}).get("traffic_user_id"), size=sent,
                       duration_ms=round((time.perf_counter() - started) * 1000, 2),
                       detail={"status_code": status, "request_bytes": received, "response_bytes": sent},
                       payload=body_preview(response_body,response_type),truncated=sent>len(response_body) and bool(response_body))
