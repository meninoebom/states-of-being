# Calm Mirror

A browser-based biofeedback experiment that nudges a dancer toward calmness. A webcam watches the dancer via MediaPipe Pose, analyzes movement quality, and generates real-time music via Tone.js that mirrors their emotional state — but inverted. The music is uncomfortable when the dancer is uncomfortable, rewarding when they find flow.

## What It Is

**Single HTML file** — no build step, no server dependencies. Serve with `python3 -m http.server` and open `http://localhost:8000`.

**Core loop:** Camera → MediaPipe Pose (33 keypoints) → Movement Analyzer → Emotion Computation → Tone.js Music + Color Cloud Visual

## Tech Stack

- **MediaPipe Pose** (`@mediapipe/tasks-vision@0.10.14` via CDN) — 33 keypoints, 30+ FPS
- **Tone.js** (v14.7.77 via CDN) — synthesis, scheduling, effects
- **One-Euro Filter** — adaptive low-pass for landmark smoothing

## Architecture (all in index.html)

```
┌──────────────────────────────────────────────────┐
│  Camera → MediaPipe Pose (33 keypoints)          │
│              ↓ One-Euro Filter                    │
│  Movement Analyzer (kinematics + body shape)     │
│    • velocity, jerkiness (jerk = 3rd derivative) │
│    • contraction, verticality, symmetry          │
│    • AdaptiveRange normalization (no calibration) │
│              ↓                                    │
│  Emotion Computation (gated, weighted)           │
│    anger, sadness, fear, craving, flow           │
│              ↓                                    │
│  Tone.js Music Engine          Color Cloud       │
│    bass (sub+growl), pad,      radial gradient   │
│    melody, wood block perc,    orbs at joints    │
│    fear synth, stillness drone                   │
└──────────────────────────────────────────────────┘
```

## Key Design Decisions

### Movement → Emotion Mapping

| Emotion | Primary Signals | Gate Condition |
|---------|----------------|----------------|
| **Anger** | velocity + jerkiness + asymmetry | velocity > 0.08 OR jerkiness > 0.1 |
| **Sadness** | low velocity + contraction + slumped | velocity < 0.4 |
| **Fear** | high jerk-to-velocity ratio | jerkiness > 0.3 |
| **Craving** | moderate speed + reaching out | velocity 0.15-0.4, low jerk |
| **Flow** | mid velocity + low jerk + open + upright + symmetric | ALL conditions (multiplicative) |

### Musical Response

| State | Sound |
|-------|-------|
| **Agitated** | Dissonant chords, chromatic melody stabs, irregular wood block, harsh filter, fast tempo |
| **Calm/Flow** | Consonant Cm7 chords, melodic scale runs, steady wood block pulse, warm filter, 78bpm |
| **Depressed/Still** | Oppressive sub bass + sawtooth growl, building stillness drone, dark filter, slow tempo |
| **Fear** | High sawtooth stabs with tremolo LFO |

### AdaptiveRange (no calibration)

Instead of a calibration phase, each primitive has an `AdaptiveRange` that instantly expands on new extremes and slowly contracts back. This means thresholds are always relative to YOUR actual movement range.

### Asymmetric Lerp

Anger uses fast attack (0.2) but normal decay (0.1) so shaking registers immediately but doesn't snap off.

## Known Issues / Next Steps

- **Audio pops**: Some clicking/popping from synth voices — likely from retriggering synths too fast or missing release envelopes. Needs investigation. Could be MembraneSynth (wood block) retriggering before previous note finishes, or the stillness drone attack/release.
- **Tracking latency**: MediaPipe detection runs at rAF speed. Could decouple detection frequency from render frequency for lower latency.
- **Flow threshold**: Has been tuned down multiple times. User wants flow to register at very slow, smooth movement.
- **Anger threshold**: Similarly tuned down. Shaking in place should slam anger to 1.0.

## Visual Design

- **Color cloud**: Fullscreen radial gradient, hue/saturation driven by dominant emotion
- **Orbs**: Translucent gradient circles at 13 joint positions, color shifts with emotion, size pulses with velocity
- **Debug panel**: Toggle with 'd' key. Shows emotion meters + raw primitive meters. Heading-sized text for visibility while dancing.

## Development Workflow

Use judgment to plan appropriately for the task:
- Simple changes: just implement directly.
- Larger changes: think through the approach before coding.
- Always create a feature branch, commit with descriptive messages, and create a PR.

## Commands

```bash
python3 -m http.server 8000   # Serve the file
# Open http://localhost:8000 (MUST be localhost, not IP — getUserMedia requires it)
```

## Code Quality

- Everything in one HTML file for now — keeps iteration fast
- No build step, no dependencies beyond CDN scripts
- When the file gets too large, split into modules with ES imports

## After Completing Work

Before wrapping up a non-trivial PR, self-assess:
- What was the hardest decision or trickiest problem?
- Did anything surprise you or require a workaround?
- Would a future session benefit from knowing this?
If yes, update CLAUDE.md with the pattern or gotcha.
