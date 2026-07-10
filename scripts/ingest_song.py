#!/usr/bin/env python3
"""Ingest a song into the curated library.

Usage:
    python scripts/ingest_song.py /path/to/song.mp3 [--api-url URL] [--library-dir DIR]

Calls the Song Blender API to process the song, downloads the WAV loops,
converts them to MP3, and writes metadata + catalog entry to the library dir.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import httpx
from pydub import AudioSegment


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def ingest(song_path: str, api_url: str, library_dir: str,
           artist: str, license_: str, cover: str | None = None):
    song_file = Path(song_path)
    if not song_file.exists():
        print(f"Error: {song_path} not found")
        sys.exit(1)

    lib = Path(library_dir)
    lib.mkdir(parents=True, exist_ok=True)

    # 1. Process song via API
    print(f"Processing {song_file.name}...")
    with open(song_file, "rb") as f:
        response = httpx.post(
            f"{api_url}/api/process",
            files={"file": (song_file.name, f)},
            timeout=300,
        )

    if response.status_code != 200:
        print(f"API error {response.status_code}: {response.text}")
        sys.exit(1)

    data = response.json()
    job_id = data["job_id"]
    song_name = data["name"]
    slug = slugify(song_name)

    print(f"Got {data['total_loops']} loops for '{song_name}' (job: {job_id})")

    # 2. Create song directory
    song_dir = lib / "songs" / slug
    loops_dir = song_dir / "loops"
    loops_dir.mkdir(parents=True, exist_ok=True)

    # 3. Download WAV loops and convert to MP3
    failed_files = []
    for track in data["tracks"]:
        wav_url = f"{api_url}{track['url']}"
        wav_filename = track["file"]
        mp3_filename = Path(wav_filename).stem + ".mp3"

        print(f"  Downloading {wav_filename}...")
        wav_response = httpx.get(wav_url, timeout=60)
        if wav_response.status_code != 200:
            print(f"  ERROR: failed to download {wav_filename} (HTTP {wav_response.status_code}), removing from metadata")
            failed_files.append(track["file"])
            continue

        # Write WAV temporarily, convert to MP3
        tmp_wav = song_dir / wav_filename
        tmp_wav.write_bytes(wav_response.content)

        audio = AudioSegment.from_wav(str(tmp_wav))
        mp3_path = loops_dir / mp3_filename
        audio.export(str(mp3_path), format="mp3", bitrate="192k")
        tmp_wav.unlink()

        # Update track metadata
        track["file"] = mp3_filename
        track["url"] = f"/library/songs/{slug}/loops/{mp3_filename}"

    # Remove failed tracks from metadata
    if failed_files:
        data["tracks"] = [t for t in data["tracks"] if t["file"] not in failed_files]
        data["total_loops"] = len(data["tracks"])
        print(f"  Removed {len(failed_files)} failed tracks from metadata")

    # 3b. Enrich with provenance metadata (#21). Duration comes from the
    # analysis (latest section end); artist/license are supplied by the caller.
    section_ends = [s["end"] for s in data.get("sections", []) if "end" in s]
    duration = round(max(section_ends), 2) if section_ends else None
    data["artist"] = artist
    data["license"] = license_
    if duration is not None:
        data["duration"] = duration
    if cover:
        data["cover"] = cover

    # 4. Write metadata.json
    metadata_path = song_dir / "metadata.json"
    metadata_path.write_text(json.dumps(data, indent=2))
    print(f"Wrote {metadata_path}")

    # 5. Update catalog.json
    catalog_path = lib / "catalog.json"
    catalog = []
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text())

    # Remove existing entry for this slug if re-ingesting
    catalog = [s for s in catalog if s["slug"] != slug]

    # Collect unique section labels and categories
    section_labels = list(dict.fromkeys(t["section"] for t in data["tracks"]))
    categories = list(dict.fromkeys(t["category"] for t in data["tracks"]))

    entry = {
        "slug": slug,
        "name": song_name,
        "artist": artist,
        "license": license_,
        "bpm": data["bpm"],
        "time_signature": data["time_signature"],
        "total_loops": data["total_loops"],
        "sections": section_labels,
        "categories": categories,
    }
    if duration is not None:
        entry["duration"] = duration
    if cover:
        entry["cover"] = cover
    catalog.append(entry)

    catalog_path.write_text(json.dumps(catalog, indent=2))
    print(f"Updated {catalog_path} ({len(catalog)} songs)")
    print("Done!")


PROD_API_URL = "https://song-blender-api-production.up.railway.app"
LOCAL_API_URL = "http://127.0.0.1:8000"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ingest one or more songs into the curated library. "
                    "See CLAUDE.md 'Adding / re-ingesting songs' for the full flow.")
    parser.add_argument("song", nargs="+", help="Path(s) to song file(s) (mp3, wav, etc.)")
    parser.add_argument("--api-url", default=None,
                        help=f"Song Blender API URL (default: {PROD_API_URL})")
    parser.add_argument("--local", action="store_true",
                        help=f"Shortcut for --api-url {LOCAL_API_URL} (a locally-run API, "
                             "so you ingest with your in-progress code changes).")
    parser.add_argument("--library-dir", default="./library",
                        help="Local library directory (default: ./library)")
    parser.add_argument("--artist", default="Unknown",
                        help="Song artist, if known (default: 'Unknown').")
    parser.add_argument("--license", default="unlicensed", dest="license_",
                        help="Usage terms, if known (default: 'unlicensed'). Source real "
                             "licenses before any commercial release; see docs/LEGAL.md "
                             "'Current Posture'.")
    parser.add_argument("--cover", default=None,
                        help="Optional cover image filename (placed in the song dir)")
    args = parser.parse_args()

    api_url = args.api_url or (LOCAL_API_URL if args.local else PROD_API_URL)
    for song_path in args.song:
        ingest(song_path, api_url, args.library_dir,
               args.artist, args.license_, args.cover)
