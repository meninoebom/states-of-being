"""Main processing endpoint — orchestrates the full song blender pipeline."""

import asyncio
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app.config import settings
from app.limiter import limiter
from app.spend_cap import DailySpendTracker

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}

# Global daily Replicate spend cap, shared across all requests to this process.
# In-memory and single-instance only — see app/spend_cap.py for the limitation.
spend_tracker = DailySpendTracker(cap_usd=settings.DAILY_SPEND_CAP_USD)


@router.post("/process")
@limiter.limit("5/hour")
async def process_song(request: Request, file: UploadFile):
    """Upload a song and get back categorized, choppable loops.

    Pipeline: upload -> [parallel: structure analysis + stem separation] -> per-stem chop -> categorize -> select
    """
    if not file.filename:
        raise HTTPException(400, "Filename is required")
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format. Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB}MB limit")

    # Global daily spend cap: reserve this request's estimated Replicate cost
    # BEFORE doing any paid work. If the day's budget is exhausted, reject now.
    # Note: budget is reserved up front, so a request that later fails still
    # counts against the cap. This is deliberate — we err toward protecting the
    # bill rather than risking an unbounded retry loop.
    if not spend_tracker.try_spend(settings.COST_PER_REQUEST_USD):
        logger.warning("Daily spend cap reached; rejecting request")
        raise HTTPException(
            503,
            "Daily processing limit reached. Please try again tomorrow (resets at 00:00 UTC).",
        )

    from app.main import TEMP_DIR

    job_id = uuid.uuid4().hex[:8]
    job_dir = Path(TEMP_DIR) / job_id
    job_dir.mkdir(parents=True)

    try:
        input_path = job_dir / f"input{ext}"
        input_path.write_bytes(contents)

        from app.services.song_analyzer import analyze_structure
        from app.services.stem_separator import separate_stems
        from app.services.loop_chopper import chop_stem
        from app.services.categorizer import auto_select, categorize_loops

        # 1. Run structure analysis first, then stem separation
        # (Sequential to avoid Replicate rate limits with low credit)
        structure = await analyze_structure(str(input_path))
        stems = await separate_stems(str(input_path), str(job_dir))

        # Extract data from structure analysis
        sections = structure.get("segments", [])
        bpm = structure.get("bpm", 120.0)
        downbeats = structure.get("downbeats", [])
        beats = structure.get("beats", [])

        # Fallback: if structure analysis failed, create one big section
        if not sections:
            logger.warning("No song structure detected, using single section fallback")
            from app.services.beat_analyzer import analyze_beats
            beat_grid = analyze_beats(str(input_path))
            bpm = beat_grid.bpm
            downbeats = beat_grid.downbeats
            beats = beat_grid.beats
            # Estimate duration from the audio file
            import librosa
            duration = float(librosa.get_duration(path=str(input_path)))
            sections = [{"start": 0.0, "end": duration, "label": "full"}]

        # Derive time signature from beats/downbeats
        time_signature = 4
        if len(downbeats) >= 2 and len(beats) >= 2:
            beats_per_bar = []
            for i in range(len(downbeats) - 1):
                count = sum(1 for b in beats if downbeats[i] <= b < downbeats[i + 1])
                beats_per_bar.append(count)
            if beats_per_bar:
                import numpy as np
                time_signature = int(np.median(beats_per_bar))

        # 2. Chop each stem using song sections
        loops_by_stem: dict[str, list] = {}
        for stem_name, stem_path in stems.items():
            loops = chop_stem(
                stem_path=stem_path,
                sections=sections,
                output_dir=str(job_dir),
                stem_name=stem_name,
                downbeats=downbeats,
            )
            loops_by_stem[stem_name] = loops

        # 3. Categorize and auto-select (2 per category per section)
        categorized = categorize_loops(loops_by_stem)
        all_tracks = auto_select(categorized)

        song_name = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()
        for track in all_tracks:
            track["url"] = f"/clips/{job_id}/{track['file']}"

        # Filter sections to only include non-trivial ones in response
        response_sections = [
            {"label": s["label"], "start": s["start"], "end": s["end"]}
            for s in sections
            if s.get("label") not in ("start", "end")
        ]

        return {
            "job_id": job_id,
            "name": song_name,
            "bpm": bpm,
            "time_signature": time_signature,
            "sections": response_sections,
            "total_loops": len(all_tracks),
            "tracks": all_tracks,
        }

    except HTTPException:
        raise
    except Exception:
        logger.exception("Processing failed for job %s", job_id)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, "Processing failed — please try again or use a different file")
