"""Catalog metadata schema — validation and loading for the curated library.

The catalog (``library/catalog.json``) is the list surfaced to the song picker.
Each entry describes one curated song. Beyond the musical fields (bpm, sections,
categories) it carries provenance metadata added in #21:

- ``artist``   — who made the song (string; "Unknown" when unverified)
- ``duration`` — song length in seconds (number)
- ``license``  — REQUIRED to be present so every song states *some* terms.
                 Validation checks presence only, not correctness: a placeholder
                 like "unlicensed" (the default for the personal/dev-use curated
                 library) passes and is served; a blank/missing license is
                 rejected. Sourcing properly-licensed songs is a pre-commercial
                 task, not a blocker at the current small, free scale — see
                 docs/LEGAL.md "Current Posture".
- ``cover``    — optional path/URL to a cover image (omitted when none exists)

``validate_song_entry`` and ``load_catalog`` are kept dependency-free (no
network, no audio libraries) so they are cheap to unit-test and safe to call on
every ``/library`` request.
"""

from __future__ import annotations

import json
from pathlib import Path

# Fields every catalog entry must carry. ``license`` is here so every song
# states its terms explicitly (even if just "unlicensed"), rather than leaving
# provenance silently absent.
REQUIRED_FIELDS = ("slug", "name", "license")


class CatalogValidationError(Exception):
    """A catalog entry is missing a required field (e.g. ``license``)."""


def validate_song_entry(entry: dict, *, source: str = "") -> None:
    """Raise ``CatalogValidationError`` if a required field is absent or blank.

    A value counts as absent when it is missing, ``None``, or (for strings)
    whitespace-only. This checks presence, not correctness: a placeholder
    license string passes. ``source`` is an optional label (e.g.
    ``catalog.json[2]``) woven into the error message to locate bad data.
    """
    missing = []
    for field in REQUIRED_FIELDS:
        value = entry.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field)
    if missing:
        where = f" in {source}" if source else ""
        raise CatalogValidationError(
            f"Catalog entry{where} is missing required field(s): "
            f"{', '.join(missing)}"
        )


def load_catalog(catalog_path: Path | str) -> list[dict]:
    """Read and validate the catalog JSON, returning its entries.

    Returns an empty list when the file does not exist (an empty library is a
    valid state). Raises ``CatalogValidationError`` if any entry is missing a
    required field, so an entry with no license field at all can never be
    served. (A placeholder license value still passes; see module docstring.)
    """
    path = Path(catalog_path)
    if not path.exists():
        return []
    entries = json.loads(path.read_text())
    for i, entry in enumerate(entries):
        validate_song_entry(entry, source=f"{path.name}[{i}]")
    return entries
