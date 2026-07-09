"""Library endpoints — serve pre-processed curated song catalog."""

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.catalog import CatalogValidationError, load_catalog
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _library_dir() -> Path:
    d = Path(settings.LIBRARY_DIR)
    if not d.exists():
        d = Path(__file__).parent.parent.parent.parent / "library"
    return d


@router.get("/library")
def list_songs():
    """Return the curated song catalog.

    The catalog is validated on load: an entry missing its required `license`
    field is a server-side data error, so we fail loud (500) rather than serve
    it. Validation checks presence only. A placeholder license (pending the
    human legal review in #11/#22) still passes and is served.
    """
    catalog_path = _library_dir() / "catalog.json"
    try:
        return load_catalog(catalog_path)
    except CatalogValidationError:
        logger.exception("Catalog failed schema validation")
        raise HTTPException(500, "Song catalog is misconfigured")


@router.get("/library/{slug}")
def get_song(slug: str):
    """Return full metadata for a single song."""
    if not re.match(r'^[a-z0-9][a-z0-9-]*$', slug):
        raise HTTPException(400, "Invalid song slug")
    metadata_path = _library_dir() / "songs" / slug / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(404, f"Song '{slug}' not found")
    return json.loads(metadata_path.read_text())
