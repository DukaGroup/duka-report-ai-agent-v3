import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.notifications import PushNotifications
from conftest import HEADERS
from test_chat_controls import prepare, post
from test_claude_subscriptions import claude as claude_fixture


@pytest.fixture(autouse=True)
def controlled_push(monkeypatch):
    # Use explicit dispatch in tests; no external push services are contacted.
    monkeypatch.setattr(PushNotifications, "start", lambda self: None)


@pytest.fixture
def claude(client, monkeypatch):
    return claude_fixture.__wrapped__(client, monkeypatch)


def subscription():
    key = (
        ec.generate_private_key(ec.SECP256R1())
        .public_key()
        .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )

    def encode(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    return {
        "endpoint": "https://fcm.googleapis.com/fcm/send/fixture-secret-endpoint",
        "expirationTime": None,
        "keys": {"p256dh": encode(key), "auth": encode(b"1234567890123456")},
    }


def enable(client):
    config = client.get("/api/notifications/config")
    assert config.status_code == 200 and len(config.json()["public_key"]) == 87
    body = subscription()
    assert client.post("/api/notifications/subscriptions", headers=HEADERS, json=body).status_code == 200
    return body


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_both_providers_queue_owner_only_generic_push_and_retry_without_open_page(
    client, admin, claude, monkeypatch, provider
):
    enable(client)
    calls = []
    service = client.app.state.notifications
    monkeypatch.setattr(service, "send", lambda sub, data: calls.append(data))
    cid = prepare(client, provider)
    response = post(client, cid, content="Private financial question, never include it in a push.")
    assert response.status_code == 200
    messages = client.get(f"/api/conversations/{cid}").json()["messages"]
    message_id = messages[-1]["id"]
    assert client.app.state.db.one("SELECT status FROM web_push_deliveries")["status"] == "queued"
    client.portal.call(service.deliver)
    assert calls == [{"type": "reply-completed", "userId": admin["id"], "conversationId": cid, "messageId": message_id}]
    assert "Private financial" not in json.dumps(calls)
    service.enqueue(message_id)
    client.portal.call(service.deliver)
    assert len(calls) == 1
    # Restart recovery does not create duplicate alerts, but recovers a missing checkpoint.
    client.app.state.db.execute("DELETE FROM web_push_deliveries")
    service.enqueue()
    client.portal.call(service.deliver)
    assert len(calls) == 2
    check = client.get("/api/notifications/messages/" + message_id)
    assert check.json() == {"userId": admin["id"], "conversationId": cid, "messageId": message_id}


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",
        "https://127.0.0.1/private",
        "https://fcm.googleapis.com.attacker.test/x",
        "https://fcm.googleapis.com:444/x",
        "https://u:p@fcm.googleapis.com/x",
    ],
)
def test_push_cannot_make_requests_to_arbitrary_or_internal_servers(client, admin, endpoint):
    body = subscription()
    body["endpoint"] = endpoint
    response = client.post("/api/notifications/subscriptions", headers=HEADERS, json=body)
    assert response.status_code == 422
    assert endpoint not in response.text
    assert not client.app.state.db.all("SELECT * FROM web_push_subscriptions")


def test_subscription_keys_invalid_and_logged_out_requests_are_rejected(client, admin):
    body = subscription()
    body["keys"]["auth"] = "!" * 22
    assert client.post("/api/notifications/subscriptions", headers=HEADERS, json=body).status_code == 422
    enable(client)
    assert client.app.state.db.one("SELECT count(*) AS n FROM web_push_subscriptions")["n"] == 1
    client.post("/api/auth/logout", headers=HEADERS)
    assert not client.app.state.db.all("SELECT * FROM web_push_subscriptions")
    assert client.get("/api/notifications/config").status_code == 401


@pytest.mark.parametrize("blocked", ["expired", "inactive"])
def test_expired_session_and_inactive_members_receive_no_push(client, admin, monkeypatch, blocked):
    enable(client)
    service = client.app.state.notifications
    cid = prepare(client, "chatgpt")
    post(client, cid, content="Notification test")
    calls = []
    monkeypatch.setattr(service, "send", lambda *args: calls.append(args))
    if blocked == "expired":
        client.app.state.db.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
    else:
        client.app.state.db.execute("UPDATE users SET active=0 WHERE id=?", (admin["id"],))
    client.portal.call(service.deliver)
    assert calls == []


