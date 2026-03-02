# States of Being — Song Blender Roadmap

## Product Vision

A fun, widely available web tool where people explore a "song space" using their webcam. Movement drives how songs blend and transform in real time — a game-like biofeedback experience.

**Target audience (v1):** Adults looking for a novel, playful experience
**Future direction:** Kid-oriented versions

## What's Done

- [x] Song Blender API deployed on Railway (`song-blender-api-production.up.railway.app`)
- [x] Stem separation via Demucs (drums, bass, vocals, other)
- [x] Song structure analysis via allin1 (verse/chorus/bridge/solo/outro)
- [x] Section-aware loop chopping for instruments
- [x] Vocal phrase extraction via voice activity detection
- [x] Per-stem energy filtering, front-loaded filter, directional snap-to-silence
- [x] Categorization (groove, foundation, bass, hook, accent, harmonic_bed, texture)
- [x] Auto-selection (top 2 per category per section)

## Next Steps (in order)

### 1. Tune the pipeline with more songs
**Why first:** The VAD and energy thresholds were tuned on only 2 songs (line.wav, alorsondance.wav). Before building UI on top of the API, we need confidence the output is good across genres.
- Process 3-5 more songs with different characteristics (instrumental, hip-hop, acoustic, electronic)
- Adjust `_SILENCE_THRESHOLD` (currently 0.008) — may need to go lower for quieter vocals
- Update LEARNINGS.md with findings
- Estimated effort: 1 session of listening + tweaking

### 2. Rate limiting on the API
**Why next:** Before anyone else uses this, prevent abuse. The Replicate calls cost ~$0.14/song.
- Add slowapi rate limiting: 5 songs/hr per IP
- Pattern: same as Tend's rate limiting (in-memory, disabled in tests)
- Estimated effort: small, ~30 min

### 3. Pre-process Brandon's curated song library
**Why next:** The free tier needs a library of pre-blended songs ready to go. Processing them now means the frontend can load instantly without waiting 2 min per song.
- Pick 5-10 songs for the curated library
- Run each through the API, save the output JSON + WAV files to persistent storage
- Decision needed: where to store (Railway volume? S3? Git LFS?)
- Estimated effort: 1 session

### 4. Build the frontend song blender UI
**Why next:** This is the actual product experience. Everything before this was infrastructure.
- Song picker (curated library for free tier)
- Loop grid showing sections × stems with play/mute toggles
- Real-time mixing (Tone.js or Web Audio API for playback + crossfading)
- Decision needed: standalone app or integrated into existing States of Being index.html?
- Estimated effort: 2-3 sessions

### 5. Connect webcam movement to loop mixing
**Why next:** This is what makes it *States of Being* — movement controls the blend.
- Map MediaPipe pose data to loop volumes/selection
- Reuse movement analysis from Calm Mirror (velocity, jerkiness, contraction)
- Movement → which loops are active, volume levels, crossfade speed
- Estimated effort: 1-2 sessions

### 6. Premium tier: user song upload
**Why after:** Only gate this after the free experience is polished.
- Upload UI calling the existing `/api/process` endpoint
- Account system (auth, usage tracking)
- Storage for user-generated loops
- Pricing model decision needed
- Estimated effort: 2-3 sessions

## Open Questions

- Pricing model (subscription vs one-time vs credits?)
- Song generation: what tool/API? How much control does the user get?
- How many curated songs ship in the free tier?
- Where to store pre-processed song data (Railway volume vs S3 vs other)
- Standalone frontend app vs integrated into existing States of Being?
