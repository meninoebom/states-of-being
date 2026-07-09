"""Unit tests for beat_analyzer — the librosa fallback beat detector.

The most important documented behavior is graceful degradation: any failure
returns a 120 BPM, 4/4, empty-grid BeatGrid rather than raising. We also pin
the downbeat-derivation contract (every 4th beat) on a real synthetic click
track so the happy path stays honest. No network.
"""

import numpy as np
import soundfile as sf

from app.services.beat_analyzer import BeatGrid, analyze_beats


def test_fallback_on_bad_path():
    grid = analyze_beats("/no/such/file.wav")
    assert isinstance(grid, BeatGrid)
    assert grid.bpm == 120.0
    assert grid.time_signature == 4
    assert grid.beats == []
    assert grid.downbeats == []


def test_click_track_yields_grid_with_derived_downbeats(tmp_path):
    # A 120 BPM click track: an impulse every 0.5s for 8 seconds.
    sr = 22050
    dur = 8.0
    y = np.zeros(int(sr * dur), dtype=np.float32)
    for beat in np.arange(0.0, dur, 0.5):
        idx = int(beat * sr)
        y[idx:idx + 200] = 1.0  # short click
    wav = tmp_path / "click.wav"
    sf.write(str(wav), y, sr)

    grid = analyze_beats(str(wav))
    assert grid.time_signature == 4
    assert grid.bpm > 0
    assert len(grid.beats) > 0
    # Downbeats are documented as every `time_signature`-th beat.
    assert grid.downbeats == grid.beats[::4]