def test_retry_and_expired_push_endpoint_never_fail_the_reply(client, admin, monkeypatch):
    enable(client)
    service = client.app.state.notifications
    cid = prepare(client, "chatgpt")
    post(client, cid, content="Notification retry")

    def unavailable(*args):
        raise RuntimeError("temporary push outage")

    monkeypatch.setattr(service, "send", unavailable)
    client.portal.call(service.deliver)
    row = client.app.state.db.one("SELECT * FROM web_push_deliveries")
    assert row["status"] == "queued" and row["attempts"] == 1 and row["next_attempt"] > time.time()
    assert client.get(f"/api/conversations/{cid}").json()["messages"][-1]["status"] == "completed"

    class Expired(Exception):
        status_code = 410

    def expired(*args):
        raise Expired()

    monkeypatch.setattr(service, "send", expired)
    client.app.state.db.execute("UPDATE web_push_deliveries SET next_attempt=0")
    client.portal.call(service.deliver)
    assert not client.app.state.db.all("SELECT * FROM web_push_subscriptions")
    assert not client.app.state.db.all("SELECT * FROM web_push_deliveries")


def test_other_members_cannot_read_or_remove_someone_elses_notifications(client, admin):
    body = enable(client)
    cid = prepare(client, "chatgpt")
    post(client, cid, content="Private")
    mid = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["id"]
    # A second account is a Manager with no grants; keep the first session alive like a second device.
    from app.security import hash_password
    from app.db import now

    client.app.state.db.execute(
        "INSERT INTO users VALUES(?,?,?,?,?,?,?)",
        ("other-manager", "other@example.com", "Other", hash_password("other-test-password"), "manager", 1, now()),
    )
    client.cookies.clear()
    client.post(
        "/api/auth/login", headers=HEADERS, json={"email": "other@example.com", "password": "other-test-password"}
    )
    assert client.get("/api/notifications/messages/" + mid).status_code == 404
    client.request("DELETE", "/api/notifications/subscriptions", headers=HEADERS, json={"endpoint": body["endpoint"]})
    assert client.app.state.db.one("SELECT count(*) AS n FROM web_push_subscriptions")["n"] == 1


def test_private_push_details_are_excluded_from_traffic_and_key_survives_restart(client, admin):
    body = enable(client)
    service = client.app.state.notifications
    first = service.public_key()
    assert PushNotifications(client.app.state.settings, client.app.state.db).public_key() == first
    assert service.key_path.stat().st_mode & 0o777 == 0o600
    client.portal.call(client.app.state.traffic.flush)
    logs = json.dumps(client.app.state.db.all("SELECT * FROM traffic_events"))
    assert body["endpoint"] not in logs and body["keys"]["p256dh"] not in logs
    service.key_path.unlink()
    with pytest.raises(OSError):
        service.public_key()


def test_webpush_signs_and_encrypts_with_persisted_key_without_sending_plaintext(client, admin, monkeypatch):
    import requests
    from types import SimpleNamespace

    body = enable(client)
    sent = []

    def post(endpoint, **kwargs):
        sent.append((endpoint, kwargs))
        return SimpleNamespace(status_code=201, text="", headers={})

    monkeypatch.setattr(requests, "post", post)
    client.app.state.notifications.send(
        body, {"type": "reply-completed", "userId": admin["id"], "conversationId": "test", "messageId": "test-message"}
    )
    assert len(sent) == 1
    endpoint, options = sent[0]
    assert endpoint == body["endpoint"] and options["timeout"] == 8
    assert options["headers"]["content-encoding"] == "aes128gcm"
    assert options["headers"]["authorization"].startswith("vapid ")
    assert b"reply-completed" not in options["data"]
    assert b"test-message" not in options["data"]


