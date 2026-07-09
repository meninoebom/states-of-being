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
    # Loud 0-4s, then silent 4-9s. The chorus (5.0-9.0) is cut on its downbeats
    # and lands entirely in the silent region, so the per-stem energy filter
    # drops it while the loud verse is kept.
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


def test_chop_stem_vocals_drops_below_threshold_phrase(tmp_path):
    # A VAD-detectable phrase whose loudness sits just under the vocals energy
    # threshold (0.005) must be dropped inside _chop_vocal_phrases, proving the
    # energy filter fires on the real vocal path, not just the primitive.
    quiet_amp = 0.004  # sine RMS = 0.004/sqrt(2) ~ 0.0028 < 0.005
    p = _tone(int(1.4 * SR), amp=quiet_amp)
    gap = _silence(int(0.6 * SR))
    y = np.concatenate([gap, p, gap])
    wav = tmp_path / "vocals.wav"
    _write_wav(wav, y)

    sections = [{"start": 0.0, "end": 3.0, "label": "verse"}]
    downbeats = [float(i) * 0.5 for i in range(0, 7)]

    loops = lc.chop_stem(str(wav), sections, str(tmp_path / "out"), "vocals", downbeats)
    assert loops == []


# ---------------------------------------------------------------------------
# chop_stem — gapless-at-the-source: bar-exact cuts + loop-safe fades (#18)
# ---------------------------------------------------------------------------


def _read_wav_mono(path):
    y, sr = sf.read(str(path))
    if y.ndim == 2:
        y = y.mean(axis=1)
    return y, sr


def test_nonvocal_loop_is_exact_nominal_bar_multiple_when_downbeats_drift(tmp_path):
    # The Transport plays at the NOMINAL tempo, so loop length must be an exact
    # multiple of the nominal bar (60/bpm * time_signature), NOT the raw
    # downbeat span. Here the real downbeats run slightly long (2.1s apart) while
    # the nominal bar is 2.0s — the loop must be quantized to the nominal grid.
    bpm, ts = 120.0, 4
    nominal_bar = (60.0 / bpm) * ts  # 2.0s
    y = _tone(int(12.0 * SR), amp=0.4)  # long enough that a trim is needed
    wav = tmp_path / "drums.wav"
    _write_wav(wav, y)

    downbeats = [0.0, 2.1, 4.2, 6.3, 8.4]  # ~2.1s bars => real tempo ~114 bpm
    sections = [{"start": 0.0, "end": 8.4, "label": "verse"}]

    loops = lc.chop_stem(
        str(wav), sections, str(tmp_path / "out"), "drums", downbeats,
        bpm=bpm, time_signature=ts,
    )
    assert len(loops) == 1
    loop = loops[0]

    # raw span 8.4s / 2.0s nominal -> round(4.2) = 4 bars -> 8.0s target
    assert loop.bars == 4
    assert loop.duration_sec == pytest.approx(4 * nominal_bar, abs=1e-3)

    # The WAV on disk is an exact nominal-bar multiple, to the sample.
    out, out_sr = _read_wav_mono(tmp_path / "out" / loop.file)
    expected_samples = round(4 * nominal_bar * out_sr)
    assert len(out) == expected_samples


def test_nonvocal_loop_pads_short_section_up_to_bar_multiple(tmp_path):
    # A section a hair SHORT of a whole number of nominal bars is padded up to
    # the nearest multiple (never left off-grid).
    bpm, ts = 120.0, 4
    nominal_bar = (60.0 / bpm) * ts  # 2.0s
    y = _tone(int(8.0 * SR), amp=0.4)
    wav = tmp_path / "bass.wav"
    _write_wav(wav, y)

    downbeats = [0.0, 1.9, 3.8]  # span 3.8s -> round(1.9 bars) = 2 bars -> pad to 4.0s
    sections = [{"start": 0.0, "end": 3.8, "label": "chorus"}]

    loops = lc.chop_stem(
        str(wav), sections, str(tmp_path / "out"), "bass", downbeats,
        bpm=bpm, time_signature=ts,
    )
    assert len(loops) == 1
    assert loops[0].bars == 2
    out, out_sr = _read_wav_mono(tmp_path / "out" / loops[0].file)
    assert len(out) == round(2 * nominal_bar * out_sr)


def test_nonvocal_loop_has_short_symmetric_edge_fades_not_80ms_tail(tmp_path):
    # A constant-amplitude signal makes the fade envelope crisp to read back.
    # Requirement: ~5ms fade-IN at the head and ~5ms fade-OUT at the tail, and
    # NOT the old 80ms tail-only fade.
    bpm, ts = 120.0, 4
    sr = SR
    dc = np.full(int(6.0 * sr), 0.5, dtype=np.float32)  # steady 0.5
    wav = tmp_path / "drums.wav"
    _write_wav(wav, dc)

    downbeats = [0.0, 2.0, 4.0]
    sections = [{"start": 0.0, "end": 4.0, "label": "verse"}]

    loops = lc.chop_stem(
        str(wav), sections, str(tmp_path / "out"), "drums", downbeats,
        bpm=bpm, time_signature=ts,
    )
    out, out_sr = _read_wav_mono(tmp_path / "out" / loops[0].file)
    fade = int(0.005 * out_sr)

    # Head and tail start/end at (near) zero — no click at the loop seam.
    assert abs(out[0]) < 0.05
    assert abs(out[-1]) < 0.05
    # Fade is SHORT: 20ms in from each edge the signal is already at full level,
    # which would be impossible under an 80ms fade.
    twenty_ms = int(0.02 * out_sr)
    assert out[twenty_ms] == pytest.approx(0.5, abs=0.02)
    assert out[len(out) - twenty_ms] == pytest.approx(0.5, abs=0.02)
    # And the interior is untouched full level.
    assert out[len(out) // 2] == pytest.approx(0.5, abs=0.02)
    # Sanity: the fade actually ramps (midpoint of the head fade ~ half level).
    assert out[fade // 2] < 0.4


def test_nonvocal_cut_is_on_downbeat_not_snapped_into_nearby_dip(tmp_path):
    # A brief quiet dip sits just inside the section, near the end boundary.
    # The OLD forward snap-to-silence would have pulled the end cut into that
    # dip; the new downbeat-only cut must ignore it and stay bar-exact.
    bpm, ts = 120.0, 4
    nominal_bar = (60.0 / bpm) * ts  # 2.0s
    sr = SR
    body = np.full(int(4.0 * sr), 0.4, dtype=np.float32)
    # carve a 0.1s dip at 3.9s (inside the last bar)
    body[int(3.9 * sr):int(4.0 * sr)] = 0.0
    wav = tmp_path / "other.wav"
    _write_wav(wav, np.concatenate([body, np.full(int(2.0 * sr), 0.4, dtype=np.float32)]))

    downbeats = [0.0, 2.0, 4.0]
    sections = [{"start": 0.0, "end": 4.0, "label": "verse"}]

    loops = lc.chop_stem(
        str(wav), sections, str(tmp_path / "out"), "other", downbeats,
        bpm=bpm, time_signature=ts,
    )
    out, out_sr = _read_wav_mono(tmp_path / "out" / loops[0].file)
    # Exactly 2 nominal bars, cut at the 4.0s downbeat — not shifted to the dip.
    assert len(out) == round(2 * nominal_bar * out_sr)
