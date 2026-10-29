"""Hana's animated introduction plays once per member, on any device."""

from conftest import HEADERS
from test_application import create_member, sign_in_member


def test_introduction_is_pending_until_seen_and_stays_seen_after_login(client, admin):
    assert admin["intro_pending"] is True
    assert client.get("/api/auth/status").json()["user"]["intro_pending"] is True
    assert client.post("/api/auth/introduction", headers=HEADERS).json() == {"intro_pending": False}
    assert client.get("/api/auth/status").json()["user"]["intro_pending"] is False
    # Marking it again is harmless.
    assert client.post("/api/auth/introduction", headers=HEADERS).status_code == 200

    create_member(client)
    client.post("/api/auth/logout", headers=HEADERS)
    sign_in_member(client)
    member = client.get("/api/auth/status").json()["user"]
    assert member["email"] == "member@example.com" and member["intro_pending"] is True


def test_introduction_requires_a_session(client, admin):
    client.post("/api/auth/logout", headers=HEADERS)
    assert client.post("/api/auth/introduction", headers=HEADERS).status_code == 401
