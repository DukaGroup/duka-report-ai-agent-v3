import asyncio
import importlib.util
import tempfile
from pathlib import Path


class VoiceService:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.lock = asyncio.Lock()

    def status(self):
        installed = importlib.util.find_spec("faster_whisper") is not None
        return {
            "available": self.settings.voice_enabled and installed,
            "engine": "local-whisper",
            "model": self.settings.whisper_model,
            "loaded": self.model is not None,
            "language": self.settings.whisper_language,
            "note": "First transcription downloads the local model. Speech playback uses your device's voices.",
        }

    async def transcribe(self, audio: bytes, suffix: str, language=None):
        if not self.status()["available"]:
            raise ValueError(
                "Local speech transcription is unavailable. Install requirements-voice.txt and enable VOICE_ENABLED."
            )
        async with self.lock:
            return await asyncio.to_thread(self._transcribe, audio, suffix, language)

    def _transcribe(self, audio, suffix, language=None):
        from faster_whisper import WhisperModel

        if self.model is None:
            self.model = WhisperModel(
                self.settings.whisper_model,
                device="cpu",
                compute_type="int8",
                download_root=str(self.settings.data_dir / "speech-cache"),
            )
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio)
            path = Path(f.name)
        try:
            segments, info = self.model.transcribe(
                str(path),
                language=None if language == "auto" else language or self.settings.whisper_language,
                vad_filter=True,
            )
            return {"text": " ".join(s.text.strip() for s in segments), "language": info.language}
        finally:
            path.unlink(missing_ok=True)
