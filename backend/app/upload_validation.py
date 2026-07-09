"""Pre-spend upload validation for /api/process.

Everything here runs BEFORE any paid Replicate call. The goal is to reject bad
input cheaply (wrong type, oversized, undecodable, too long) so we never pay
Replicate to process garbage. Every failure raises UploadValidationError, which
the endpoint maps to a 4xx status: it is the client's input that is wrong, as
opposed to an upstream failure (502) or a pipeline bug (500).

The functions are deliberately small and pure so they can be unit-tested without
librosa, Replicate, or a running server. `probe_duration` is the one exception:
it needs librosa to decode, so it is imported lazily and exercised separately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable

# 1 MiB read chunk: large enough to keep syscalls cheap, small enough that an
# oversized upload is caught within a megabyte rather than after buffering it all.
_CHUNK_SIZE = 1 << 20


class UploadValidationError(Exception):
    """A pre-spend upload check failed. Carries the HTTP status to return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def validate_extension(filename: str | None, supported: set[str]) -> str:
    """Return the lowercased file extension, or raise 400 if missing/unsupported.

    Extension (plus the later decode probe) is our real type check; the browser-
    supplied content-type is unreliable and not trusted here.
    """
    if not filename:
        raise UploadValidationError(400, "Filename is required")
    ext = Path(filename).suffix.lower()
    if ext not in supported:
        raise UploadValidationError(
            400, f"Unsupported format. Accepted: {', '.join(sorted(supported))}"
        )
    return ext


def validate_duration(duration_sec: float, max_sec: float) -> None:
    """Raise 400 if the audio is empty or longer than max_sec.

    Duration is the real cost driver: Replicate bills by the audio length it
    processes, so a multi-hour file is the expensive-mistake case we guard.
    The upper bound is inclusive (exactly max_sec is allowed).
    """
    if duration_sec <= 0:
        raise UploadValidationError(400, "Audio file appears to be empty or unreadable")
    if duration_sec > max_sec:
        raise UploadValidationError(
            400,
            f"Audio is too long ({duration_sec / 60:.1f} min). "
            f"Maximum is {max_sec / 60:.0f} minutes.",
        )


async def stream_to_disk(
    read_chunk: Callable[[int], Awaitable[bytes]],
    dest_path: str,
    max_bytes: int,
    chunk_size: int = _CHUNK_SIZE,
) -> int:
    """Stream an upload to disk in chunks, aborting once it exceeds max_bytes.

    We never hold the whole file in memory and we stop reading the moment the cap
    is passed, so an oversized upload cannot exhaust RAM. The byte cap is
    inclusive: a file exactly max_bytes long is accepted. Returns the number of
    bytes written. A partial file may be left on disk when the cap is exceeded;
    the caller cleans up the job directory on failure.

    read_chunk is any async callable(size)->bytes, e.g. UploadFile.read.
    """
    total = 0
    with open(dest_path, "wb") as f:
        while True:
            chunk = await read_chunk(chunk_size)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                mb = max_bytes / (1024 * 1024)
                raise UploadValidationError(413, f"File exceeds {mb:.0f}MB limit")
            f.write(chunk)
    return total


def probe_duration(path: str) -> float:
    """Decode-probe the file and return its duration in seconds.

    This doubles as a corruption/mislabel check: librosa raises on files it
    cannot decode (a text file renamed .mp3, a truncated upload), which we
    translate to a 400. Runs before any Replicate spend. Import is lazy so the
    other validators stay usable without librosa installed.
    """
    import librosa

    try:
        return float(librosa.get_duration(path=path))
    except Exception as e:  # noqa: BLE001 - any decode failure means bad input
        raise UploadValidationError(
            400, "Could not decode audio file. It may be corrupt or not a real audio file."
        ) from e
