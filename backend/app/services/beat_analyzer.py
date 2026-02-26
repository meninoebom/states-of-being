"""Beat and downbeat detection using librosa."""

import logging
from dataclasses import dataclass

import librosa
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BeatGrid:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    time_signature: int  # beats per bar


def analyze_beats(audio_path: str) -> BeatGrid:
    """Detect beats, estimate downbeats and BPM using librosa.

    Falls back to 120 BPM, 4/4, and empty beat grids on any error.
    """
    try:
        y, sr = librosa.load(audio_path, sr=22050, mono=True)

        # Beat tracking
        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

        # tempo may be an array in some librosa versions
        bpm = round(float(np.atleast_1d(tempo)[0]), 1)

        # Estimate time signature (assume 4/4) and derive downbeats
        time_signature = 4
        downbeats = beat_times[::time_signature]

        return BeatGrid(
            bpm=bpm,
            beats=beat_times,
            downbeats=downbeats,
            time_signature=time_signature,
        )

    except Exception:
        logger.warning("Beat analysis failed, using 120 BPM fallback", exc_info=True)
        return BeatGrid(bpm=120.0, beats=[], downbeats=[], time_signature=4)
