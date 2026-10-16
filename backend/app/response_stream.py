"""Keep quiet provider streams alive without cancelling an in-flight tool or SDK scope."""

import asyncio
from contextlib import aclosing


async def keepalive(events, *, timeout=None, interval=15):
    queue = asyncio.Queue(maxsize=256)

    async def consume():
        # SDK connect/receive/disconnect must all run in the same task (AnyIO scopes).
        async with aclosing(events):
            try:
                async for event in events:
                    await queue.put(event)
            except asyncio.CancelledError:
                # An SDK may cancel itself without a terminal message. Do not
                # leave its caller receiving heartbeats indefinitely in that case.
                if not queue.full():
                    queue.put_nowait(RuntimeError("Provider stream stopped before completion."))
                raise
            except Exception as exc:
                await queue.put(exc)
            await queue.put(None)

    task = asyncio.create_task(consume())
    terminal = False
    try:
        async with asyncio.timeout(timeout):
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), interval)
                except TimeoutError:
                    if not terminal:
                        yield {"type": "heartbeat"}
                    continue
                if event is None:
                    return
                if isinstance(event, Exception):
                    raise event
                terminal = event.get("type") in ("done", "error") or terminal
                yield event
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
