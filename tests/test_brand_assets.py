from pathlib import Path
import mimetypes

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_official_logos_and_favicon_are_served_as_images_before_spa_fallback(tmp_path, monkeypatch):
    frontend = tmp_path / "frontend"
    brand = frontend / "brand"
    brand.mkdir(parents=True)
    public = Path(__file__).resolve().parents[1] / "frontend" / "public" / "brand"
    for name in ("duka-group-logo.webp", "duka-group-logo-light.webp", "duka-group-icon-32.webp", "duka-group-icon-192.webp", "duka-group-touch-icon.webp"):
        (brand / name).write_bytes((public / name).read_bytes())
    (frontend / "index.html").write_text("<html>application</html>")
    settings = Settings(data_dir=tmp_path / "data", frontend_dir=frontend, voice_enabled=False, env_file=None)
    monkeypatch.setitem(mimetypes.types_map, ".webp", "application/octet-stream")
    with TestClient(create_app(settings)) as client:
        for path in brand.iterdir():
            response = client.get("/brand/" + path.name)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("image/webp")
            assert response.content == path.read_bytes()
        assert client.get("/brand/missing.webp").status_code == 404
        assert "application" in client.get("/conversations").text
