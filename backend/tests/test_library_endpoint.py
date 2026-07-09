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
    assert r.json()["name"] == "Sweet Thang"


def test_get_unknown_song_404(client):
    r = client.get("/api/library/does-not-exist")
    assert r.status_code == 404


def test_invalid_slug_rejected_400(client):
    # Uppercase fails the slug regex before any filesystem lookup.
    r = client.get("/api/library/NotASlug")
    assert r.status_code == 400


def test_path_traversal_slug_rejected(client):
    # The %2f sequences decode to slashes, so the request no longer matches the
    # single-segment `/library/{slug}` route and 404s before any file read. The
    # security property under test is "never a 200 that leaks a file"; the
    # deterministic 400 regex-rejection path is covered by the uppercase test.
    r = client.get("/api/library/..%2f..%2fetc%2fpasswd")
    assert r.status_code == 404


def test_clips_missing_file_404(client):
    r = client.get("/clips/nope/missing.wav")
    assert r.status_code == 404


def test_malformed_catalog_fails_loud_500(client, monkeypatch, tmp_path):
    # A catalog entry missing its required `license` is a server-side data error:
    # list_songs must fail loud (500), not serve invalid data. Drives the real
    # `except CatalogValidationError` branch end to end.
    import json as _json

    from app.config import settings

    (tmp_path / "catalog.json").write_text(
        _json.dumps([{"slug": "bad", "name": "Bad", "artist": "X", "duration": 10.0}])
    )
    monkeypatch.setattr(settings, "LIBRARY_DIR", str(tmp_path))

    r = client.get("/api/library")
    assert r.status_code == 500
