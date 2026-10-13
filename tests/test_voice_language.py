from types import SimpleNamespace
from unittest.mock import AsyncMock

from conftest import HEADERS
from app.voice import VoiceService


def test_albanian_transcription_language_is_forwarded_and_invalid_languages_rejected(client, admin):
    service = client.app.state.voice
    service.transcribe = AsyncMock(return_value={"text": "Përshëndetje", "language": "sq"})
    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("recording.webm", b"fixture-audio", "audio/webm")},
        data={"language": "sq"},
        headers=HEADERS,
    )
    assert response.status_code == 200 and response.json()["language"] == "sq"
    service.transcribe.assert_awaited_once_with(b"fixture-audio", ".webm", "sq")
    response = client.post(
        "/api/voice/transcribe",
        files={"file": ("recording.webm", b"fixture-audio", "audio/webm")},
        data={"language": "invalid"},
        headers=HEADERS,
    )
    assert response.status_code == 422


def test_auto_language_overrides_server_default_and_shqip_is_used_without_translation(tmp_path, monkeypatch):
    class Model:
        def transcribe(self, path, **options):
            calls.append(options)
            return [SimpleNamespace(text=" Përshëndetje ")], SimpleNamespace(language="sq")

    import sys

    calls = []
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    service = VoiceService(SimpleNamespace(whisper_language="en"))
    service.model = Model()
    assert service._transcribe(b"audio", ".webm", "sq")["text"] == "Përshëndetje"
    assert calls[-1]["language"] == "sq"
    service._transcribe(b"audio", ".webm", "auto")
    assert calls[-1]["language"] is None
