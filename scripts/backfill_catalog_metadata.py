#!/usr/bin/env python3
"""Backfill enriched catalog metadata (#21) onto the curated library.

Adds `artist`, `duration`, `license` (required), and optional `cover` to both
each song's `metadata.json` and the top-level `catalog.json`.

- `duration` is computed from the analysis already on disk (the max section end
  time), so it is a real value, not a guess.
- `artist` and `license` are preserved if already present. Where a real value
  cannot be verified, a clearly-marked placeholder is written so a human can
  fill it in. License is legally sensitive (see issues #11 / #22); we never
  fabricate a value.
- `cover` is only written when a cover image file exists for the song.

Idempotent: re-running it will not overwrite already-filled artist/license
values, and recomputes duration each time.

Usage:
    python scripts/backfill_catalog_metadata.py [--library-dir DIR]
"""

import argparse
import json
from pathlib import Path

# Placeholder written when a real value cannot be verified. Kept as a module
# constant so the picker/tests can recognise "not yet reviewed" values.
NEEDS_REVIEW = "UNKNOWN - NEEDS REVIEW"

COVER_NAMES = ("cover.jpg", "cover.jpeg", "cover.png", "cover.webp")


def compute_duration(metadata: dict) -> float | None:
    """Song length in seconds, from the latest section end time on disk."""
    sections = metadata.get("sections") or []
    ends = [s["end"] for s in sections if isinstance(s, dict) and "end" in s]
    if not ends:
        return None
    return round(max(ends), 2)


def find_cover(song_dir: Path) -> str | None:
    for name in COVER_NAMES:
        if (song_dir / name).exists():
            return name
    return None


def backfill(library_dir: str) -> None:
    lib = Path(library_dir)
    catalog_path = lib / "catalog.json"
    catalog = json.loads(catalog_path.read_text())

    for entry in catalog:
        slug = entry["slug"]
        song_dir = lib / "songs" / slug
        metadata_path = song_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text())

        duration = compute_duration(metadata)
        artist = metadata.get("artist") or entry.get("artist") or NEEDS_REVIEW
        license_ = metadata.get("license") or entry.get("license") or NEEDS_REVIEW
        cover = find_cover(song_dir)

        # Enrich both the per-song metadata and the catalog entry so the two
        # stay in sync (the catalog is what the picker reads).
        for target in (metadata, entry):
            target["artist"] = artist
            target["license"] = license_
            if duration is not None:
                target["duration"] = duration
            if cover is not None:
                target["cover"] = cover

        metadata_path.write_text(json.dumps(metadata, indent=2))
        flag = "  <-- NEEDS REVIEW" if NEEDS_REVIEW in (artist, license_) else ""
        print(f"{slug}: duration={duration}s artist={artist!r} license={license_!r}{flag}")

    catalog_path.write_text(json.dumps(catalog, indent=2))
    print(f"Updated {catalog_path} ({len(catalog)} songs)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill catalog metadata (#21)")
    parser.add_argument("--library-dir", default="./library",
                        help="Library directory (default: ./library)")
    args = parser.parse_args()
    backfill(args.library_dir)
