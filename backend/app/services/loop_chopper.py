"""Chop audio stems into loops aligned to song structure sections."""

import logging
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


@dataclass
class Loop:
    file: str
    start_sec: float
    end_sec: float
    duration_sec: float
    bars: int
    energy: float
    category: str
    mode: str
    volume: float
    section: str


# Minimum energy per stem — loops below this are silent/useless
ENERGY_THRESHOLDS = {
    "drums": 0.005,
    "bass": 0.003,
    "vocals": 0.005,
    "other": 0.003,
}

# 20ms analysis frames for silence detection
_FRAME_MS = 0.02

# Vocal phrase detection parameters
_SILENCE_THRESHOLD = 0.008  # RMS below this = silence
_MIN_GAP_SEC = 0.3  # Gaps shorter than this merge into one phrase
_MIN_PHRASE_SEC = 1.0  # Phrases shorter than this are discarded
_SMOOTH_WINDOW = 5  # Rolling average window in frames (100ms)


def _snap_to_downbeat(cut_time: float, downbeats: list[float]) -> float:
    """Snap a cut time to the nearest downbeat for musically coherent boundaries."""
    if not downbeats:
        return cut_time
    return min(downbeats, key=lambda db: abs(db - cut_time))


def _snap_to_silence(
    y_mono: np.ndarray,
    sr: int,
    cut_time: float,
    direction: str = "forward",
    window_sec: float = 0.8,
) -> float:
    """Find the quietest moment near cut_time, biased by direction.

    For end cuts (direction="forward"), search from cut_time to +window_sec.
    For start cuts (direction="backward"), search from -window_sec to cut_time.
    """
    frame_len = int(sr * _FRAME_MS)
    window_samples = int(window_sec * sr)
    center = int(cut_time * sr)

    if direction == "forward":
        search_start = center
        search_end = min(len(y_mono), center + window_samples)
    else:
        search_start = max(0, center - window_samples)
        search_end = center

    region = y_mono[search_start:search_end]

    if len(region) < frame_len:
        return cut_time

    n_frames = len(region) // frame_len
    frames = region[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames**2, axis=1))

    quietest = int(np.argmin(rms))
    best_sample = search_start + quietest * frame_len + frame_len // 2
    return best_sample / sr


def _fit_to_length(segment: np.ndarray, target_samples: int) -> np.ndarray:
    """Trim or zero-pad a segment (last axis = samples) to exactly target_samples.

    Returns a fresh, writable array so the caller can apply fades in place.
    """
    cur = segment.shape[-1]
    if cur > target_samples:
        return np.array(segment[..., :target_samples])
    if cur < target_samples:
        pad = ((0, 0), (0, target_samples - cur)) if segment.ndim == 2 else (0, target_samples - cur)
        return np.pad(segment, pad, mode="constant")
    return np.array(segment)


