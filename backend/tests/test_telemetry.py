"""Unit tests for the observability helpers (pure formatting + counters)."""

import logging

import pytest

from app import telemetry


@pytest.fixture(autouse=True)
def _clean_counters():
    telemetry._reset_counters_for_test()
    yield
    telemetry._reset_counters_for_test()


# ---- format_fields ----

def test_format_fields_renders_key_value_line():
    assert telemetry.format_fields({"a": 1, "b": "x"}) == "a=1 b=x"


def test_format_fields_drops_none_values():
    assert telemetry.format_fields({"a": 1, "b": None, "c": 3}) == "a=1 c=3"


def test_format_fields_collapses_newlines_to_single_line():
    out = telemetry.format_fields({"stack": "line1\nline2\t  line3"})
    assert "\n" not in out
    assert out == "stack=line1 line2 line3"


def test_format_fields_truncates_long_values():
    out = telemetry.format_fields({"big": "x" * 5000})
    assert out.endswith("...(truncated)")
    assert len(out) < 5000


# ---- counters ----

def test_increment_and_snapshot():
    assert telemetry.increment("songs") == 1
    assert telemetry.increment("songs") == 2
    assert telemetry.increment("sessions", 3) == 3
    assert telemetry.snapshot() == {"songs": 2, "sessions": 3}


def test_snapshot_is_a_copy():
    telemetry.increment("x")
    snap = telemetry.snapshot()
    snap["x"] = 999
    assert telemetry.snapshot()["x"] == 1


# ---- log_pipeline_failure ----

def test_log_pipeline_failure_emits_structured_line(caplog):
    with caplog.at_level(logging.WARNING, logger="observability"):
        telemetry.log_pipeline_failure(
            job_id="abc123",
            stage="stem_separation",
            http_status=502,
            error=ValueError("demucs boom"),
            duration_sec=12.345,
        )
    line = caplog.records[-1].message
    assert "event=pipeline_failure" in line
    assert "job_id=abc123" in line
    assert "stage=stem_separation" in line
    assert "http_status=502" in line
    assert "error_type=ValueError" in line
    assert "duration_sec=12.35" in line  # rounded to 2 places


def test_log_pipeline_failure_bumps_counter_on_5xx():
    telemetry.log_pipeline_failure(
        job_id="j", stage="chop", http_status=500,
        error=RuntimeError("x"), duration_sec=1.0,
    )
    assert telemetry.snapshot()["pipeline_failures"] == 1


def test_log_pipeline_failure_does_not_count_4xx_user_errors(caplog):
    # A 4xx is the client's bad input, not a pipeline failure. It still logs a
    # line (for debugging) but must not inflate the failure counter.
    with caplog.at_level(logging.WARNING, logger="observability"):
        telemetry.log_pipeline_failure(
            job_id="j", stage="validate", http_status=413,
            error=ValueError("too big"), duration_sec=0.1,
        )
    assert "event=pipeline_failure" in caplog.records[-1].message
    assert "pipeline_failures" not in telemetry.snapshot()
