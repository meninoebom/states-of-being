"""Stem separation via Replicate Demucs model."""

import asyncio
import logging
import os
from pathlib import Path

import httpx
import replicate

logger = logging.getLogger(__name__)

# Demucs v4 (htdemucs) on Replicate
DEMUCS_MODEL = "cjwbw/demucs"

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

    # Replicate Demucs returns a dict of stem_name -> URL,
    # or sometimes a flat URL string per stem. Normalize both.
    stem_urls: dict[str, str] = {}
    if isinstance(output, dict):
        stem_urls = {k: v for k, v in output.items() if isinstance(v, str)}
    elif isinstance(output, list):
        # Fallback: positional list matching STEM_NAMES order
        for name, url in zip(STEM_NAMES, output):
            if isinstance(url, str):
                stem_urls[name] = url

    if not stem_urls:
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
