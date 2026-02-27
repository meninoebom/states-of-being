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


def chop_stem(
    stem_path: str,
    sections: list[dict],
    output_dir: str,
    stem_name: str,
    downbeats: list[float],
) -> list[Loop]:
    """Chop a stem into one loop per song section.

    Each section (verse, chorus, bridge, etc.) from the structure analysis
    becomes one loop per stem. Silent sections are filtered by energy threshold.
    """
    # Load at native sample rate, preserve stereo for output
    y_full, sr = librosa.load(stem_path, sr=None, mono=False)
    is_stereo = y_full.ndim == 2
    num_samples = y_full.shape[-1]

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    energy_threshold = ENERGY_THRESHOLDS.get(stem_name, 0.003)
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

        start_sample = int(sec_start * sr)
        end_sample = min(int(sec_end * sr), num_samples)
        segment = y_full[..., start_sample:end_sample]

        # RMS energy on mono mixdown
        mono_seg = segment.mean(axis=0) if is_stereo else segment
        rms = float(np.sqrt(np.mean(mono_seg**2)))
        energy = min(rms, 1.0)

        if energy <= energy_threshold:
            continue

        # Count bars in this segment
        bars = sum(1 for db in downbeats if sec_start <= db < sec_end)
        bars = max(bars, 1)

        mode = "oneshot" if bars <= 1 else "loop"
        loop_idx += 1

        filename = f"{stem_name}_{label}_{loop_idx}.wav"
        filepath = output_path / filename
        write_data = segment.T if is_stereo else segment
        sf.write(str(filepath), write_data, sr)

        seg_duration = sec_end - sec_start
        loops.append(Loop(
            file=filename,
            start_sec=round(sec_start, 3),
            end_sec=round(sec_end, 3),
            duration_sec=round(seg_duration, 3),
            bars=bars,
            energy=round(energy, 4),
            category="",
            mode=mode,
            volume=-12.0,
            section=label,
        ))

    return loops
