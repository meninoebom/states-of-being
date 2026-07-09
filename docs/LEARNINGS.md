# Song Blender — Learnings & Refinement Log

Accumulated insights from testing the loop processing pipeline. These drive code improvements in our chopper, filter, and categorizer — the models (Demucs, allin1) are fixed, but our post-processing is where all refinement happens.

## Solved: Gapless Loops at the Source (#18, 2026-07-09)

**Problem:** Loops had audible seams. Three source-level defects: (1) the chopper snapped instrument cuts to silence *after* snapping to downbeats, shifting cuts off the beat grid and producing off-grid loops (e.g. 4.043 bars) that the frontend then papered over by rounding `loopEnd`; (2) an 80ms tail-only fade caused a volume dip every cycle and there was no fade-in, so downbeat cuts could click; (3) an untested worry that 192k MP3 encoder delay broke browser gapless looping.

**Solution (chopper):** Non-vocal stems now cut on downbeats **only** (no silence snap), then trim/zero-pad each loop so its length is an exact multiple of the *nominal* bar (`60/bpm * time_signature`). Exactness is defined against the nominal grid, not the raw downbeat span, because real songs drift from a constant tempo and the frontend Transport runs at the nominal tempo. `chop_stem` now takes `bpm`/`time_signature` (guarded against degenerate `0`/`None` values that would otherwise divide-by-zero after Replicate spend). `duration_sec` is the exact written file length (`target_samples / sr`, a whole number of bars to the sample) at sample-fine precision — so the frontend's `loopEnd = duration_sec` wraps precisely at the buffer end, where the fade-out reaches zero.

**Solution (fades):** Replaced the 80ms linear fade-out with a ~5ms **symmetric** fade-in + fade-out (`_apply_edge_fades`). At the loop seam the tail fades to zero and meets the head fading up from zero — declicked, with no per-cycle dip.

**Solution (frontend):** `audio-engine.js` drives `player.loopEnd` from `track.duration_sec` instead of rounding `buffer.duration`. Lossy formats pad the decoded buffer past the true end, so rounding the buffer length can push the loop point past the real content and open a gap; the source duration stops the loop before any padding.

**MP3 encoder-delay finding — VERIFIED, hypothesis REFUTED (keep MP3):**
Empirically decoded with `AudioContext.decodeAudioData` in Chrome (Blink), cross-checked offline with `soundfile`/libsndfile. Method: generate a 2s 440Hz tone WAV whose signal is non-zero from sample 0, encode via the exact ingest path (`pydub` → LAME 192k), decode both, compare leading silence and length.

| file | decoder | samples | lead silence | trail pad |
|------|---------|--------:|-------------:|----------:|
| `src.wav` (source) | Chrome | 88200 | 0 | 0 |
| `src.mp3` (our 192k) | Chrome | 88200 | 0 (0.00ms) | 0 (0.00ms) |
| `src.mp3` (our 192k) | libsndfile | 88200 | 0 | 0 |

Our pydub export writes the Xing/LAME gapless header, and Chrome honors it: the MP3 decodes **sample-identical** to the source with zero encoder delay or padding. So the defect is not present for our pipeline. Per the acceptance criterion ("switch format only if the defect is confirmed AND the new format decodes on Safari/iOS") we **keep MP3 192k**. A real library loop (`library_sample.mp3`) shows ~45ms lead / ~47ms trail, but that is genuine content silence from the *old* snap-to-silence chopper (the controlled tone had zero) — exactly what the new downbeat cuts + 5ms fades remove. Reproduce with `scripts/verify_mp3_gapless.py`. (Safari/iOS and Firefox were not exercised here; WebKit/Gecko also honor the LAME gapless header, so no switch is warranted — revisit only if a real device shows a seam.)

**Remaining manual step:** the 4 curated library songs must be re-ingested once against the deployed new backend (requires the source audio) so their loops become bar-exact; then listen-test per this doc.

