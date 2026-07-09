"""Unit tests for pre-spend upload validation (no librosa, no network)."""

import asyncio

import pytest

from app.upload_validation import (
    UploadValidationError,
    stream_to_disk,
    validate_duration,
    validate_extension,
)

SUPPORTED = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}


# ---- extension ----

def test_valid_extension_returns_lowercase_ext():
    assert validate_extension("Song.MP3", SUPPORTED) == ".mp3"


def test_missing_filename_raises_400():
    with pytest.raises(UploadValidationError) as ei:
        validate_extension(None, SUPPORTED)
    assert ei.value.status_code == 400


def test_empty_filename_raises_400():
    with pytest.raises(UploadValidationError) as ei:
        validate_extension("", SUPPORTED)
    assert ei.value.status_code == 400


def test_unsupported_extension_raises_400():
    with pytest.raises(UploadValidationError) as ei:
        validate_extension("track.txt", SUPPORTED)
    assert ei.value.status_code == 400


# ---- duration ----

def test_duration_under_max_ok():
    validate_duration(300.0, 600)  # should not raise


def test_duration_exactly_max_ok():
    validate_duration(600.0, 600)  # inclusive boundary


def test_duration_over_max_raises_400():
    with pytest.raises(UploadValidationError) as ei:
        validate_duration(600.1, 600)
    assert ei.value.status_code == 400


def test_zero_duration_raises_400():
    with pytest.raises(UploadValidationError) as ei:
        validate_duration(0.0, 600)
    assert ei.value.status_code == 400


# ---- streaming size cap ----

class _FakeUpload:
    """Minimal async chunked reader mimicking UploadFile.read(size)."""

    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    async def read(self, size: int) -> bytes:
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk


def test_stream_under_cap_writes_full_file(tmp_path):
    data = b"x" * 1000
    dest = tmp_path / "out.bin"
    total = asyncio.run(
        stream_to_disk(_FakeUpload(data).read, str(dest), max_bytes=2000, chunk_size=256)
    )
    assert total == 1000
    assert dest.read_bytes() == data


def test_stream_exactly_at_cap_ok(tmp_path):
    data = b"x" * 1000
    dest = tmp_path / "out.bin"
    total = asyncio.run(
        stream_to_disk(_FakeUpload(data).read, str(dest), max_bytes=1000, chunk_size=256)
    )
    assert total == 1000


def test_stream_over_cap_raises_413(tmp_path):
    data = b"x" * 3000
    dest = tmp_path / "out.bin"
    with pytest.raises(UploadValidationError) as ei:
        asyncio.run(
            stream_to_disk(_FakeUpload(data).read, str(dest), max_bytes=1000, chunk_size=256)
        )
    assert ei.value.status_code == 413


def test_stream_aborts_early_without_reading_whole_file(tmp_path):
    # An oversized upload must not be fully buffered: once the cap is passed we
    # stop reading, so the reader's position should be well short of the end.
    data = b"x" * 100_000
    dest = tmp_path / "out.bin"
    reader = _FakeUpload(data)
    with pytest.raises(UploadValidationError):
        asyncio.run(stream_to_disk(reader.read, str(dest), max_bytes=1000, chunk_size=256))
    assert reader._pos < len(data)


# ---- decode probe (real librosa; skipped if the audio stack is absent) ----

def test_probe_duration_rejects_garbage_file(tmp_path):
    pytest.importorskip("librosa")
    from app.upload_validation import probe_duration

    fake = tmp_path / "not_really.mp3"
    fake.write_bytes(b"this is plain text, not audio")
    with pytest.raises(UploadValidationError) as ei:
        probe_duration(str(fake))
    assert ei.value.status_code == 400


def test_probe_duration_returns_length_for_real_audio(tmp_path):
    pytest.importorskip("librosa")
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    from app.upload_validation import probe_duration

    path = tmp_path / "tone.wav"
    sr = 22050
    sf.write(str(path), np.zeros(sr * 2, dtype="float32"), sr)  # 2 seconds
    assert probe_duration(str(path)) == pytest.approx(2.0, abs=0.05)
