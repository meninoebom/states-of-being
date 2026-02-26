"""Chop audio stems into bar-aligned loops using librosa."""

from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf


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


def find_phrase_boundaries(
    audio_path: str,
    downbeats: list[float],
    bars_per_phrase: int = 4,
) -> list[float]:
    """Group downbeats into N-bar phrases, refined by spectral novelty.

    Returns boundary timestamps in seconds.
    """
    if len(downbeats) < 2:
        return list(downbeats)

    # Group downbeats into phrase-sized chunks
    candidates = downbeats[::bars_per_phrase]

    # Refine with spectral novelty
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    times = librosa.times_like(onset_env, sr=sr)

    snap_window = 0.3  # seconds
    refined = []
    for candidate in candidates:
        mask = np.abs(times - candidate) < snap_window
        if mask.any():
            local_strengths = onset_env[mask]
            local_times = times[mask]
            best = local_times[np.argmax(local_strengths)]
            refined.append(float(best))
        else:
            refined.append(candidate)

    return sorted(set(refined))


def chop_stem(
    stem_path: str,
    phrase_boundaries: list[float],
    output_dir: str,
    stem_name: str,
    downbeats: list[float],
) -> list[Loop]:
    """Extract segments at phrase boundaries and export as audio files.

    Returns a list of Loop objects with energy and bar counts calculated.
    """
    y, sr = librosa.load(stem_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Add end of file as final boundary
    boundaries = sorted(set(phrase_boundaries))
    if not boundaries or boundaries[-1] < duration - 0.5:
        boundaries.append(duration)

    loops: list[Loop] = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        seg_duration = end - start

        if seg_duration < 2.0:
            continue

        start_sample = int(start * sr)
        end_sample = min(int(end * sr), len(y))
        segment = y[start_sample:end_sample]

        # RMS energy normalized 0-1
        rms = float(np.sqrt(np.mean(segment**2)))
        max_possible_rms = 1.0
        energy = min(rms / max_possible_rms, 1.0)

        # Count bars in this segment
        bars = sum(1 for db in downbeats if start <= db < end)
        bars = max(bars, 1)

        mode = "oneshot" if bars <= 1 else "loop"

        filename = f"{stem_name}_loop_{i + 1}.wav"
        filepath = output_path / filename
        sf.write(str(filepath), segment, sr)

        loops.append(Loop(
            file=filename,
            start_sec=round(start, 3),
            end_sec=round(end, 3),
            duration_sec=round(seg_duration, 3),
            bars=bars,
            energy=round(energy, 4),
            category="",
            mode=mode,
            volume=-12.0,
        ))

    return loops
