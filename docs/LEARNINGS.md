# Song Blender — Learnings & Refinement Log

Accumulated insights from testing the loop processing pipeline. These drive code improvements in our chopper, filter, and categorizer — the models (Demucs, allin1) are fixed, but our post-processing is where all refinement happens.

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
