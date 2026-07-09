"""Unit tests for the loop-chopper taste layer.

These pin the DOCUMENTED post-processing behaviors from CLAUDE.md:
  - directional snap-to-silence (end cuts search forward, start cuts backward)
  - RMS voice-activity phrase extraction with <300ms gap merging and
    <1s phrase discarding
  - front-loaded energy filter (skip word-fragment-then-silence loops)
  - per-stem energy thresholds

No Replicate, no network. Synthetic numpy signals only; the one end-to-end
`chop_stem` case writes a tiny WAV to a tmp dir and reads it back with librosa.
"""

import numpy as np
import pytest
import soundfile as sf

from app.services import loop_chopper as lc


SR = 22050


def _tone(n_samples: int, amp: float = 0.5, freq: float = 220.0, sr: int = SR) -> np.ndarray:
    t = np.arange(n_samples) / sr
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _silence(n_samples: int) -> np.ndarray:
    return np.zeros(n_samples, dtype=np.float32)


# ---------------------------------------------------------------------------
# _snap_to_downbeat
# ---------------------------------------------------------------------------

def test_snap_to_downbeat_picks_nearest():
    assert lc._snap_to_downbeat(5.1, [0.0, 4.0, 8.0]) == 4.0
    assert lc._snap_to_downbeat(7.9, [0.0, 4.0, 8.0]) == 8.0


def test_snap_to_downbeat_empty_returns_input():
    assert lc._snap_to_downbeat(3.3, []) == 3.3


# ---------------------------------------------------------------------------
# _snap_to_silence — directional
# ---------------------------------------------------------------------------

def test_snap_to_silence_forward_finds_silence_ahead():
    # Layout: [loud 0.0-0.5s][silence 0.5-1.5s]. An end cut at 0.5s searching
    # forward should land inside the trailing silence (>0.5s), letting the
    # phrase finish into the quiet.
    loud = _tone(int(0.5 * SR))
    quiet = _silence(int(1.0 * SR))
    y = np.concatenate([loud, quiet])
    snapped = lc._snap_to_silence(y, SR, cut_time=0.5, direction="forward", window_sec=0.8)
    assert snapped > 0.5


def test_snap_to_silence_backward_finds_silence_before():
    # Layout: [silence 0.0-1.0s][loud 1.0-1.5s]. A start cut at 1.0s searching
    # backward should land inside the leading silence (<1.0s).
    quiet = _silence(int(1.0 * SR))
    loud = _tone(int(0.5 * SR))
    y = np.concatenate([quiet, loud])
    snapped = lc._snap_to_silence(y, SR, cut_time=1.0, direction="backward", window_sec=0.8)
    assert snapped < 1.0


def test_snap_to_silence_short_region_returns_cut_time():
    # No room to search past the very end -> returns the input cut time.
    y = _tone(int(0.5 * SR))
    cut = 0.5
    assert lc._snap_to_silence(y, SR, cut_time=cut, direction="forward", window_sec=0.8) == cut


# ---------------------------------------------------------------------------
# _is_front_loaded — front-loaded energy filter
# ---------------------------------------------------------------------------

def test_is_front_loaded_true_when_energy_up_front():
    # All energy in the first fifth, dead air after -> front-loaded (skip it).
    front = _tone(int(0.4 * SR))
    tail = _silence(int(1.6 * SR))
    y = np.concatenate([front, tail])
    assert lc._is_front_loaded(y) is True


@pytest.mark.xfail(
    reason="BUG: _is_front_loaded compares per-sample MEAN energy, not the "
    "first-20%'s SHARE of total energy. An evenly-loud loop yields ratio 1.0 "
    "(>0.75) and is wrongly flagged front-loaded. Documented intent (CLAUDE.md) "
    "is a sum-share: an even loop's first 20% holds ~20% of energy -> keep. "
    "See PR for #17. Remove xfail once the filter uses energy share.",
    strict=True,
)
def test_is_front_loaded_false_when_energy_even():
    # An evenly-loud loop is NOT front-loaded and should be kept.
    y = _tone(int(2.0 * SR))
    assert lc._is_front_loaded(y) is False


def test_is_front_loaded_true_when_near_silent():
    # Guard branch: total energy ~0 counts as front-loaded.
    y = _silence(2000)
    assert lc._is_front_loaded(y) is True


def test_is_front_loaded_false_for_tiny_input():
    assert lc._is_front_loaded(_tone(50)) is False


# ---------------------------------------------------------------------------
# _section_for_time
# ---------------------------------------------------------------------------

def test_section_for_time_maps_and_defaults():
    sections = [
        {"start": 0.0, "end": 4.0, "label": "intro"},
        {"start": 4.0, "end": 8.0, "label": "verse"},
    ]
    assert lc._section_for_time(sections, 2.0) == "intro"
    assert lc._section_for_time(sections, 4.0) == "verse"  # half-open [start, end)
    assert lc._section_for_time(sections, 99.0) == "unknown"


# ---------------------------------------------------------------------------
# _extract_vocal_phrases — VAD
# ---------------------------------------------------------------------------

