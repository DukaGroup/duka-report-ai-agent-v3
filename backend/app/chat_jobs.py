"""Durable, owner-scoped chat execution independent of an HTTP connection."""

import asyncio
import json

from .db import now
from .provider import ProviderError

ACTIVE = ("queued", "running", "paused")


class ChatJobs:
    def __init__(self, state):
        self.state = state
        self.db = state.db
        self.tasks = {}
        self.pending_resources = {}
        self.closing = False

    def enqueue(self, connection, identifier, conversation, user, payload):
        connection.execute(
            "INSERT INTO chat_runs VALUES(?,?,?,?,?,?,?)",
            (identifier, conversation, user, json.dumps(payload, ensure_ascii=False), "queued", 0, now()),
        )

    def start(self, identifier, runtime=None, lock=None):
        if identifier in self.tasks:
            return
        self.pending_resources[identifier] = (runtime, lock)
        task = asyncio.create_task(self.run(identifier, runtime, lock))
        self.tasks[identifier] = task
        task.add_done_callback(lambda done: self.tasks.pop(identifier, None))

    def record(self, identifier, event, text=None, status=None):
        # The message checkpoint and reconnect event must describe the same state.
        with self.db.connect() as c:
            if text is not None:
                c.execute(
                    "UPDATE messages SET content=?,status=? WHERE id=?", (text, status or "streaming", identifier)
                )
            c.execute(
                "INSERT INTO chat_run_events(run_id,event_json) VALUES(?,?)",
                (identifier, json.dumps(event, ensure_ascii=False)),
            )
            terminal = (
                event.get("status", "interrupted")
                if event["type"] == "done"
                else ("failed" if event["type"] == "error" else None)
            )
            if terminal:
                c.execute("UPDATE chat_runs SET status=?,updated_at=? WHERE id=?", (terminal, now(), identifier))
            else:
                c.execute("UPDATE chat_runs SET updated_at=? WHERE id=?", (now(), identifier))

    async def run(self, identifier, runtime=None, lock=None):
        self.pending_resources.pop(identifier, None)
        row = self.db.one("SELECT * FROM chat_runs WHERE id=?", (identifier,))
        if not row or row["status"] not in ACTIVE:
            return
        user, cid = row["user_id"], row["conversation_id"]
        payload = json.loads(row["payload_json"])
        text = self.db.one("SELECT content FROM messages WHERE id=?", (identifier,))["content"]
        status = "interrupted"
        acquired = runtime is not None
        if lock is None:
            lock = self.state.locks.setdefault(cid, asyncio.Lock())
            await lock.acquire()
        try:
            self.db.execute(
                "UPDATE chat_runs SET status='running',attempts=attempts+1,updated_at=? WHERE id=?", (now(), identifier)
            )
            if not self.db.one("SELECT id FROM users WHERE id=? AND active=1", (user,)):
                raise ProviderError("This account is no longer active.")
            if runtime is None:
                # Finish already accepted report work before continuing its originating chat.
                pending = [
                    task
                    for rid, task in self.state.report_jobs.items()
                    if self.db.one("SELECT id FROM reports WHERE id=? AND conversation_id=?", (rid, cid))
                ]
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                runtime = await self.state.manager.acquire_worker(user, "chat", cid, payload["model"])
                acquired = True
                thread = await runtime.thread(None, payload["model"])
                runtime.pending_handoff = True
                history = self.db.all(
                    "SELECT role,content FROM messages WHERE conversation_id=? AND id<>? AND status='completed' ORDER BY created_at,rowid",
                    (cid, identifier),
                )
                # All earlier instructions are retained. The unfinished draft is evidence,
                # not a completed answer or a new instruction.
                reports = self.db.all(
                    "SELECT id,title,status FROM reports WHERE user_id=? AND conversation_id=? AND deleted_at IS NULL",
                    (user, cid),
                )
                original = (
                    json.loads(payload["content"]) if payload.get("wrapped") else {"new_message": payload["content"]}
                )
                content = json.dumps(
                    {
                        **original,
                        "previous_messages": history[:-1],
                        "new_message": history[-1]["content"] if history else original.get("new_message", ""),
                        "recovery": {
                            "instruction": "The server restarted during this response. Continue the original investigation automatically and return a complete final answer. Recheck unfinished operations. Reuse existing reports instead of creating duplicates. The unfinished draft is unverified evidence.",
                            "unfinished_draft": text,
                            "existing_reports": reports,
                        },
                    },
                    ensure_ascii=False,
                )
                provider = runtime.provider
                with self.db.connect() as c:
                    c.execute("UPDATE conversations SET provider_thread_id=? WHERE id=?", (thread, cid))
                    c.execute("DELETE FROM conversation_provider_threads WHERE conversation_id=?", (cid,))
                    c.execute("INSERT INTO conversation_provider_threads VALUES(?,?,?)", (cid, provider, thread))
                payload.update(thread=thread, content=content, wrapped=True)
                self.db.execute(
                    "UPDATE chat_runs SET payload_json=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), identifier),
                )
                text = ""
                self.record(identifier, {"type": "snapshot", "text": "", "activity": "recovering"}, text)
            self.record(identifier, {"type": "message", "id": identifier, "user_message_id": payload.get('user_message_id')})
            async for event in runtime.stream(
                payload["thread"],
                payload["content"],
                payload["model"],
                **({"reasoning_effort": payload["effort"]} if payload.get("effort") is not None else {}),
            ):
                if event["type"] == "delta":
                    text += event["text"]
                elif event["type"] == "snapshot":
                    text = event.get("text", "")
                elif event["type"] == "done":
                    status = "completed" if event["status"] == "completed" else "interrupted"
                    text = event.get("text") or text
                self.record(identifier, event, text, status if event["type"] == "done" else "streaming")
            if status != "completed":
                status = "interrupted"
        except asyncio.CancelledError:
            if self.closing:
                self.db.execute(
                    "UPDATE chat_runs SET status='paused',updated_at=? WHERE id=? AND status IN ('queued','running','paused')",
                    (now(), identifier),
                )
                return
            status = "interrupted"
            self.record(identifier, {"type": "done", "status": status, "text": text}, text, status)
        except Exception as exc:
            status = "failed"
            message = str(exc) if isinstance(exc, ProviderError) else "The response could not finish. Please try again."
            text = message
            self.record(identifier, {"type": "error", "message": message, "text": message}, text, status)
        finally:
            if not self.closing:
                self.db.execute("UPDATE messages SET content=?,status=? WHERE id=?", (text, status, identifier))
                self.db.execute("UPDATE chat_runs SET status=?,updated_at=? WHERE id=?", (status, now(), identifier))
                self.db.audit(user, "chat.response", cid, {"status": status})
            if lock.locked():
                lock.release()
            if acquired:
                await self.state.manager.release_worker(user, "chat", cid)

    async def events(self, identifier, after=0):
        quiet = 0
        while True:
            rows = self.db.all(
                "SELECT seq,event_json FROM chat_run_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT 256",
                (identifier, after),
            )
            for row in rows:
                after = row["seq"]
                yield json.dumps({**json.loads(row["event_json"]), "seq": after}) + "\n"
            job = self.db.one("SELECT status FROM chat_runs WHERE id=?", (identifier,))
            if not job or (job["status"] not in ACTIVE and not rows):
                return
            if rows:
                quiet = 0
                continue
            quiet += 1
            if quiet >= 60:
                yield json.dumps({"type": "heartbeat"}) + "\n"
                quiet = 0
            await asyncio.sleep(0.25)

    async def stop(self, conversation):
        row = self.db.one(
            "SELECT id,user_id,payload_json FROM chat_runs WHERE conversation_id=? AND status IN ('queued','running','paused')",
            (conversation,),
        )
        if row:
            thread = json.loads(row["payload_json"])["thread"]
            runtime = self.state.manager.workers.get((row["user_id"], "chat", conversation))
            turn = runtime.active_turns.get(thread) if runtime else None
            if turn:
                # A database read may finish in another task after cancellation.
                # Reject a late report submission from this stopped turn as well.
                self.state.manager.cancelled_report_turns.add((row["user_id"], thread, turn))
            task = self.tasks.get(row["id"])
            if task:
                task.cancel()
            if runtime:
                runtime.request_stop()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            await self.release_pending(row["id"], row["user_id"], conversation)
            job = self.db.one("SELECT status FROM chat_runs WHERE id=?", (row["id"],))
            if job and job["status"] in ACTIVE:
                message = self.db.one("SELECT content FROM messages WHERE id=?", (row["id"],))
                self.record(
                    row["id"],
                    {"type": "done", "status": "interrupted", "text": message["content"]},
                    message["content"],
                    "interrupted",
                )
                self.db.execute("UPDATE chat_runs SET status='interrupted' WHERE id=?", (row["id"],))

    async def release_pending(self, identifier, user, conversation):
        # Cancelling a task before its first scheduling turn skips its finally.
        resources = self.pending_resources.pop(identifier, None)
        if resources:
            runtime, lock = resources
            if lock and lock.locked():
                lock.release()
            if runtime:
                await self.state.manager.release_worker(user, "chat", conversation)

    async def close(self):
        self.closing = True
        for task in list(self.tasks.values()):
            task.cancel()
        await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
        for identifier in list(self.pending_resources):
            row = self.db.one("SELECT user_id,conversation_id FROM chat_runs WHERE id=?", (identifier,))
            if row:
                await self.release_pending(identifier, row["user_id"], row["conversation_id"])
