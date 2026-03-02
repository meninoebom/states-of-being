# States of Being — Song Blender

## What Is This?

Two things in one repo:

1. **Calm Mirror** (`index.html`) — A browser-based biofeedback experiment. Webcam → MediaPipe Pose → movement analysis → real-time Tone.js music. Single HTML file, no build step.

2. **Song Blender API** (`backend/`) — A standalone FastAPI service that processes uploaded songs into categorized, section-aware loops. Deployed on Railway. Designed as an API that any web app (including States of Being) can call.

## Song Blender API

### Architecture

```
Upload song → [sequential: allin1 structure + Demucs stems] → chop → filter → categorize → select
```

- **Demucs** (Replicate, `ryan5453/demucs`) — Separates song into 4 stems: drums, bass, vocals, other (~$0.035/song)
- **allin1** (Replicate, `sakemin/all-in-one-music-structure-analyzer`) — Detects song sections with labels: intro/verse/chorus/bridge/solo/outro (~$0.10/song)
- **Post-processing** (our code) — Where all the taste lives. Chopping, energy filtering, vocal phrase extraction, categorization, selection.

### Key Files

| File | Purpose |
|------|---------|
| `backend/app/api/process.py` | `/api/process` endpoint — orchestrates the pipeline |
| `backend/app/services/song_analyzer.py` | Calls allin1 on Replicate for song structure |
| `backend/app/services/stem_separator.py` | Calls Demucs on Replicate for stem separation |
| `backend/app/services/loop_chopper.py` | Chops stems into loops — section-based for instruments, VAD phrase extraction for vocals |
| `backend/app/services/categorizer.py` | Categorizes loops (groove, foundation, bass, hook, accent, harmonic_bed, texture) and auto-selects best per section |
| `backend/app/services/beat_analyzer.py` | Fallback beat detection via librosa (used when allin1 fails) |
| `backend/app/main.py` | FastAPI app setup, temp dir, CORS |
| `backend/app/config.py` | Settings (MAX_UPLOAD_MB=100, Replicate token) |
| `docs/LEARNINGS.md` | Pipeline refinement log — accumulated taste decisions from listening sessions |

### Critical Technical Decisions

#### Vocal chopping: VAD, not section boundaries
Vocals are sparse — silence between phrases is the signal. We use RMS-based Voice Activity Detection: compute per-frame energy (20ms), smooth (100ms rolling avg), threshold (0.008), group active regions, merge small gaps (< 300ms). Each phrase > 1s becomes its own loop. Instruments use section boundaries from allin1.

#### Directional snap-to-silence
End cuts search forward (let the phrase finish). Start cuts search backward (find quiet before phrase starts). Window: 0.8s. Direction matters more than window size.

#### Energy thresholds are per-stem
drums: 0.005, bass: 0.003, vocals: 0.005, other: 0.003. Use `<=` (not `<`) to filter edge cases.

#### Front-loaded energy filter
If first 20% of a vocal loop has >75% of total energy, skip it — it's a word fragment followed by dead air.

#### Replicate rate limits
With < $5 credit, burst limit is 1 request. allin1 and Demucs run sequentially (not parallel) to avoid 429s.

#### Replicate SDK FileOutput objects
SDK v1.0+ returns FileOutput objects, not strings. Always use `str(v)` to normalize URLs.

### Deployment (Railway)

- **Service:** `song-blender-api` in Railway project `states-of-being`
- **Domain:** `song-blender-api-production.up.railway.app`
- **Deploy:** `cd backend && railway up --detach`
- **Logs:** `cd backend && railway logs`
- **Env vars:** `REPLICATE_API_TOKEN` (required)
- **Health check:** `GET /health`
- `os.environ.setdefault("REPLICATE_API_TOKEN", ...)` in `main.py` exports token for Replicate SDK

### Local Development

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Create .env with REPLICATE_API_TOKEN=...
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### API

```
POST /api/process  (multipart file upload)
GET  /health
GET  /clips/{job_id}/{filename}  (serve generated WAV files)
```

Response shape:
```json
{
  "job_id": "abc123",
  "name": "Song Name",
  "bpm": 120,
  "time_signature": 4,
  "sections": [{"label": "verse", "start": 32.37, "end": 48.38}],
  "total_loops": 41,
  "tracks": [
    {"file": "drums_verse_1.wav", "category": "groove", "section": "verse",
     "mode": "loop", "bars": 8, "duration_sec": 16.0, "energy": 0.17,
     "volume": -12.0, "selected": true, "url": "/clips/abc123/drums_verse_1.wav"}
  ]
}
```

### What's Next

- Rate limiting (5 songs/hr/IP)
- Frontend preview grid showing sections
- Tune vocal VAD thresholds with more songs (current: only tested with line.wav + alorsondance.wav)
- Consider lowering `_SILENCE_THRESHOLD` to capture quieter vocal phrases

## Calm Mirror (index.html)

Single HTML file biofeedback experiment. See the Architecture section below for details.

### Tech Stack

- **MediaPipe Pose** (`@mediapipe/tasks-vision@0.10.14` via CDN)
- **Tone.js** (v14.7.77 via CDN)
- **One-Euro Filter** for landmark smoothing

### Commands

```bash
python3 -m http.server 8000   # Serve (must be localhost for getUserMedia)
```

### Gotchas

- **PolySynth + frame loop**: NEVER use PolySynth for instruments whose per-voice properties are modified in `updateMusic()`. PolySynth doesn't expose `.envelope.decay` etc. at the top level — crashes kill the entire detection loop silently.
- **Tone.js v14 PolySynth constructor**: Options go flat, NOT nested under `voice:`.

## Development Workflow

Use judgment to plan appropriately for the task:
- Simple changes: just implement directly.
- Larger changes: think through the approach before coding.
- Always create a feature branch, commit with descriptive messages, and create a PR.

## After Completing Work

Before wrapping up a non-trivial PR, self-assess:
- What was the hardest decision or trickiest problem?
- Did anything surprise you or require a workaround?
- Would a future session benefit from knowing this?
If yes, update CLAUDE.md with the pattern or gotcha.
