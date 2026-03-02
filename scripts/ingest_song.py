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


def ingest(song_path: str, api_url: str, library_dir: str):
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
    for track in data["tracks"]:
        wav_url = f"{api_url}{track['url']}"
        wav_filename = track["file"]
        mp3_filename = Path(wav_filename).stem + ".mp3"

        print(f"  Downloading {wav_filename}...")
        wav_response = httpx.get(wav_url, timeout=60)
        if wav_response.status_code != 200:
            print(f"  Warning: failed to download {wav_filename}, skipping")
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

    catalog.append({
        "slug": slug,
        "name": song_name,
        "bpm": data["bpm"],
        "time_signature": data["time_signature"],
        "total_loops": data["total_loops"],
        "sections": section_labels,
        "categories": categories,
    })

    catalog_path.write_text(json.dumps(catalog, indent=2))
    print(f"Updated {catalog_path} ({len(catalog)} songs)")
    print("Done!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest a song into the curated library")
    parser.add_argument("song", help="Path to song file (mp3, wav, etc.)")
    parser.add_argument("--api-url", default="https://song-blender-api-production.up.railway.app",
                        help="Song Blender API URL")
    parser.add_argument("--library-dir", default="./library",
                        help="Local library directory (default: ./library)")
    args = parser.parse_args()

    ingest(args.song, args.api_url, args.library_dir)
