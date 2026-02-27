"""Song structure analysis via Replicate all-in-one model."""

import asyncio
import logging
import os

import httpx
import replicate

logger = logging.getLogger(__name__)

ALLIN1_MODEL = "sakemin/all-in-one-music-structure-analyzer:001b4137be6ac67bdc28cb5cffacf128b874f530258d033de23121e785cb7290"


def _run_allin1(audio_path: str) -> list:
    """Sync call to Replicate — runs in a thread."""
    with open(audio_path, "rb") as f:
        return replicate.run(
            ALLIN1_MODEL,
            input={"music_input": f, "visualize": False, "sonify": False},
        )


async def analyze_structure(audio_path: str) -> dict:
    """Get song structure (sections, beats, BPM) from all-in-one analyzer.

    Returns dict with keys: bpm, beats, downbeats, segments.
    Each segment has: start, end, label (intro/verse/chorus/bridge/solo/outro/etc).
    """
    try:
        output = await asyncio.to_thread(_run_allin1, audio_path)
    except Exception as e:
        logger.warning("Song structure analysis failed: %s", e, exc_info=True)
        return {}

    # Output is a list of URLs; first one is the JSON result
    json_url = None
    for item in output:
        url = str(item)
        if url.endswith(".json"):
            json_url = url
            break

    if not json_url:
        logger.warning("No JSON in allin1 output: %s", output)
        return {}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(json_url)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.warning("Failed to fetch allin1 JSON: %s", e)
        return {}