def _apply_edge_fades(segment: np.ndarray, sr: int, fade_ms: float = 5.0) -> np.ndarray:
    """Apply a short symmetric fade-in and fade-out for seamless looping.

    A ~5ms linear ramp at each edge declicks the loop seam — the tail fades to
    zero and meets the head fading up from zero — without the audible per-cycle
    volume dip of a long (80ms) tail fade. Mutates and returns `segment`.
    """
    n = segment.shape[-1]
    fade = min(int(sr * fade_ms / 1000.0), n // 2)
    if fade <= 0:
        return segment
    fade_in = np.linspace(0.0, 1.0, fade, dtype=segment.dtype)
    fade_out = fade_in[::-1]
    segment[..., :fade] *= fade_in
    segment[..., -fade:] *= fade_out
    return segment


def _extract_vocal_phrases(
    y_mono: np.ndarray, sr: int
) -> list[tuple[float, float]]:
    """Detect individual vocal phrases using RMS-based voice activity detection.

    Returns list of (start_sec, end_sec) for each contiguous vocal region.
    """
    frame_len = int(sr * _FRAME_MS)
    n_frames = len(y_mono) // frame_len
    if n_frames < 10:
        return []

    # Compute per-frame RMS
    trimmed = y_mono[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(trimmed**2, axis=1))

    # Smooth to avoid micro-gaps (breath between syllables in same word)
    kernel = np.ones(_SMOOTH_WINDOW) / _SMOOTH_WINDOW
    rms = np.convolve(rms, kernel, mode="same")

    # Threshold: active frames
    active = rms > _SILENCE_THRESHOLD

    # Group consecutive active frames into regions
    min_gap_frames = int(_MIN_GAP_SEC / _FRAME_MS)
    min_phrase_frames = int(_MIN_PHRASE_SEC / _FRAME_MS)

    # Merge small gaps: if gap between two active regions < min_gap_frames, fill it
    regions: list[tuple[int, int]] = []
    in_region = False
    region_start = 0

    for i in range(len(active)):
        if active[i] and not in_region:
            region_start = i
            in_region = True
        elif not active[i] and in_region:
            # Look ahead: is this a small gap?
            gap_end = i
            while gap_end < len(active) and not active[gap_end]:
                gap_end += 1
            if gap_end - i < min_gap_frames and gap_end < len(active):
                # Small gap — bridge it, stay in region
                continue
            else:
                regions.append((region_start, i))
                in_region = False

    if in_region:
        regions.append((region_start, len(active)))

    # Filter short phrases and convert to seconds
    phrases = []
    for start_frame, end_frame in regions:
        if end_frame - start_frame < min_phrase_frames:
            continue
        start_sec = start_frame * _FRAME_MS
        end_sec = end_frame * _FRAME_MS
        # Snap to silence for clean edges
        start_sec = _snap_to_silence(y_mono, sr, start_sec, direction="backward", window_sec=0.3)
        end_sec = _snap_to_silence(y_mono, sr, end_sec, direction="forward", window_sec=0.3)
        if end_sec - start_sec >= _MIN_PHRASE_SEC:
            phrases.append((start_sec, end_sec))

    logger.info("Detected %d vocal phrases", len(phrases))
    return phrases


def _section_for_time(sections: list[dict], t: float) -> str:
    """Find which song section a timestamp falls in."""
    for s in sections:
        if s["start"] <= t < s["end"]:
            return s.get("label", "unknown")
    return "unknown"


def _is_front_loaded(y_mono: np.ndarray, threshold: float = 0.75) -> bool:
    """Check if most energy is in the first 20% of the audio."""
    if len(y_mono) < 100:
        return False
    split = len(y_mono) // 5
    energy_front = float(np.mean(y_mono[:split] ** 2))
    energy_total = float(np.mean(y_mono**2))
    if energy_total < 1e-10:
        return True
    return energy_front / energy_total > threshold


def _chop_vocal_phrases(
    y_full: np.ndarray,
    sr: int,
    y_mono: np.ndarray,
    sections: list[dict],
    downbeats: list[float],
    output_path: Path,
    energy_threshold: float,
) -> list[Loop]:
    """Extract individual vocal phrases via voice activity detection."""
    is_stereo = y_full.ndim == 2
    num_samples = y_full.shape[-1]

    phrases = _extract_vocal_phrases(y_mono, sr)
    loops: list[Loop] = []

    for idx, (phrase_start, phrase_end) in enumerate(phrases, 1):
        start_sample = int(phrase_start * sr)
        end_sample = min(int(phrase_end * sr), num_samples)
        segment = y_full[..., start_sample:end_sample]

        mono_seg = segment.mean(axis=0) if is_stereo else segment
        rms = float(np.sqrt(np.mean(mono_seg**2)))
        energy = min(rms, 1.0)

        if energy <= energy_threshold:
            continue

        if _is_front_loaded(mono_seg):
            continue

        section_label = _section_for_time(sections, phrase_start)
        bars = sum(1 for db in downbeats if phrase_start <= db < phrase_end)
        bars = max(bars, 1)

        duration = phrase_end - phrase_start
        mode = "oneshot" if duration <= 6.0 else "loop"

        filename = f"vocals_phrase_{section_label}_{idx}.wav"
        write_data = segment.T if is_stereo else segment
        sf.write(str(output_path / filename), write_data, sr)

        loops.append(Loop(
            file=filename,
            start_sec=round(phrase_start, 3),
            end_sec=round(phrase_end, 3),
            duration_sec=round(duration, 3),
            bars=bars,
            energy=round(energy, 4),
            category="",
            mode=mode,
            volume=-12.0,
            section=section_label,
        ))

    return loops


def chop_stem(
    stem_path: str,
    sections: list[dict],
    output_dir: str,
    stem_name: str,
    downbeats: list[float],
    bpm: float = 120.0,
    time_signature: int = 4,
) -> list[Loop]:
    """Chop a stem into loops.

    For non-vocal stems: one loop per song section, cut on downbeats and
    quantized to an exact multiple of the nominal bar (60/bpm * time_signature)
    so loops are gapless at the source (issue #18).
    For vocals: extract individual phrases via voice activity detection,
    plus keep full-section loops where the section is densely vocal.
    """
    y_full, sr = librosa.load(stem_path, sr=None, mono=False)
    is_stereo = y_full.ndim == 2
    num_samples = y_full.shape[-1]

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    energy_threshold = ENERGY_THRESHOLDS.get(stem_name, 0.003)

    # For vocals, use phrase extraction instead of section-based chopping.
    # (y_mono is only needed here; non-vocal chopping computes per-segment RMS.)
    if stem_name == "vocals":
        y_mono = y_full.mean(axis=0) if is_stereo else y_full
        return _chop_vocal_phrases(
            y_full, sr, y_mono, sections, downbeats, output_path, energy_threshold
        )

    # Non-vocal stems: one loop per section, cut on downbeats and quantized to
    # the nominal bar grid (issue #18).
    nominal_bar_dur = (60.0 / bpm) * time_signature  # seconds per bar on the grid
    loops: list[Loop] = []
    loop_idx = 0
    skip_labels = {"start", "end"}

    for section in sections:
        label = section.get("label", "unknown")
        if label in skip_labels:
            continue

        sec_start = section["start"]
        sec_end = section["end"]

        if sec_end - sec_start < 2.0:
            continue

        # Cut on downbeats ONLY. The old code then snapped each cut to nearby
        # silence, which shifted boundaries off the beat grid and produced loops
        # like 4.043 bars. The frontend Transport runs at the nominal tempo, so
        # off-grid loops desync; snap-to-silence is intentionally dropped here.
        sec_start = _snap_to_downbeat(sec_start, downbeats)
        sec_end = _snap_to_downbeat(sec_end, downbeats)

        start_sample = int(round(sec_start * sr))
        end_sample = min(int(round(sec_end * sr)), num_samples)
        if end_sample <= start_sample:
            continue
        segment = y_full[..., start_sample:end_sample]

        mono_seg = segment.mean(axis=0) if is_stereo else segment
        rms = float(np.sqrt(np.mean(mono_seg**2)))
        energy = min(rms, 1.0)

        if energy <= energy_threshold:
            continue

        # Quantize the loop LENGTH to an exact multiple of the nominal bar,
        # measured against the nominal grid (not the raw downbeat span) because
        # real songs drift from a constant tempo. Trim if long, zero-pad if short.
        raw_span = (end_sample - start_sample) / sr
        bars = max(1, round(raw_span / nominal_bar_dur))
        target_samples = round(bars * nominal_bar_dur * sr)
        segment = _fit_to_length(segment, target_samples)

        # Short symmetric fades declick the downbeat cut without a per-cycle dip.
        segment = _apply_edge_fades(segment, sr)

        mode = "oneshot" if bars <= 1 else "loop"
        loop_idx += 1

        filename = f"{stem_name}_{label}_{loop_idx}.wav"
        write_data = segment.T if is_stereo else segment
        sf.write(str(output_path / filename), write_data, sr)

        # duration_sec is the exact nominal-bar length. The frontend drives
        # player.loopEnd from it (kept at sample-fine precision to avoid drift
        # between layers over a long session).
        duration_sec = bars * nominal_bar_dur
        loops.append(Loop(
            file=filename,
            start_sec=round(sec_start, 3),
            end_sec=round(sec_start + duration_sec, 3),
            duration_sec=round(duration_sec, 6),
            bars=bars,
            energy=round(energy, 4),
            category="",
            mode=mode,
            volume=-12.0,
            section=label,
        ))

    return loops
