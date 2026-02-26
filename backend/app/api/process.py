"""Main processing endpoint — orchestrates the full song blender pipeline."""

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile

from app.config import settings

router = APIRouter()

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


@router.post("/process")
async def process_song(file: UploadFile):
    """Upload a song and get back categorized, choppable loops.

    Pipeline: upload -> stem separation -> beat analysis -> phrase detection -> chop -> categorize -> auto-select
    """
    # Validate file extension
    if not file.filename:
        raise HTTPException(400, "Filename is required")
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported format. Accepted: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

    # Validate file size
    contents = await file.read()
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(413, f"File exceeds {settings.MAX_UPLOAD_MB}MB limit")

    # Late import to avoid circular dependency at module level
    from app.main import TEMP_DIR

    job_id = uuid.uuid4().hex[:8]
    job_dir = Path(TEMP_DIR) / job_id
    job_dir.mkdir(parents=True)

    try:
        # Save uploaded file
        input_path = job_dir / f"input{ext}"
        input_path.write_bytes(contents)

        # Import service functions (built by other agents)
        from app.services.stem_separator import separate_stems
        from app.services.beat_analyzer import analyze_beats
        from app.services.loop_chopper import chop_stem, find_phrase_boundaries
        from app.services.categorizer import auto_select, categorize_loops

        # 1. Separate stems via Replicate
        stems = await separate_stems(str(input_path), str(job_dir))

        # 2. Analyze beats on original audio
        beat_grid = analyze_beats(str(input_path))

        # 3. Find phrase boundaries
        boundaries = find_phrase_boundaries(
            str(input_path), beat_grid.downbeats, bars_per_phrase=4
        )

        # 4. Chop each stem into loops
        loops_by_stem: dict[str, list] = {}
        for stem_name, stem_path in stems.items():
            loops = chop_stem(
                stem_path=stem_path,
                phrase_boundaries=boundaries,
                output_dir=str(job_dir),
                stem_name=stem_name,
                downbeats=beat_grid.downbeats,
            )
            loops_by_stem[stem_name] = loops

        # 5. Categorize and auto-select
        categorized = categorize_loops(loops_by_stem)
        selected = auto_select(categorized)

        # Build response — add clip URLs to each track
        song_name = Path(file.filename).stem.replace("_", " ").replace("-", " ").title()
        for track in selected:
            track["url"] = f"/clips/{job_id}/{track['file']}"

        return {
            "job_id": job_id,
            "name": song_name,
            "bpm": beat_grid.bpm,
            "time_signature": beat_grid.time_signature,
            "total_loops": len(selected),
            "tracks": selected,
        }

    except HTTPException:
        raise
    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, f"Processing failed: {e}")