**Code refs:** `backend/app/services/loop_chopper.py` (`_fit_to_length`, `_apply_edge_fades`, non-vocal branch of `chop_stem`); `frontend/js/audio-engine.js` (`_setLoopPoints`).

## Architecture Insight

The Replicate models (Demucs for stems, allin1 for song structure) are pre-trained and unchangeable. Our competitive advantage lives in the post-processing pipeline: chopping, energy filtering, categorization, and selection. Every listening session produces feedback that becomes a code improvement.

## Issue: Low-Energy Edge Cases Not Filtered (2026-02-27)

**Song:** alorsondance.wav
**Observed:** `bass_intro_1.wav` (energy 0.003) and `drums_verse_3.wav` (energy 0.005) survived filtering but are essentially silent/useless.
**Root cause:** Energy thresholds are inclusive (`<` not `<=`), so values exactly at the threshold pass through.
**Fix needed:** Use `<=` instead of `<` for energy threshold comparison, or bump thresholds slightly:
- drums: 0.005 → 0.006
- bass: 0.003 → 0.004

## Issue: Vocals Cut Mid-Word at Section Boundaries (2026-02-27)

**Song:** alorsondance.wav
**Observed:** Vocal loops are cut at exact section boundary timestamps from allin1. These timestamps mark structural transitions (verse→chorus) but don't account for vocal phrasing. Result: words get sliced mid-syllable (e.g., "ch-" of "chant" ends up at the tail of one loop, "-ant" at the start of the next).
**Root cause:** We slice exactly at allin1's section boundary with no awareness of vocal activity.
**Fix approach:** Add a "snap to silence" step for vocal stems only. Near each cut point (±500ms window), find the nearest moment of low vocal energy or zero-crossing and snap the cut there. librosa's `zero_crossings()` or RMS energy in a sliding window can find natural pauses. This should only apply to the vocals stem — drums and bass can cut anywhere.

## Solved: Vocal Phrase Extraction via VAD (2026-02-27)

**Problem:** Section-based vocal chopping produced 16-second loops with huge silent gaps, or cut mid-word. A section with a repeating chant would be one giant loop instead of individual usable phrases.
**Solution:** RMS-based Voice Activity Detection on the vocal stem. Compute per-frame RMS (20ms), smooth with 100ms rolling average, threshold at 0.008, group consecutive active frames into regions, merge gaps < 300ms (breath pauses). Each region > 1.0s becomes a phrase loop.
**Key insight:** Vocals need fundamentally different chopping than instruments. Instruments can cut at section boundaries. Vocals must cut at silence between phrases.
**Parameters that worked:** `silence_threshold=0.008`, `min_gap_sec=0.3`, `min_phrase_sec=1.0`, `smooth_window=5` (100ms).
**Result:** 4 clean vocal loops (1 long passage + 3 individual chants) vs 15 messy section-based loops before. Each phrase starts and ends on silence.

## Solved: Directional Snap-to-Silence (2026-02-27)

**Problem:** Symmetric snap (±500ms) found silence *before* the last word instead of *after*, cutting phrases short.
**Solution:** End cuts search forward only (let the phrase finish), start cuts search backward only (find quiet before phrase starts). Window: 0.8s.
**Lesson:** Direction matters more than window size for snap-to-silence.

## Solved: Front-Loaded Energy Filter (2026-02-27)

**Problem:** Some vocal loops started with a loud word fragment then were 90% dead air.
**Solution:** If first 20% of a loop contains >75% of total energy, skip it.

## What's Working Well (2026-02-27)

- **Drums:** Consistently good output across sections. Energy-based groove/foundation categorization makes sense.
- **Song structure detection:** allin1 correctly identifies intro/verse/chorus/outro with accurate timestamps. Section-aware chopping is a massive improvement over the old 4-bar grid.
- **Silent stem filtering:** Vocal loops from instrumental songs (line.wav) are now properly filtered (1 loop vs 61 before).
- **Loop count reduction:** 51-54 loops per song vs 244 before — much more manageable.
