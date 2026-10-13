"""Озвучка текста (бесплатные голоса Microsoft Edge)."""
import asyncio
from pathlib import Path

import edge_tts

from . import config


async def synthesize(text: str, out: Path, attempts: int = 4) -> Path:
    # Сервис озвучки иногда разово не отвечает — пробуем ещё раз.
    for attempt in range(1, attempts + 1):
        try:
            await edge_tts.Communicate(text, config.VOICE, rate=config.VOICE_RATE).save(str(out))
            return out
        except edge_tts.exceptions.EdgeTTSException:
            if attempt == attempts:
                raise
            await asyncio.sleep(5 * attempt)
    return out
