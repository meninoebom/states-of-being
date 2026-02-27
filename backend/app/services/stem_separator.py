"""Stem separation via Replicate Demucs model."""

import asyncio
import logging
import os
from pathlib import Path

import httpx
import replicate

logger = logging.getLogger(__name__)

# Demucs v4 (htdemucs) on Replicate
DEMUCS_MODEL = "ryan5453/demucs:5a7041cc9b82e5a558fea6b3d7b12dea89625e89da33f0447bd727c2d0ab9e77"

STEM_NAMES = ["drums", "bass", "vocals", "other"]


def _run_demucs(audio_path: str) -> dict | list:
    """Sync call to Replicate — runs in a thread to avoid blocking the event loop."""
    with open(audio_path, "rb") as f:
        return replicate.run(DEMUCS_MODEL, input={"audio": f})


async def separate_stems(audio_path: str, output_dir: str) -> dict[str, str]:
    """Send audio to Replicate Demucs and download separated stems. Returns {stem_name: local_path}."""
    os.makedirs(output_dir, exist_ok=True)

    try:
        output = await asyncio.to_thread(_run_demucs, audio_path)
    except Exception as e:
        raise RuntimeError(f"Stem separation service error: {type(e).__name__}") from e

    # Replicate returns dict of stem_name -> URL (str or FileOutput object).
    # Convert all values to plain URL strings.
    stem_urls: dict[str, str] = {}
    if isinstance(output, dict):
        for k, v in output.items():
            url = str(v)
            if url.startswith("http"):
                stem_urls[k] = url
    elif isinstance(output, list):
        for name, v in zip(STEM_NAMES, output):
            url = str(v)
            if url.startswith("http"):
                stem_urls[name] = url

    if not stem_urls:
        logger.error("Unexpected Demucs output: %s", output)
        raise RuntimeError(f"Unexpected Demucs output format: {type(output)}")

    result: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=120) as client:
        for stem_name, url in stem_urls.items():
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise RuntimeError(f"Failed to download stem '{stem_name}': {e}") from e
            ext = Path(url.split("?")[0]).suffix or ".wav"
            local_path = os.path.join(output_dir, f"{stem_name}{ext}")
            with open(local_path, "wb") as f:
                f.write(resp.content)
            result[stem_name] = local_path

    return result
