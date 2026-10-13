import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from typing import Literal

from fastapi.exceptions import RequestValidationError
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from jsonschema import Draft202012Validator, SchemaError, ValidationError

from .config import Settings
from .connectors import ConnectorRegistry, SourceNotConfigured
from .db import Database, now, uid
from .provider import ProviderError, SubscriptionManager
from .reports import csv_snapshot, generate_report, markdown_report, save_excel
from .schemas import (
    ChatMessage,
    CreateUser,
    Credentials,
    NewConversation,
    NewDataset,
    NewSource,
    ReportRequest,
    UpdateUser,
)
from .security import (
    COOKIE,
    LoginLimiter,
    admin_user,
    create_session,
    current_user,
    hash_password,
    public_user,
    token_hash,
    verify_password,
)
from .voice import VoiceService
from .source_secrets import SecretsUnavailable
from .workbooks import excel_report


def create_app(settings=None, manager_factory=SubscriptionManager):
    settings = settings or Settings()
    dummy_password_hash = hash_password("unavailable-account")

    @asynccontextmanager
    async def lifespan(app):
        settings.prepare()
        app.state.settings = settings
        app.state.db = Database(settings.data_dir / "application.sqlite3")
        app.state.db.initialize()
        app.state.connectors = ConnectorRegistry(settings, app.state.db)
        app.state.manager = manager_factory(settings, app.state.db, app.state.connectors)
        app.state.voice = VoiceService(settings)
        app.state.limiter = LoginLimiter()
        app.state.locks = {}
        app.state.jobs = set()
        app.state.report_jobs = {}
        app.state.manager.report_threads = {}
        app.state.manager.cancelled_report_turns = set()
        app.state.manager.report_handler = submit_report
        yield
        for task in list(app.state.jobs):
            task.cancel()
        await asyncio.gather(*app.state.jobs, return_exceptions=True)
        await app.state.manager.close()

    app = FastAPI(
        title="Duka Report Agent", version="0.1.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.middleware("http")
    async def boundaries(request, call_next):
        if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if (origin and origin not in settings.allowed_origins) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return JSONResponse({"detail": "This request origin is not allowed."}, status_code=403)
            if request.headers.get("x-duka-request") != "1":
                return JSONResponse({"detail": "Missing application request header."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; media-src 'self' blob:; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # FastAPI's default validation details include input values, including secrets.
        return JSONResponse(
            {"detail": [{"loc": error["loc"], "msg": error["msg"], "type": error["type"]} for error in exc.errors()]},
            status_code=422,
        )

    @app.exception_handler(SecretsUnavailable)
    async def secrets_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(ProviderError)
    async def provider_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "provider": "chatgpt-subscription", "version": "0.1.0"}

    @app.get("/api/auth/status")
    async def auth_status(request: Request):
        needs_setup = request.app.state.db.one("SELECT count(*) AS count FROM users")["count"] == 0
        try:
            user = public_user(current_user(request))
        except HTTPException:
            user = None
        return {"needs_setup": needs_setup, "user": user}

    @app.post("/api/auth/setup")
    async def setup(body: CreateUser, request: Request, response: Response):
        db = request.app.state.db
        request.app.state.limiter.check(request.client.host)
        user_id = uid()
        with db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT count(*) FROM users").fetchone()[0]:
                raise HTTPException(409, "Workspace setup has already been completed.")
            c.execute(
                "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                (user_id, body.email, body.name, hash_password(body.password), "admin", 1, now()),
            )
        db.audit(user_id, "workspace.setup")
        create_session(db, settings, response, user_id)
        return public_user(db.one("SELECT * FROM users WHERE id=?", (user_id,)))

    @app.post("/api/auth/login")
    async def login(body: Credentials, request: Request, response: Response):
        db = request.app.state.db
        request.app.state.limiter.check(request.client.host)
        user = db.one("SELECT * FROM users WHERE email=? AND active=1", (body.email,))
        # Do the expensive password work even for unknown accounts.
        encoded = user["password_hash"] if user else dummy_password_hash
        if not verify_password(body.password, encoded) or not user:
            raise HTTPException(401, "Email or password is incorrect.")
        create_session(db, settings, response, user["id"])
        db.audit(user["id"], "workspace.login")
        return public_user(user)

    @app.post("/api/auth/logout")
    async def logout(request: Request, response: Response, user=Depends(current_user)):
        request.app.state.db.execute(
            "DELETE FROM sessions WHERE token_hash=?", (token_hash(request.cookies.get(COOKIE, "")),)
        )
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/subscription")
    async def subscription(request: Request, user=Depends(current_user)):
        try:
            result = await request.app.state.manager.for_user(user["id"]).account()
            return {**result, "available": True, "provider": "chatgpt-subscription"}
        except ProviderError as exc:
            return {"connected": False, "available": False, "error": str(exc), "provider": "chatgpt-subscription"}

    @app.post("/api/subscription/login")
    async def subscription_login(request: Request, user=Depends(current_user)):
        result = await request.app.state.manager.for_user(user["id"]).begin_login()
        request.app.state.db.audit(user["id"], "subscription.login_started")
        return result

    @app.post("/api/subscription/disconnect")
    async def subscription_disconnect(request: Request, user=Depends(current_user)):
        runtime = request.app.state.manager.for_user(user["id"])
        if runtime.active_turns:
            raise HTTPException(409, "Stop active responses before disconnecting.")
        await runtime.logout()
        # Old histories must not be reused with a different ChatGPT account.
        request.app.state.db.execute("UPDATE conversations SET provider_thread_id=NULL WHERE user_id=?", (user["id"],))
        await request.app.state.manager.release(user["id"])
        request.app.state.db.audit(user["id"], "subscription.disconnected")
        return {"ok": True}

    @app.get("/api/subscription/models")
    async def models(request: Request, user=Depends(current_user)):
        return await request.app.state.manager.for_user(user["id"]).models()

    @app.get("/api/subscription/usage")
    async def usage(request: Request, user=Depends(current_user)):
        runtime = request.app.state.manager.for_user(user["id"])
        await runtime.require_account()
        return await runtime.rpc("account/rateLimits/read")

    def owned_conversation(request, conversation_id, user_id):
        row = request.app.state.db.one(
            "SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user_id)
        )
        if not row:
            raise HTTPException(404, "Conversation not found.")
        return row

    @app.get("/api/conversations")
    async def conversations(request: Request, user=Depends(current_user)):
        return request.app.state.db.all(
            "SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count, "
            "(SELECT SUBSTR(m.content,1,180) FROM messages m WHERE m.conversation_id=c.id AND m.content<>'' ORDER BY m.created_at DESC,m.rowid DESC LIMIT 1) AS preview "
            "FROM conversations c WHERE c.user_id=? ORDER BY c.updated_at DESC",
            (user["id"],),
        )

    @app.post("/api/conversations", status_code=201)
    async def new_conversation(body: NewConversation, request: Request, user=Depends(current_user)):
        identifier, timestamp = uid(), now()
        request.app.state.db.execute(
            "INSERT INTO conversations VALUES(?,?,?,?,?,?,?)",
            (identifier, user["id"], body.title, body.model, None, timestamp, timestamp),
        )
        return owned_conversation(request, identifier, user["id"])

    @app.get("/api/conversations/{conversation_id}")
    async def conversation(conversation_id: str, request: Request, user=Depends(current_user)):
        row = owned_conversation(request, conversation_id, user["id"])
        return {
            **row,
            "messages": request.app.state.db.all(
                "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at,rowid", (conversation_id,)
            ),
        }

    @app.delete("/api/conversations/{conversation_id}")
    async def delete_conversation(conversation_id: str, request: Request, user=Depends(current_user)):
        owned_conversation(request, conversation_id, user["id"])
        lock = request.app.state.locks.setdefault(conversation_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Stop the current response before deleting this conversation.")
        async with lock:
            request.app.state.db.execute(
                "DELETE FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"])
            )
            request.app.state.db.audit(user["id"], "conversation.deleted", conversation_id)
        return {"ok": True}

    @app.post("/api/conversations/{conversation_id}/messages")
    async def send_message(conversation_id: str, body: ChatMessage, request: Request, user=Depends(current_user)):
        row = owned_conversation(request, conversation_id, user["id"])
        if request.app.state.db.one(
            "SELECT id FROM reports WHERE user_id=? AND status IN ('queued','running') LIMIT 1", (user["id"],)
        ):
            raise HTTPException(409, "Wait for your report to finish, or interrupt it first.")
        runtime = request.app.state.manager.for_user(user["id"])
        await runtime.require_account()
        lock = request.app.state.locks.setdefault(conversation_id, asyncio.Lock())
        if lock.locked():
            raise HTTPException(409, "Wait for this response to finish, or stop it first.")
        await lock.acquire()
        try:
            row = owned_conversation(request, conversation_id, user["id"])
            if request.app.state.db.one(
                "SELECT id FROM reports WHERE user_id=? AND status IN ('queued','running') LIMIT 1", (user["id"],)
            ):
                raise HTTPException(409, "Wait for your report to finish, or interrupt it first.")
            model = body.model or row["model"]
            thread_id = await runtime.thread(row["provider_thread_id"], model)
            # Local history is replayed if the provider thread was cleared at disconnect.
            content = body.content
            if thread_id != row["provider_thread_id"]:
                history = request.app.state.db.all(
                    "SELECT role,content FROM messages WHERE conversation_id=? AND status='completed' ORDER BY created_at,rowid",
                    (conversation_id,),
                )
                if history:
                    content = json.dumps(
                        {"previous_messages": history[-40:], "new_message": body.content}, ensure_ascii=False
                    )
            db = request.app.state.db
            title = body.content.strip()[:60] if row["title"] in ("New conversation", "Bisedë e re") else row["title"]
            db.execute(
                "UPDATE conversations SET provider_thread_id=?,model=?,title=?,updated_at=? WHERE id=?",
                (thread_id, model, title, now(), conversation_id),
            )
            db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?)",
                (uid(), conversation_id, "user", body.content, "completed", now()),
            )
            assistant_id = uid()
            db.execute(
                "INSERT INTO messages VALUES(?,?,?,?,?,?)",
                (assistant_id, conversation_id, "assistant", "", "streaming", now()),
            )
        except BaseException:
            lock.release()
            raise

        async def events():
            text, status = "", "interrupted"
            try:
                yield json.dumps({"type": "message", "id": assistant_id}) + "\n"
                async for event in runtime.stream(thread_id, content, model):
                    if event["type"] == "delta":
                        text += event["text"]
                    elif event["type"] == "done":
                        status = "completed" if event["status"] == "completed" else "interrupted"
                        text = event.get("text") or text
                    yield json.dumps(event) + "\n"
            except ProviderError as exc:
                status = "failed"
                yield json.dumps({"type": "error", "message": str(exc)}) + "\n"
            except asyncio.CancelledError:
                raise
            except Exception:
                status = "failed"
                yield (
                    json.dumps({"type": "error", "message": "The response could not finish. Please try again."}) + "\n"
                )
            finally:
                db.execute("UPDATE messages SET content=?,status=? WHERE id=?", (text, status, assistant_id))
                db.audit(user["id"], "chat.response", conversation_id, {"status": status})
                lock.release()

        return StreamingResponse(events(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no"})

    @app.post("/api/conversations/{conversation_id}/stop")
    async def stop_message(conversation_id: str, request: Request, user=Depends(current_user)):
        row = owned_conversation(request, conversation_id, user["id"])
        if row["provider_thread_id"]:
            runtime = request.app.state.manager.for_user(user["id"])
            turn = runtime.active_turns.get(row["provider_thread_id"])
            if turn:
                request.app.state.manager.cancelled_report_turns.add((user["id"], row["provider_thread_id"], turn))
            await stop_reports(user["id"])
            try:
                await runtime.interrupt(row["provider_thread_id"])
            except ProviderError:
                pass
        await stop_reports(user["id"])
        return {"ok": True}

    async def stop_reports(user_id, identifier=None):
        state = app.state
        reports = state.db.all("SELECT id FROM reports WHERE user_id=? AND status IN ('queued','running')", (user_id,))
        for report in reports:
            if identifier and report["id"] != identifier:
                continue
            thread_id = state.manager.report_threads.get(report["id"])
            task = state.report_jobs.get(report["id"])
            if task:
                task.cancel()
            if thread_id:
                try:
                    await state.manager.for_user(user_id).interrupt(thread_id)
                except ProviderError:
                    pass
            if task:
                await asyncio.gather(task, return_exceptions=True)
            # Also covers cancellation before the coroutine gets its first scheduling turn.
            state.db.execute(
                "UPDATE reports SET status='failed',stage='interrupted',error=?,completed_at=? WHERE id=? AND status IN ('queued','running')",
                ("Report generation was interrupted by the user.", now(), report["id"]),
            )

    @app.post("/api/reports/{identifier}/stop")
    async def stop_report(identifier: str, request: Request, user=Depends(current_user)):
        owned_report(request, identifier, user["id"])
        await stop_reports(user["id"], identifier)
        return {"ok": True}

    @app.get("/api/voice")
    async def voice_status(request: Request, user=Depends(current_user)):
        return request.app.state.voice.status()

    @app.post("/api/voice/transcribe")
    async def transcribe(
        request: Request,
        file: UploadFile = File(...),
        language: Literal["sq", "en", "auto"] | None = Form(None),
        user=Depends(current_user),
    ):
        suffixes = {
            "audio/webm": ".webm",
            "audio/ogg": ".ogg",
            "audio/wav": ".wav",
            "audio/mp4": ".m4a",
            "audio/mpeg": ".mp3",
        }
        mime = (file.content_type or "").split(";")[0]
        if mime not in suffixes:
            raise HTTPException(415, "Use a supported audio recording (WebM, Ogg, WAV, MP4, or MP3).")
        audio = await file.read(12 * 1024 * 1024 + 1)
        await file.close()
        if len(audio) > 12 * 1024 * 1024:
            raise HTTPException(413, "Recording is too large. Keep recordings under 12 MB.")
        if not audio:
            raise HTTPException(400, "Recording is empty.")
        try:
            return await request.app.state.voice.transcribe(audio, suffixes[mime], language)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                503, "Local transcription failed. Check the recording, model download, and server resources."
            ) from exc

    @app.get("/api/sources")
    async def accessible_sources(request: Request, user=Depends(current_user)):
        return app.state.connectors.accessible_sources(user["id"])

    @app.get("/api/datasets")
    async def datasets(request: Request, user=Depends(current_user)):
        return request.app.state.db.all(
            "SELECT d.id,d.name,d.description,d.enabled,s.name AS source,s.status FROM datasets d JOIN data_sources s ON s.id=d.source_id "
            "JOIN dataset_grants g ON g.dataset_id=d.id WHERE g.user_id=?",
            (user["id"],),
        )

    @app.get("/api/report-templates")
    async def templates(request: Request, user=Depends(current_user)):
        return request.app.state.db.all("SELECT * FROM report_templates")

    @app.get("/api/reports")
    async def report_list(request: Request, deleted: bool = False, user=Depends(current_user)):
        return request.app.state.db.all(
            "SELECT id,title,conversation_id,template_id,status,stage,error,created_at,completed_at,deleted_at FROM reports WHERE user_id=? AND "
            + ("deleted_at IS NOT NULL" if deleted else "deleted_at IS NULL")
            + " ORDER BY created_at DESC",
            (user["id"],),
        )

    def owned_report(request, identifier, user_id):
        row = request.app.state.db.one(
            "SELECT * FROM reports WHERE id=? AND user_id=? AND deleted_at IS NULL", (identifier, user_id)
        )
        if not row:
            raise HTTPException(404, "Report not found.")
        return row

    @app.delete("/api/reports/{identifier}")
    async def delete_report(identifier: str, request: Request, user=Depends(current_user)):
        report = owned_report(request, identifier, user["id"])
        if report["status"] in ("queued", "running"):
            raise HTTPException(409, "Stop the report before deleting it.")
        request.app.state.db.execute(
            "UPDATE reports SET deleted_at=? WHERE id=? AND user_id=?", (now(), identifier, user["id"])
        )
        request.app.state.db.audit(user["id"], "report.deleted", identifier)
        return {"ok": True}

    @app.post("/api/reports/{identifier}/restore")
    async def restore_report(identifier: str, request: Request, user=Depends(current_user)):
        report = request.app.state.db.one(
            "SELECT id FROM reports WHERE id=? AND user_id=? AND deleted_at IS NOT NULL", (identifier, user["id"])
        )
        if not report:
            raise HTTPException(404, "Report not found.")
        request.app.state.db.execute(
            "UPDATE reports SET deleted_at=NULL WHERE id=? AND user_id=?", (identifier, user["id"])
        )
        request.app.state.db.audit(user["id"], "report.restored", identifier)
        return {"ok": True}

    @app.post("/api/reports", status_code=201)
    async def new_report(body: ReportRequest, request: Request, user=Depends(current_user)):
        return await submit_report(user["id"], body)

    async def submit_report(user_id, body, origin_thread=None, origin_turn=None):
        user = {"id": user_id}
        state = app.state
        db = state.db
        if not db.one("SELECT id FROM report_templates WHERE id=?", (body.template_id,)):
            raise HTTPException(422, "Report template not found.")
        if body.conversation_id:
            if not db.one("SELECT id FROM conversations WHERE id=? AND user_id=?", (body.conversation_id, user_id)):
                raise HTTPException(404, "Conversation not found.")
        if sum((body.rows is not None, bool(body.dataset_id), bool(body.source_id))) > 1:
            raise HTTPException(422, "Choose one data source: database query, dataset, or manual rows.")
        if bool(body.source_id) != (body.query is not None):
            raise HTTPException(422, "A database report requires both source_id and a structured query.")
        if body.analyses and not body.source_id:
            raise HTTPException(422, "Additional analyses require an authorized database source.")
        error, rows, provenance = None, body.rows, {"source": "User-provided data", "parameters": body.parameters}
        if body.source_id:
            try:
                source = state.connectors.authorized_source(user_id, body.source_id)
            except SourceNotConfigured as exc:
                raise HTTPException(404, "Database source is unavailable or access was not granted.") from exc
            try:
                result = await state.connectors.database_call(
                    user_id, body.source_id, "query", query=body.query.model_dump(by_alias=True)
                )
                if result["truncated"]:
                    raise HTTPException(
                        422,
                        "Report results exceed the row limit. Use aggregate metrics or narrower filters; a preview cannot be saved as a complete report.",
                    )
                rows = result["rows"]
                provenance = {
                    "source": source["name"],
                    "source_id": source["id"],
                    "query": result["query"],
                    "columns": result["columns"],
                    "scope": result["scope"],
                    "parameters": body.parameters,
                    "analysis": body.analysis.model_dump(),
                }
            except SourceNotConfigured as exc:
                error = str(exc)
            except ValueError as exc:
                raise HTTPException(
                    422, "Invalid database query. Check selected tables, columns, joins and grouping."
                ) from exc
        elif body.dataset_id:
            dataset = db.one(
                "SELECT d.* FROM datasets d JOIN dataset_grants g ON g.dataset_id=d.id WHERE d.id=? AND g.user_id=?",
                (body.dataset_id, user["id"]),
            )
            if not dataset:
                raise HTTPException(404, "Dataset not found or access was not granted.")
            try:
                rows = await state.connectors.fetch(dataset, body.parameters)
                provenance = {
                    "source": dataset["name"],
                    "query_key": dataset["query_key"],
                    "parameters": body.parameters,
                    "columns": json.loads(dataset["columns_schema_json"]),
                }
            except SourceNotConfigured as exc:
                error = str(exc)
            except ValidationError as exc:
                raise HTTPException(422, "Dataset parameters do not match the registered schema.") from exc
        elif not rows:
            error = "No reporting data is available yet. Add manual JSON rows or connect a database later."
        if not error and not rows:
            error = "The dataset returned no rows for these parameters. No business figures are available to report."
        serialized = json.dumps(rows or [], allow_nan=False)
        if (user_id, origin_thread, origin_turn) in state.manager.cancelled_report_turns:
            raise HTTPException(409, "Report generation was interrupted by the user.")
        provenance.setdefault("analysis", body.analysis.model_dump())
        if len(serialized.encode()) > 100000 or (rows and len(rows) > 500):
            raise HTTPException(413, "For this prototype, use at most 500 rows and 100 KB of data.")
        identifier, snapshot_id = uid(), None
        if not error:
            await state.manager.for_user(user["id"]).require_account()
            in_flight = db.one(
                "SELECT count(*) AS count FROM reports WHERE user_id=? AND status IN ('queued','running')",
                (user["id"],),
            )["count"]
            if in_flight >= 2:
                raise HTTPException(429, "Wait for your current reports to finish before starting another.")
            snapshot_id = uid()
            db.execute(
                "INSERT INTO dataset_snapshots VALUES(?,?,?,?,?,?)",
                (snapshot_id, user["id"], body.dataset_id, json.dumps(provenance), serialized, now()),
            )
        db.execute(
            "INSERT INTO reports(id,user_id,conversation_id,template_id,snapshot_id,title,instructions,model,parameters_json,status,error,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                user["id"],
                body.conversation_id,
                body.template_id,
                snapshot_id,
                body.title,
                body.instructions,
                body.model,
                json.dumps(body.parameters),
                "blocked" if error else "queued",
                error,
                now(),
            ),
        )
        db.audit(user["id"], "report.requested", identifier)
        if not error:
            task = asyncio.create_task(
                generate_report(
                    db, state.manager, identifier, user["id"], [a.model_dump(by_alias=True) for a in body.analyses]
                )
            )
            state.jobs.add(task)
            state.report_jobs[identifier] = task

            def done(task):
                state.jobs.discard(task)
                state.report_jobs.pop(identifier, None)

            task.add_done_callback(done)
        return db.one("SELECT * FROM reports WHERE id=? AND user_id=?", (identifier, user_id))

    @app.get("/api/reports/{identifier}")
    async def report_detail(identifier: str, request: Request, user=Depends(current_user)):
        report = owned_report(request, identifier, user["id"])
        report["document"] = json.loads(report["content_json"]) if report["content_json"] else None
        return report

    @app.get("/api/reports/{identifier}/export/{format}")
    async def export_report(identifier: str, format: str, request: Request, user=Depends(current_user)):
        report = owned_report(request, identifier, user["id"])
        if report["status"] != "completed":
            raise HTTPException(409, "This report is not ready to export.")
        snapshot = request.app.state.db.one(
            "SELECT * FROM dataset_snapshots WHERE id=? AND user_id=?", (report["snapshot_id"], user["id"])
        )
        if format == "xlsx":
            path = request.app.state.settings.data_dir / "reports" / (identifier + ".xlsx")
            if not path.exists():
                # Existing saved reports acquire Excel exports without another subscription request.
                content = await asyncio.to_thread(excel_report, report, snapshot)
                save_excel(request.app.state.manager, report, snapshot, content)
            return FileResponse(
                path,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                filename=f"report-{identifier}.xlsx",
            )
        if format == "markdown":
            content, media, extension = markdown_report(report, snapshot), "text/markdown", "md"
        elif format == "json":
            content, media, extension = (
                json.dumps(
                    {
                        "document": json.loads(report["content_json"]),
                        "provenance": json.loads(snapshot["provenance_json"]),
                        "captured_at": snapshot["captured_at"],
                    },
                    indent=2,
                ),
                "application/json",
                "json",
            )
        elif format == "csv":
            content, media, extension = csv_snapshot(snapshot), "text/csv", "csv"
        else:
            raise HTTPException(404, "Unsupported export format.")
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="report-{identifier}.{extension}"'},
        )

    @app.get("/api/admin/overview")
    async def overview(request: Request, user=Depends(admin_user)):
        db = request.app.state.db
        counts = {
            name: db.one(f"SELECT count(*) AS count FROM {name}")["count"]
            for name in ("users", "conversations", "reports", "data_sources")
        }
        return {
            "counts": counts,
            "provider": "ChatGPT subscription / Codex CLI",
            "billing": "Subscription only",
            "active_runtimes": len(request.app.state.manager.runtimes),
            "max_runtimes": settings.max_runtimes,
            "voice": request.app.state.voice.status(),
            "database_sources": [
                app.state.connectors.public_source(source)
                for source in db.all("SELECT * FROM data_sources ORDER BY created_at")
            ],
            "database_configuration": app.state.connectors.configuration(),
        }

    @app.get("/api/admin/users")
    async def users(request: Request, user=Depends(admin_user)):
        return [public_user(row) for row in request.app.state.db.all("SELECT * FROM users ORDER BY created_at")]

    @app.post("/api/admin/users", status_code=201)
    async def add_user(body: CreateUser, request: Request, user=Depends(admin_user)):
        identifier = uid()
        try:
            request.app.state.db.execute(
                "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
                (identifier, body.email, body.name, hash_password(body.password), body.role, 1, now()),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "A user with that email already exists.") from exc
        request.app.state.db.audit(user["id"], "user.created", identifier)
        return public_user(request.app.state.db.one("SELECT * FROM users WHERE id=?", (identifier,)))

    @app.patch("/api/admin/users/{identifier}")
    async def update_user(identifier: str, body: UpdateUser, request: Request, user=Depends(admin_user)):
        if identifier == user["id"] and not body.active:
            raise HTTPException(422, "You cannot disable your own administrator account.")
        if not request.app.state.db.execute("UPDATE users SET active=? WHERE id=?", (int(body.active), identifier)):
            raise HTTPException(404, "User not found.")
        if not body.active:
            request.app.state.db.execute("DELETE FROM sessions WHERE user_id=?", (identifier,))
            await request.app.state.manager.release(identifier)
        request.app.state.db.audit(user["id"], "user.updated", identifier, {"active": body.active})
        return {"ok": True}

    def seal_source_credentials(body, source_id, existing=False):
        values = body.connection_settings()
        if not values:
            return None
        if body.kind != "sqlserver":
            raise HTTPException(422, "SQL Server connection fields require database type sqlserver.")
        previous = app.state.connectors.secrets.load(source_id) if existing else None
        combined = {**(previous or {}), **values}
        required = {"SQLSERVER_HOST", "SQLSERVER_PORT", "SQLSERVER_USER", "SQLSERVER_PASSWORD", "SQLSERVER_DATABASE"}
        missing = required - combined.keys()
        if missing:
            raise HTTPException(422, "Complete the connection settings: " + ", ".join(sorted(missing)))
        return app.state.connectors.secrets.encrypt(source_id, combined)

    def public_source(source_id):
        source = app.state.db.one("SELECT * FROM data_sources WHERE id=?", (source_id,))
        return app.state.connectors.public_source(source)

    @app.get("/api/admin/sources")
    async def sources(request: Request, user=Depends(admin_user)):
        return [
            app.state.connectors.public_source(source)
            for source in app.state.db.all("SELECT * FROM data_sources ORDER BY created_at")
        ]

    @app.post("/api/admin/sources", status_code=201)
    async def add_source(body: NewSource, request: Request, user=Depends(admin_user)):
        identifier = uid()
        ciphertext = seal_source_credentials(body, identifier)
        with app.state.db.connect() as connection:
            connection.execute(
                "INSERT INTO data_sources(id,name,kind,description,status,created_at) VALUES(?,?,?,?,?,?)",
                (identifier, body.name, body.kind, body.description, "not_configured", now()),
            )
            if ciphertext:
                connection.execute("INSERT INTO source_credentials VALUES(?,?,?)", (identifier, ciphertext, now()))
        app.state.db.audit(user["id"], "source.created", identifier)
        app.state.connectors.attach(public_source(identifier))
        return public_source(identifier)

    @app.patch("/api/admin/sources/{source_id}")
    async def update_source(source_id: str, body: NewSource, request: Request, user=Depends(admin_user)):
        source = app.state.db.one("SELECT * FROM data_sources WHERE id=?", (source_id,))
        if not source:
            raise HTTPException(404, "Source not found.")
        if body.kind != source["kind"]:
            raise HTTPException(422, "Create a new source to use a different database type.")
        ciphertext = seal_source_credentials(body, source_id, existing=True)
        with app.state.db.connect() as connection:
            connection.execute(
                "UPDATE data_sources SET name=?,description=? WHERE id=?", (body.name, body.description, source_id)
            )
            if ciphertext:
                connection.execute(
                    "INSERT INTO source_credentials VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET ciphertext=excluded.ciphertext,updated_at=excluded.updated_at",
                    (source_id, ciphertext, now()),
                )
        app.state.db.audit(user["id"], "source.updated", source_id)
        if ciphertext:
            app.state.connectors.attach(public_source(source_id))
        return public_source(source_id)

    @app.post("/api/admin/sources/{source_id}/check")
    async def check_source(source_id: str, request: Request, user=Depends(admin_user)):
        if not request.app.state.db.one("SELECT id FROM data_sources WHERE id=?", (source_id,)):
            raise HTTPException(404, "Source not found.")
        try:
            await request.app.state.connectors.check(source_id)
        except SourceNotConfigured as exc:
            raise HTTPException(422, str(exc)) from exc
        request.app.state.db.audit(user["id"], "source.checked", source_id)
        return public_source(source_id)

    @app.get("/api/admin/sources/{source_id}/grants")
    async def source_grants(source_id: str, request: Request, user=Depends(admin_user)):
        if not app.state.db.one("SELECT id FROM data_sources WHERE id=?", (source_id,)):
            raise HTTPException(404, "Source not found.")
        return app.state.db.all("SELECT user_id FROM source_grants WHERE source_id=?", (source_id,))

    @app.put("/api/admin/sources/{source_id}/grants/{user_id}")
    async def grant_source(source_id: str, user_id: str, request: Request, user=Depends(admin_user)):
        db = app.state.db
        if not db.one("SELECT id FROM data_sources WHERE id=? AND kind='sqlserver'", (source_id,)) or not db.one(
            "SELECT id FROM users WHERE id=?", (user_id,)
        ):
            raise HTTPException(404, "Source or member not found.")
        db.execute("INSERT OR IGNORE INTO source_grants VALUES(?,?)", (source_id, user_id))
        db.audit(user["id"], "source.granted", source_id, {"user_id": user_id})
        return {"ok": True}

    @app.delete("/api/admin/sources/{source_id}/grants/{user_id}")
    async def revoke_source(source_id: str, user_id: str, request: Request, user=Depends(admin_user)):
        app.state.db.execute("DELETE FROM source_grants WHERE source_id=? AND user_id=?", (source_id, user_id))
        app.state.db.audit(user["id"], "source.revoked", source_id, {"user_id": user_id})
        return {"ok": True}

    @app.get("/api/admin/database")
    async def database_configuration(request: Request, user=Depends(admin_user)):
        return request.app.state.connectors.configuration()

    @app.patch("/api/admin/datasets/{dataset_id}")
    async def toggle_dataset(dataset_id: str, body: UpdateUser, request: Request, user=Depends(admin_user)):
        db = request.app.state.db
        dataset = db.one("SELECT * FROM datasets WHERE id=?", (dataset_id,))
        if not dataset:
            raise HTTPException(404, "Dataset not found.")
        if body.active:
            if dataset["source_id"] not in request.app.state.connectors.connectors:
                raise HTTPException(422, "No connector is implemented for this source type.")
            try:
                manifest, _ = request.app.state.connectors.catalog.load(dataset["query_key"])
            except SourceNotConfigured as exc:
                raise HTTPException(422, str(exc)) from exc
            db.execute(
                "UPDATE datasets SET parameters_schema_json=?,columns_schema_json=? WHERE id=?",
                (json.dumps(manifest["parameters_schema"]), json.dumps(manifest.get("columns_schema", [])), dataset_id),
            )
        db.execute("UPDATE datasets SET enabled=? WHERE id=?", (int(body.active), dataset_id))
        db.audit(user["id"], "dataset.updated", dataset_id, {"enabled": body.active})
        return db.one("SELECT * FROM datasets WHERE id=?", (dataset_id,))

    @app.get("/api/admin/datasets")
    async def admin_datasets(request: Request, user=Depends(admin_user)):
        return request.app.state.db.all("SELECT * FROM datasets ORDER BY created_at")

    @app.post("/api/admin/datasets", status_code=201)
    async def add_dataset(body: NewDataset, request: Request, user=Depends(admin_user)):
        if not request.app.state.db.one("SELECT id FROM data_sources WHERE id=?", (body.source_id,)):
            raise HTTPException(404, "Source not found.")
        try:
            Draft202012Validator.check_schema(body.parameters_schema)
        except SchemaError as exc:
            raise HTTPException(422, "Dataset parameters must be a valid JSON Schema.") from exc

        def local_references(value):
            if isinstance(value, dict):
                if "$ref" in value and not str(value["$ref"]).startswith("#"):
                    return False
                return all(local_references(v) for v in value.values())
            if isinstance(value, list):
                return all(local_references(v) for v in value)
            return True

        if not local_references(body.parameters_schema):
            raise HTTPException(422, "Dataset schemas must not reference remote resources.")
        try:
            manifest, _ = request.app.state.connectors.catalog.load(body.query_key)
            body.parameters_schema = manifest["parameters_schema"]
            body.columns_schema = manifest.get("columns_schema", [])
        except SourceNotConfigured:
            pass  # Unknown keys can be prepared now, but cannot be enabled.
        identifier = uid()
        request.app.state.db.execute(
            "INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                body.source_id,
                body.name,
                body.description,
                body.query_key,
                json.dumps(body.parameters_schema),
                json.dumps(body.columns_schema),
                0,
                now(),
            ),
        )
        request.app.state.db.audit(user["id"], "dataset.created", identifier)
        return request.app.state.db.one("SELECT * FROM datasets WHERE id=?", (identifier,))

    @app.put("/api/admin/datasets/{dataset_id}/grants/{user_id}")
    async def grant_dataset(dataset_id: str, user_id: str, request: Request, user=Depends(admin_user)):
        db = request.app.state.db
        if not db.one("SELECT id FROM users WHERE id=?", (user_id,)) or not db.one(
            "SELECT id FROM datasets WHERE id=?", (dataset_id,)
        ):
            raise HTTPException(404, "Dataset or user not found.")
        db.execute("INSERT OR IGNORE INTO dataset_grants VALUES(?,?)", (dataset_id, user_id))
        db.audit(user["id"], "dataset.granted", dataset_id, {"user_id": user_id})
        return {"ok": True}

    @app.delete("/api/admin/datasets/{dataset_id}/grants/{user_id}")
    async def revoke_dataset(dataset_id: str, user_id: str, request: Request, user=Depends(admin_user)):
        request.app.state.db.execute(
            "DELETE FROM dataset_grants WHERE dataset_id=? AND user_id=?", (dataset_id, user_id)
        )
        request.app.state.db.audit(user["id"], "dataset.revoked", dataset_id, {"user_id": user_id})
        return {"ok": True}

    @app.get("/api/admin/audit")
    async def audit(request: Request, user=Depends(admin_user)):
        return request.app.state.db.all(
            "SELECT a.*,u.email AS actor_email FROM audit_events a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.created_at DESC LIMIT 100"
        )

    @app.post("/api/admin/runtimes/{user_id}/restart")
    async def restart_runtime(user_id: str, request: Request, user=Depends(admin_user)):
        runtime = request.app.state.manager.runtimes.get(user_id)
        if runtime and runtime.active_turns:
            raise HTTPException(409, "This user has an active response. Wait for it to finish.")
        await request.app.state.manager.release(user_id)
        request.app.state.db.audit(user["id"], "runtime.restarted", user_id)
        return {"ok": True}

    if (settings.frontend_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=settings.frontend_dir / "assets"), name="assets")

    @app.get("/{path:path}")
    async def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Endpoint not found.")
        index = settings.frontend_dir / "index.html"
        if not index.exists():
            return JSONResponse(
                {"detail": "Frontend has not been built. Run npm ci && npm run build in frontend/."}, status_code=503
            )
        return FileResponse(index)

    return app


app = create_app()
