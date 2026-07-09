"""Endpoint tests for /api/process error taxonomy (TestClient, no network).

These verify that the endpoint maps failures to the right status codes:
  - bad user input (wrong type / oversized / undecodable / too long) -> 4xx
  - upstream Replicate timeout/error -> 502
  - unexpected pipeline bug -> 500
No real Replicate or librosa call is made; the paid/heavy functions are patched.
"""

import pytest
from fastapi.testclient import TestClient

from app.exceptions import UpstreamServiceError
from app.upload_validation import UploadValidationError


@pytest.fixture
def client(monkeypatch):
    from app.limiter import limiter
    from app.main import app

    # Rate limiting is per-IP; the suite reuses one client IP, so disable it or
    # later tests would 429 after 5 posts.
    limiter.enabled = False
    return TestClient(app, raise_server_exceptions=False)


def _post(client, filename="song.mp3", data=b"fake-audio-bytes", content_type="audio/mpeg"):
    return client.post("/api/process", files={"file": (filename, data, content_type)})


def test_rejects_unsupported_extension(client):
    # Wrong type is rejected before any decode or Replicate spend.
    r = _post(client, filename="evil.txt", content_type="text/plain")
    assert r.status_code == 400


def test_rejects_oversized_upload(client, monkeypatch):
    from app.config import settings

    # Shrink the cap so a tiny payload trips it, without a huge test fixture.
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 0.0001)  # ~104 bytes
    r = _post(client, data=b"x" * 5000)
    assert r.status_code == 413


def test_rejects_undecodable_file(client, monkeypatch):
    import app.api.process as process

    def _boom(_path):
        raise UploadValidationError(400, "Could not decode audio file.")

    monkeypatch.setattr(process, "probe_duration", _boom)
    r = _post(client)
    assert r.status_code == 400


def test_rejects_too_long_file(client, monkeypatch):
    import app.api.process as process
    from app.config import settings

    monkeypatch.setattr(process, "probe_duration", lambda _p: settings.MAX_DURATION_SEC + 1.0)
    r = _post(client)
    assert r.status_code == 400


def test_upstream_timeout_surfaces_as_502(client, monkeypatch):
    import app.api.process as process
    import app.services.song_analyzer as song_analyzer
    import app.services.stem_separator as stem_separator

    # Skip real decode; make structure analysis succeed cheaply.
    monkeypatch.setattr(process, "probe_duration", lambda _p: 5.0)

    async def _fake_structure(_path):
        return {"segments": [{"start": 0.0, "end": 5.0, "label": "verse"}], "bpm": 120.0, "downbeats": [], "beats": []}

    async def _timeout(_path, _out):
        raise UpstreamServiceError("Stem separation timed out")

    monkeypatch.setattr(song_analyzer, "analyze_structure", _fake_structure)
    monkeypatch.setattr(stem_separator, "separate_stems", _timeout)

    r = _post(client)
    assert r.status_code == 502


def test_unexpected_pipeline_bug_surfaces_as_500(client, monkeypatch):
    import app.api.process as process
    import app.services.song_analyzer as song_analyzer
    import app.services.stem_separator as stem_separator

    monkeypatch.setattr(process, "probe_duration", lambda _p: 5.0)

    async def _fake_structure(_path):
        return {"segments": [{"start": 0.0, "end": 5.0, "label": "verse"}], "bpm": 120.0, "downbeats": [], "beats": []}

    async def _bug(_path, _out):
        raise ValueError("unexpected pipeline bug")

    monkeypatch.setattr(song_analyzer, "analyze_structure", _fake_structure)
    monkeypatch.setattr(stem_separator, "separate_stems", _bug)

    r = _post(client)
    assert r.status_code == 500
