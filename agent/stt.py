"""Распознавание голосовых сообщений (Whisper, работает локально на этом компьютере)."""
from functools import lru_cache
from pathlib import Path

from . import config


@lru_cache(maxsize=1)
def _model():
    from faster_whisper import WhisperModel  # загружается долго — только при первом вызове
    return WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")


def transcribe(path: Path) -> str:
    segments, _ = _model().transcribe(str(path), language="ru", vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()
