"""States of Being — Song Blender API."""

import os
import tempfile
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.process import router as process_router
from app.config import settings

TEMP_DIR = tempfile.mkdtemp(prefix="sob_")

app = FastAPI(title="Song Blender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/clips", StaticFiles(directory=TEMP_DIR), name="clips")
app.include_router(process_router, prefix="/api")


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok"}


def _cleanup_loop():
    """Delete files older than 1 hour from the temp directory every 10 minutes."""
    while True:
        time.sleep(600)
        cutoff = time.time() - 3600
        try:
            for entry in Path(TEMP_DIR).iterdir():
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    import shutil

                    shutil.rmtree(entry, ignore_errors=True)
        except Exception:
            pass


_cleanup_thread = threading.Thread(target=_cleanup_loop, daemon=True)
_cleanup_thread.start()
