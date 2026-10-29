import asyncio
import threading

import pytest

from app.db import Database
from app.system_logs import SystemLog
from app.traffic import TrafficLog


@pytest.fixture(params=["traffic", "system"])
def recorder(request, tmp_path):
    db = Database(tmp_path / "logs.sqlite3")
    db.initialize()
    if request.param == "traffic":
        log = TrafficLog(db)
        def record(i):
            log.record("model-backend", f"event-{i}", "received")
        table = "traffic_events"
    else:
        log = SystemLog(db, TrafficLog(db))
        def record(i):
            log.record("info", "application", f"event-{i}", "Fixture")
        table = "system_logs"
    return log, record, table


async def test_bursts_above_old_caps_are_not_dropped_before_or_after_flush(recorder):
    log, record, table = recorder
    for i in range(10050):
        record(i)
    assert len(log.pending) == 10050
    await log.flush()
    assert log.db.one(f"SELECT count(*) AS n FROM {table}")["n"] == 10050
    assert not log.pending
    record(10050)
    await log.close()
    assert log.db.one(f"SELECT count(*) AS n FROM {table}")["n"] == 10051
    if table == "traffic_events":
        assert log.db.one("SELECT sum(events) AS n FROM traffic_totals")["n"] == 10051
        log.db.execute("DELETE FROM traffic_events WHERE id=(SELECT min(id) FROM traffic_events)")
        assert log.db.one("SELECT sum(events) AS n FROM traffic_totals")["n"] == 10050


async def test_failed_batch_is_retried_without_losing_or_duplicating_events(recorder, monkeypatch):
    log, record, table = recorder
    original = log.write_batch
    def failed(batch):
        record(2)
        raise OSError("Fixture full disk")
    record(0)
    record(1)
    monkeypatch.setattr(log, "write_batch", failed)
    with pytest.raises(OSError):
        await log.flush()
    assert len(log.pending) == 3
    monkeypatch.setattr(log, "write_batch", original)
    await log.flush()
    assert log.db.one(f"SELECT count(*) AS n FROM {table}")["n"] == 3


@pytest.mark.parametrize("fail", [False, True])
async def test_cancelled_flush_waits_for_inflight_write_and_keeps_failed_rows(recorder, monkeypatch, fail):
    log, record, table = recorder
    started, release = threading.Event(), threading.Event()
    original = log.write_batch
    def held(batch):
        started.set()
        assert release.wait(timeout=5)
        if fail:
            raise OSError("Fixture failed commit")
        original(batch)
    monkeypatch.setattr(log, "write_batch", held)
    record(0)
    task = asyncio.create_task(log.flush())
    try:
        assert await asyncio.to_thread(started.wait, 3)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(log, "write_batch", original)
    await log.flush()
    assert log.db.one(f"SELECT count(*) AS n FROM {table}")["n"] == 1
