"""Endpoint tests for the client observability routes (TestClient, no network)."""

import pytest
from fastapi.testclient import TestClient

from app import telemetry


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _clean_counters():
    telemetry._reset_counters_for_test()
    yield
    telemetry._reset_counters_for_test()


# ---- /api/client-error ----

def test_client_error_accepts_minimal_payload(client):
    r = client.post("/api/client-error", json={"message": "boom"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert telemetry.snapshot()["client_errors"] == 1


def test_client_error_requires_message(client):
    r = client.post("/api/client-error", json={"source": "app.js"})
    assert r.status_code == 422


def test_client_error_rejects_oversized_message(client):
    r = client.post("/api/client-error", json={"message": "x" * 2000})
    assert r.status_code == 422


def test_client_error_logs_structured_line(client, caplog):
    import logging

    with caplog.at_level(logging.WARNING, logger="observability"):
        client.post(
            "/api/client-error",
            json={"message": "TypeError: undefined", "source": "app.js", "lineno": 42},
        )
    line = caplog.records[-1].message
    assert "event=client_error" in line
    assert "message=TypeError: undefined" in line
    assert "lineno=42" in line


# ---- /api/client-event ----

def test_client_event_increments_allowed_counter(client):
    r = client.post("/api/client-event", json={"event": "song_played"})
    assert r.status_code == 200
    assert r.json()["count"] == 1
    assert telemetry.snapshot()["song_played"] == 1


def test_client_event_rejects_unknown_event(client):
    r = client.post("/api/client-event", json={"event": "hack"})
    assert r.status_code == 422
    assert "song_played" not in telemetry.snapshot()


# ---- /api/metrics ----

def test_metrics_returns_counter_snapshot(client):
    client.post("/api/client-event", json={"event": "session_started"})
    client.post("/api/client-event", json={"event": "session_started"})
    r = client.get("/api/metrics")
    assert r.status_code == 200
    assert r.json()["session_started"] == 2
