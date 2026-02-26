"""Beat and downbeat detection using madmom."""

from dataclasses import dataclass

import numpy as np


@dataclass
class BeatGrid:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    time_signature: int  # beats per bar


def analyze_beats(audio_path: str) -> BeatGrid:
    """Detect beats, downbeats, BPM using madmom. Falls back to 120 BPM / 4/4."""
    try:
        from madmom.features.beats import RNNBeatProcessor
        from madmom.features.downbeats import DBNDownBeatTrackingProcessor

        beat_activations = RNNBeatProcessor()(audio_path)
        processor = DBNDownBeatTrackingProcessor(
            beats_per_bar=[3, 4], fps=100
        )
        result = processor(beat_activations)

        # result is Nx2 array: [time_seconds, beat_position]
        # beat_position 1 = downbeat
        times = result[:, 0].tolist()
        positions = result[:, 1].astype(int).tolist()

        beats = times
        downbeats = [t for t, p in zip(times, positions) if p == 1]

        # BPM from median inter-beat interval
        if len(beats) >= 2:
            intervals = np.diff(beats)
            bpm = round(60.0 / float(np.median(intervals)), 1)
        else:
            bpm = 120.0

        # Time signature from median beats-per-bar count
        if len(downbeats) >= 2:
            beats_per_bar = []
            for i in range(len(downbeats) - 1):
                count = sum(
                    1 for t in beats if downbeats[i] <= t < downbeats[i + 1]
                )
                beats_per_bar.append(count)
            time_signature = int(np.median(beats_per_bar)) if beats_per_bar else 4
        else:
            time_signature = 4

        return BeatGrid(
            bpm=bpm,
            beats=beats,
            downbeats=downbeats,
            time_signature=time_signature,
        )

    except Exception:
        # Fallback: 120 BPM, 4/4, empty grid
        return BeatGrid(bpm=120.0, beats=[], downbeats=[], time_signature=4)
