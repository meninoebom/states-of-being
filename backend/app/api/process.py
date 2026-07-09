"""Main processing endpoint — orchestrates the full song blender pipeline."""

import asyncio
import logging
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app import telemetry
from app.config import settings
from app.exceptions import UpstreamServiceError
from app.limiter import limiter
from app.spend_cap import DailySpendTracker
from app.upload_validation import (
    UploadValidationError,
    probe_duration,
    stream_to_disk,
    validate_duration,
    validate_extension,
)

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

    Pipeline: validate -> reserve spend -> [structure analysis + stem separation] -> per-stem chop -> categorize -> select

    Error taxonomy:
      - UploadValidationError -> 4xx: the client's input is bad (wrong type,
        oversized, undecodable, too long). Rejected BEFORE any Replicate spend.
      - spend cap reached -> 503: we are healthy but out of daily budget.
      - UpstreamServiceError -> 502: Replicate (Demucs) timed out or errored.
      - any other exception -> 500: an unexpected pipeline bug on our side.
    """
    from app.main import TEMP_DIR

    job_id = uuid.uuid4().hex[:8]
    job_dir = Path(TEMP_DIR) / job_id

    # `stage` tracks how far the pipeline got, so a failure log pinpoints where it
    # died. `started` measures wall-clock duration for the same log line.
    stage = "validate"
    started = time.monotonic()

    try:
        # --- Validate cheaply, BEFORE spending on Replicate ---
        ext = validate_extension(file.filename, SUPPORTED_EXTENSIONS)
        job_dir.mkdir(parents=True)
        input_path = job_dir / f"input{ext}"

        # Stream to disk with an enforced byte cap (never buffer the whole file
        # in RAM), then decode-probe for corruption and over-length audio.
        max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
        await stream_to_disk(file.read, str(input_path), max_bytes)
        duration = await asyncio.to_thread(probe_duration, str(input_path))
        validate_duration(duration, settings.MAX_DURATION_SEC)

        # --- Reserve the daily Replicate budget only once input is known-good ---
        # A rejected reservation still counts nothing against the cap; a reserved
        # request that later fails does count. We err toward protecting the bill.
        stage = "spend_reserve"
        if not spend_tracker.try_spend(settings.COST_PER_REQUEST_USD):
            logger.warning("Daily spend cap reached; rejecting request")
            raise HTTPException(
                503,
                "Daily processing limit reached. Please try again tomorrow (resets at 00:00 UTC).",
            )

        from app.services.song_analyzer import analyze_structure
        from app.services.stem_separator import separate_stems
        from app.services.loop_chopper import chop_stem
        from app.services.categorizer import auto_select, categorize_loops

        # 1. Run structure analysis first, then stem separation
        # (Sequential to avoid Replicate rate limits with low credit)
        stage = "structure_analysis"
        structure = await analyze_structure(str(input_path))
        stage = "stem_separation"
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
            # Reuse the duration already probed during validation (line above);
            # no need to decode the file a second time.
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
        stage = "chop"
        loops_by_stem: dict[str, list] = {}
        for stem_name, stem_path in stems.items():
            loops = chop_stem(
                stem_path=stem_path,
                sections=sections,
                output_dir=str(job_dir),
                stem_name=stem_name,
                downbeats=downbeats,
                bpm=bpm,
                time_signature=time_signature,
            )
            loops_by_stem[stem_name] = loops

        # 3. Categorize and auto-select (2 per category per section)
        stage = "categorize"
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

    except UploadValidationError as e:
        # Bad user input, rejected before (or without) any Replicate spend.
        telemetry.log_pipeline_failure(
            job_id=job_id, stage=stage, http_status=e.status_code, error=e,
            duration_sec=time.monotonic() - started,
        )
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(e.status_code, e.detail) from e
    except UpstreamServiceError as e:
        # Replicate timed out or errored — distinct from a bug on our side.
        # Keep the traceback in logs too: the wrapped exception's cause pinpoints
        # which upstream call died, which the structured line alone does not.
        logger.warning("Upstream (Replicate) failure for job %s", job_id, exc_info=True)
        telemetry.log_pipeline_failure(
            job_id=job_id, stage=stage, http_status=502, error=e,
            duration_sec=time.monotonic() - started,
        )
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(
            502, "Audio processing service is unavailable or timed out. Please try again later."
        )
    except HTTPException as e:
        # Already-mapped statuses (e.g. the 503 spend cap). Log with the real status.
        telemetry.log_pipeline_failure(
            job_id=job_id, stage=stage, http_status=e.status_code, error=e,
            duration_sec=time.monotonic() - started,
        )
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except Exception as e:
        # Unexpected bug on our side. Keep the full traceback in logs too.
        logger.exception("Processing failed for job %s", job_id)
        telemetry.log_pipeline_failure(
            job_id=job_id, stage=stage, http_status=500, error=e,
            duration_sec=time.monotonic() - started,
        )
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, "Processing failed — please try again or use a different file")
