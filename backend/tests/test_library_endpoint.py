"""No-mock TestClient tests for the read-only endpoints.

These exercise the real FastAPI app end to end with no internal mocking and no
Replicate: health, the library catalog, single-song lookup (including slug
validation and 404), and the /clips static mount. The catalog/slug data comes
from the git-committed library/ tree.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_library_lists_catalog_with_license(client):
    r = client.get("/api/library")
    assert r.status_code == 200
    catalog = r.json()
    assert isinstance(catalog, list)
    assert len(catalog) >= 1
    for entry in catalog:
        assert entry.get("license"), f"{entry.get('slug')} missing license"
        assert "artist" in entry


def test_get_known_song_returns_metadata(client):
    # sweet-thang is one of the committed curated songs.
    r = client.get("/api/library/sweet-thang")
    assert r.status_code == 200
    assert r.json().get("slug") == "sweet-thang" or "name" in r.json()


def test_get_unknown_song_404(client):
    r = client.get("/api/library/does-not-exist")
    assert r.status_code == 404


def test_invalid_slug_rejected_400(client):
    # Uppercase fails the slug regex before any filesystem lookup.
    r = client.get("/api/library/NotASlug")
    assert r.status_code == 400


def test_path_traversal_slug_rejected(client):
    # Encoded traversal must not escape the library dir; it fails slug validation
    # (400) or is simply not found (404) — never a 200 leaking a file.
    r = client.get("/api/library/..%2f..%2fetc%2fpasswd")
    assert r.status_code in (400, 404)


def test_clips_missing_file_404(client):
    r = client.get("/clips/nope/missing.wav")
    assert r.status_code == 404
