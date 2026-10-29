"""Append-only batched log storage; queued records are never count-evicted."""

import asyncio
from collections import deque
import contextlib


class PersistentLog:
    interval = 0.25
    batch_size = 500
    capacity = None  # API compatibility: null means no event-count retention cap.

    def __init__(self, db):
        self.db = db
        self.pending = deque()
        self.lock = asyncio.Lock()
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.writer())

    async def writer(self):
        while True:
            await asyncio.sleep(self.interval)
            try:
                await self.flush()
            except Exception:
                # Keep failed records queued; observability must not break chats.
                continue

    async def flush(self):
        async with self.lock:
            remaining = len(self.pending)
            while remaining:
                batch = [self.pending.popleft() for _ in range(min(remaining, self.batch_size))]
                remaining -= len(batch)
                task = asyncio.create_task(asyncio.to_thread(self.write_batch, batch))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    # A cancelled HTTP poll/shutdown must not abandon an in-flight
                    # commit or requeue rows which the SQLite worker has committed.
                    try:
                        await task
                    except Exception:
                        self.pending.extendleft(reversed(batch))
                    raise
                except Exception:
                    self.pending.extendleft(reversed(batch))
                    raise

    async def close(self):
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        await self.flush()
