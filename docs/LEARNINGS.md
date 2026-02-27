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

## What's Working Well (2026-02-27)

- **Drums:** Consistently good output across sections. Energy-based groove/foundation categorization makes sense.
- **Song structure detection:** allin1 correctly identifies intro/verse/chorus/outro with accurate timestamps. Section-aware chopping is a massive improvement over the old 4-bar grid.
- **Silent stem filtering:** Vocal loops from instrumental songs (line.wav) are now properly filtered (1 loop vs 61 before).
- **Loop count reduction:** 51-54 loops per song vs 244 before — much more manageable.
