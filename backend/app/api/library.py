"""Library endpoints — serve pre-processed curated song catalog."""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _library_dir() -> Path:
    return Path(settings.LIBRARY_DIR)


@router.get("/library")
def list_songs():
    """Return the curated song catalog."""
    catalog_path = _library_dir() / "catalog.json"
    if not catalog_path.exists():
        return []
    return json.loads(catalog_path.read_text())


@router.get("/library/{slug}")
def get_song(slug: str):
    """Return full metadata for a single song."""
    metadata_path = _library_dir() / "songs" / slug / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(404, f"Song '{slug}' not found")
    return json.loads(metadata_path.read_text())
