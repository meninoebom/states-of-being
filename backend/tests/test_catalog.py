"""Unit tests for catalog metadata schema validation and loading.

Covers the enriched catalog fields added in #21: artist, duration, and the
legally-sensitive REQUIRED `license` field. No network, no librosa.
"""

import json

import pytest

from app.catalog import (
    REQUIRED_FIELDS,
    CatalogValidationError,
    load_catalog,
    validate_song_entry,
)


def _valid_entry(**overrides):
    entry = {
        "slug": "sweet-thang",
        "name": "Sweet Thang",
        "artist": "Some Artist",
        "duration": 189.75,
        "license": "CC-BY-4.0",
    }
    entry.update(overrides)
    return entry


# ---- validate_song_entry ----

def test_valid_entry_passes():
    validate_song_entry(_valid_entry())  # should not raise


def test_license_is_required():
    assert "license" in REQUIRED_FIELDS


def test_missing_license_raises():
    entry = _valid_entry()
    del entry["license"]
    with pytest.raises(CatalogValidationError) as ei:
        validate_song_entry(entry)
    assert "license" in str(ei.value)


def test_empty_license_raises():
    with pytest.raises(CatalogValidationError):
        validate_song_entry(_valid_entry(license=""))


def test_whitespace_only_license_raises():
    with pytest.raises(CatalogValidationError):
        validate_song_entry(_valid_entry(license="   "))


def test_missing_slug_raises():
    entry = _valid_entry()
    del entry["slug"]
    with pytest.raises(CatalogValidationError):
        validate_song_entry(entry)


def test_missing_name_raises():
    entry = _valid_entry()
    del entry["name"]
    with pytest.raises(CatalogValidationError):
        validate_song_entry(entry)


def test_error_names_the_source():
    with pytest.raises(CatalogValidationError) as ei:
        validate_song_entry(_valid_entry(license=""), source="catalog.json[0]")
    assert "catalog.json[0]" in str(ei.value)


# ---- load_catalog ----

def test_load_catalog_reads_and_validates(tmp_path):
    catalog = [_valid_entry(), _valid_entry(slug="other", name="Other")]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog))
    loaded = load_catalog(path)
    assert len(loaded) == 2


def test_load_catalog_rejects_entry_missing_license(tmp_path):
    bad = _valid_entry()
    del bad["license"]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps([_valid_entry(), bad]))
    with pytest.raises(CatalogValidationError):
        load_catalog(path)


def test_load_catalog_missing_file_returns_empty(tmp_path):
    assert load_catalog(tmp_path / "nope.json") == []


# ---- the real committed library must satisfy the schema ----

def test_committed_catalog_is_valid():
    from pathlib import Path

    catalog_path = (
        Path(__file__).parent.parent.parent / "library" / "catalog.json"
    )
    loaded = load_catalog(catalog_path)
    assert len(loaded) == 4
    for entry in loaded:
        assert entry["license"], f"{entry['slug']} missing license"
        assert "artist" in entry
        assert isinstance(entry["duration"], (int, float))
        assert entry["duration"] > 0
