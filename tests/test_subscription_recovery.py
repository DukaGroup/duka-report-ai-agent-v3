import json


def test_saved_subscription_recovers_without_new_login_or_process_restart(client, admin):
    home = client.app.state.settings.data_dir / "codex" / admin["id"]
    home.mkdir(parents=True)
    credential = home / "fixture-account.json"
    credential.write_text(json.dumps({"type": "chatgpt", "email": "fixture@example.com", "planType": "plus"}))
    offline = home / "network-offline"
    offline.touch()

    unavailable = client.get("/api/subscription").json()
    assert unavailable["available"] is False
    assert unavailable["connected"] is False
    assert unavailable["error"] == "workspace routing discovery failed"
    runtime = client.app.state.manager.runtimes[admin["id"]]
    original_process = runtime.process

    offline.unlink()
    recovered = client.get("/api/subscription").json()
    assert recovered["connected"] is True and recovered["available"] is True
    assert runtime.process is original_process
    assert credential.exists()
    assert client.get("/api/subscription/models").status_code == 200
    assert not client.app.state.db.all("SELECT id FROM audit_events WHERE action='subscription.login_started'")