def test_two_phrases_separated_by_large_gap_stay_separate():
    # phrase(1.2s) | gap(0.6s > 300ms) | phrase(1.2s)
    p = _tone(int(1.2 * SR), amp=0.5)
    gap = _silence(int(0.6 * SR))
    y = np.concatenate([p, gap, p])
    phrases = lc._extract_vocal_phrases(y, SR)
    assert len(phrases) == 2


def test_small_gap_below_300ms_merges_into_one_phrase():
    # phrase(0.8s) | gap(0.15s < 300ms) | phrase(0.8s) -> one merged phrase.
    # Each half is <1s but the merged region is >1s, so it survives.
    p = _tone(int(0.8 * SR), amp=0.5)
    gap = _silence(int(0.15 * SR))
    y = np.concatenate([p, gap, p])
    phrases = lc._extract_vocal_phrases(y, SR)
    assert len(phrases) == 1


def test_short_phrase_below_1s_is_discarded():
    # A single 0.5s blip surrounded by silence is below the 1s minimum.
    y = np.concatenate([_silence(int(0.5 * SR)), _tone(int(0.5 * SR)), _silence(int(0.5 * SR))])
    phrases = lc._extract_vocal_phrases(y, SR)
    assert phrases == []


def test_silence_below_threshold_yields_no_phrases():
    y = _silence(int(3.0 * SR))
    assert lc._extract_vocal_phrases(y, SR) == []


def test_too_few_frames_returns_empty():
    assert lc._extract_vocal_phrases(_tone(100), SR) == []


# ---------------------------------------------------------------------------
# ENERGY_THRESHOLDS — documented per-stem values
# ---------------------------------------------------------------------------

def test_per_stem_energy_thresholds_match_documented_values():
    assert lc.ENERGY_THRESHOLDS == {
        "drums": 0.005,
        "bass": 0.003,
        "vocals": 0.005,
        "other": 0.003,
    }


# ---------------------------------------------------------------------------
# chop_stem — end-to-end on a synthetic WAV (non-vocal section chopping)
# ---------------------------------------------------------------------------

def _write_wav(path, y, sr=SR):
    sf.write(str(path), y, sr)


def test_chop_stem_drops_silent_sections_by_energy(tmp_path):
    # Loud 0-4s, then silent 4-9s. The chorus section starts at 5.0 so the
    # backward snap-to-silence (0.15s window) cannot reach back into the loud
    # region — the 1s guard gap keeps this test about energy filtering, not
    # boundary snapping.
    loud = _tone(int(4.0 * SR), amp=0.4)
    quiet = _silence(int(5.0 * SR))
    wav = tmp_path / "drums.wav"
    _write_wav(wav, np.concatenate([loud, quiet]))

    sections = [
        {"start": 0.0, "end": 4.0, "label": "verse"},
        {"start": 5.0, "end": 9.0, "label": "chorus"},
    ]
    downbeats = [float(i) for i in range(0, 10)]

    loops = lc.chop_stem(str(wav), sections, str(tmp_path / "out"), "drums", downbeats)

    labels = {l.section for l in loops}
    assert "verse" in labels          # loud section kept
    assert "chorus" not in labels     # silent section filtered by energy
    for l in loops:
        assert (tmp_path / "out" / l.file).exists()
        assert l.energy > lc.ENERGY_THRESHOLDS["drums"]


def test_chop_stem_skips_start_end_and_too_short_sections(tmp_path):
    y = _tone(int(10.0 * SR), amp=0.4)
    wav = tmp_path / "bass.wav"
    _write_wav(wav, y)

    sections = [
        {"start": 0.0, "end": 4.0, "label": "start"},   # skip label
        {"start": 4.0, "end": 5.0, "label": "verse"},   # < 2s duration, skip
        {"start": 5.0, "end": 9.0, "label": "chorus"},  # kept
        {"start": 9.0, "end": 10.0, "label": "end"},    # skip label
    ]
    downbeats = [float(i) for i in range(0, 11)]

    loops = lc.chop_stem(str(wav), sections, str(tmp_path / "out"), "bass", downbeats)
    kept = {l.section for l in loops}
    assert kept == {"chorus"}


def test_chop_stem_vocals_uses_phrase_extraction(tmp_path):
    # Two clearly separated ~1.2s phrases -> two vocal phrase loops.
    p = _tone(int(1.2 * SR), amp=0.4)
    gap = _silence(int(0.6 * SR))
    y = np.concatenate([gap, p, gap, p, gap])
    wav = tmp_path / "vocals.wav"
    _write_wav(wav, y)

    sections = [{"start": 0.0, "end": 6.0, "label": "verse"}]
    downbeats = [float(i) * 0.5 for i in range(0, 13)]

    loops = lc.chop_stem(str(wav), sections, str(tmp_path / "out"), "vocals", downbeats)
    assert len(loops) == 2
    for l in loops:
        assert l.file.startswith("vocals_phrase_")
        assert (tmp_path / "out" / l.file).exists()