@pytest.mark.parametrize("provider", ["chatgpt", "claude"])
def test_report_request_notifies_once_after_all_excel_files_are_ready(client, admin, claude, monkeypatch, provider):
    import asyncio
    from app.subscription_pool import PooledRuntime
    from app.schemas import ReportRequest
    from test_excel_reports import wait_report

    enable(client)
    service = client.app.state.notifications
    calls = []
    monkeypatch.setattr(service, "send", lambda sub, data: calls.append(data))
    gates, created = {}, []
    original = PooledRuntime.stream

    async def stream(self, thread_id, content, model=None, output_schema=None, reasoning_effort=None):
        if self.kind == "chat":
            for period in ("January", "February"):
                report = await self.manager.report_handler(
                    self.user_id,
                    ReportRequest(
                        title=period + " monthly report",
                        conversation_id=self.identifier,
                        rows=[{"month": period, "amount": 10}],
                        model=model,
                    ),
                    thread_id,
                    "fixture-report-turn",
                )
                created.append(report["id"])
                gates[report["id"]] = asyncio.Event()
            yield {"type": "done", "status": "completed", "text": "Raportet po përgatiten."}
        else:
            await gates[self.identifier].wait()
            async for event in original(self, thread_id, content, model, output_schema, reasoning_effort):
                yield event

    monkeypatch.setattr(PooledRuntime, "stream", stream)
    cid = prepare(client, provider)
    response = post(client, cid, content="Prepare the monthly reports.")
    events = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    assert events[-1]["notification_ready"] == "waiting"
    assert events[-1]["notification_kind"] == "report"
    detail = client.get(f"/api/conversations/{cid}").json()
    message = detail["messages"][-1]
    assert message["status"] == "completed" and not message["notification_ready"]
    assert message["notification_pending"] and message["report_count"] == 2
    assert client.get("/api/conversations").json()[0]["notification_pending"]
    assert client.get("/api/notifications/messages/" + message["id"]).status_code == 404
    assert not client.app.state.db.all("SELECT * FROM web_push_deliveries")
    for rid in created:
        assert client.get(f"/api/reports/{rid}/export/xlsx").status_code == 409
    client.portal.call(gates[created[0]].set)
    assert wait_report(client, created[0])["status"] == "completed"
    service.enqueue(message["id"])
    client.portal.call(service.deliver)
    assert calls == []  # One file ready is not the whole request ready.
    client.portal.call(gates[created[1]].set)
    assert wait_report(client, created[1])["status"] == "completed"
    for rid in created:
        exported = client.get(f"/api/reports/{rid}/export/xlsx")
        assert exported.status_code == 200 and exported.content.startswith(b"PK")
    detail = client.get(f"/api/conversations/{cid}").json()["messages"][-1]
    assert detail["notification_ready"] and not detail["notification_pending"]
    assert client.app.state.db.one("SELECT status FROM web_push_deliveries")["status"] == "queued"
    client.portal.call(service.deliver)
    assert len(calls) == 1
    check = client.get("/api/notifications/messages/" + message["id"])
    assert check.status_code == 200 and check.json()["reportCount"] == 2
    service.enqueue(message["id"])
    client.portal.call(service.deliver)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "report_status,deleted",
    [
        ("queued", None),
        ("running", None),
        ("failed", None),
        ("blocked", None),
        ("completed", "2026-10-20T12:00:00+00:00"),
    ],
)
def test_incomplete_failed_or_deleted_reports_never_announce_success(
    client, admin, monkeypatch, report_status, deleted
):
    from app.db import now
    from app.completion import report_completion

    enable(client)
    cid = prepare(client, "chatgpt")
    post(client, cid, content="Initial response")
    mid = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["id"]
    db = client.app.state.db
    # Simulate a delayed export associated with this exact request, including an already-queued alert.
    db.execute(
        "INSERT INTO reports(id,user_id,conversation_id,template_id,title,instructions,status,created_at,completed_at,deleted_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("test-export", admin["id"], cid, "executive", "Monthly report", "", report_status, now(), now(), deleted),
    )
    db.execute("INSERT INTO chat_report_jobs VALUES(?,?)", ("test-export", mid))
    calls = []
    monkeypatch.setattr(client.app.state.notifications, "send", lambda *args: calls.append(args))
    client.portal.call(client.app.state.notifications.deliver)
    assert calls == []
    assert not report_completion(db, mid)["ready"]
    assert client.get("/api/notifications/messages/" + mid).status_code == 404
    message = client.get(f"/api/conversations/{cid}").json()["messages"][-1]
    assert not message["notification_ready"]
    assert message["notification_pending"] == (report_status in ("queued", "running") and not deleted)


def test_old_failed_report_does_not_block_a_later_request_in_the_same_conversation(client, admin, monkeypatch):
    from app.db import now

    enable(client)
    cid = prepare(client, "chatgpt")
    post(client, cid, content="Old request")
    old = client.get(f"/api/conversations/{cid}").json()["messages"][-1]["id"]
    db = client.app.state.db
    db.execute(
        "INSERT INTO reports(id,user_id,conversation_id,template_id,title,instructions,status,created_at) VALUES(?,?,?,?,?,?,?,?)",
        ("old-export", admin["id"], cid, "executive", "Old report", "", "failed", now()),
    )
    db.execute("INSERT INTO chat_report_jobs VALUES(?,?)", ("old-export", old))
    post(client, cid, content="New independent question")
    current = client.get(f"/api/conversations/{cid}").json()["messages"][-1]
    assert current["notification_ready"] and current["report_count"] == 0
    calls = []
    monkeypatch.setattr(client.app.state.notifications, "send", lambda sub, data: calls.append(data))
    client.portal.call(client.app.state.notifications.deliver)
    assert [call["messageId"] for call in calls] == [current["id"]]
