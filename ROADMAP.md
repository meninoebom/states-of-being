# States of Being — Song Blender Roadmap

## Product Vision

A fun, widely available web tool where people explore a "song space" using their webcam. Movement drives how songs blend and transform in real time — a game-like biofeedback experience.

**Target audience (v1):** Adults looking for a novel, playful experience
**Future direction:** Kid-oriented versions

## What's Done

- [x] Song Blender API deployed on Railway (`song-blender-api-production.up.railway.app`)
- [x] Stem separation via Demucs (drums, bass, vocals, other)
- [x] Song structure analysis via allin1 (verse/chorus/bridge/solo/outro)
- [x] Section-aware loop chopping with downbeat snap + silence fine-tune + fade-out
- [x] Vocal phrase extraction via voice activity detection
- [x] Per-stem energy filtering, front-loaded filter, directional snap-to-silence
- [x] Categorization (groove, foundation, bass, hook, accent, harmonic_bed, texture)
- [x] Auto-selection (top 2 per category per section)
- [x] Rate limiting (5 songs/hr/IP via slowapi)
- [x] Library system (ingestion script, catalog.json, MP3 compression)
- [x] Frontend: song picker, loop grid, Tone.js audio engine with Transport-synced loops
- [x] Loop sync: bar-quantized loop endpoints prevent drift
- [x] Webcam movement mixing: MediaPipe Pose → body qualities → readings → audio mapping
- [x] Two-body support: auto-detect 1-2 dancers, relational readings (synchrony, contrast)
- [x] Skeleton overlay + debug panel
- [x] 4 curated songs ingested (Highest, If I Had A Million, When Angels Sing, Sweet Thang)
- [x] Library committed to git for deployment

## Next Steps (in order)

### 1. UX refinement
- The grid is a developer tool — design the actual user experience
- What does a new user see? How do they understand what's happening?
- Movement-driven mode needs to feel intuitive without explanation

### 2. Tune movement-to-music mappings
- Test with real users (not just developer)
- Adjust reading configs (thresholds, weights) based on feel
- Tune relational readings with two actual dancers

### 3. Add more curated songs
- Process 5-10 more songs across genres
- Run through ingestion script, commit to library/

### 4. Railway Volume for user uploads
- Attach a Railway Volume at `/data/library` for writable persistent storage
- User upload UI calling existing `/api/process` endpoint
- Downloaded loops stored on volume, not baked into image
- This is when storage moves from git → volume

### 5. Premium tier: user song upload
- Account system (auth, usage tracking)
- Upload limits, storage quotas
- Pricing model decision needed

## Open Questions

- Pricing model (subscription vs one-time vs credits?)
- How many curated songs ship in the free tier?
- UX: what does the non-developer experience look like?
- Ralf integration: when does Song Blender become a formal Ralf translator?
