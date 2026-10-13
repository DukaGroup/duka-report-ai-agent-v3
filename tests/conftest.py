from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

HEADERS = {"X-Duka-Request": "1", "Origin": "http://localhost:8080"}


@pytest.fixture
def app(tmp_path):
    fixture = Path(__file__).parent / "fake_codex.py"
    fixture.chmod(0o755)
    settings = Settings(
        data_dir=tmp_path / "data",
        frontend_dir=tmp_path / "frontend",
        codex_binary=str(fixture.resolve()),
        voice_enabled=False,
        env_file=None,
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def admin(client):
    response = client.post(
        "/api/auth/setup",
        json={"email": "admin@example.com", "name": "Admin", "password": "a-long-test-password"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    return response.json()
