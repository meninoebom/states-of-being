"""States of Being — Song Blender API."""

import os
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded

from app.api.process import router as process_router
from app.config import settings
from app.limiter import limiter

# Replicate SDK reads REPLICATE_API_TOKEN from env, not from our settings.
# Ensure it's set in the process environment (pydantic-settings only loads into the class).
os.environ.setdefault("REPLICATE_API_TOKEN", settings.REPLICATE_API_TOKEN)

TEMP_DIR = tempfile.mkdtemp(prefix="sob_")

app = FastAPI(title="Song Blender API")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Max 5 songs per hour."})


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/clips", StaticFiles(directory=TEMP_DIR), name="clips")

# Mount library directory — check configured path first, then git-committed fallback
library_dir = Path(settings.LIBRARY_DIR)
if not library_dir.exists():
    library_dir = Path(__file__).parent.parent.parent / "library"
if library_dir.exists():
    app.mount("/library", StaticFiles(directory=str(library_dir)), name="library")

# Mount frontend if it exists (for local dev and same-origin serving)
frontend_dir = Path(__file__).parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

app.include_router(process_router, prefix="/api")

# Import and include library router after app creation
from app.api.library import router as library_router
app.include_router(library_router, prefix="/api")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


def _cleanup_loop():
    """Delete job directories older than 1 hour, checked every 10 minutes."""
    import logging
    import shutil
    logger = logging.getLogger(__name__)
    while True:
        time.sleep(600)
        cutoff = time.time() - 3600
        try:
            for entry in Path(TEMP_DIR).iterdir():
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
        except Exception:
            logger.warning("Temp cleanup failed", exc_info=True)


_cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True)
_cleanup_thread.start()
