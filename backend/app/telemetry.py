"""Lightweight, dependency-free observability: structured stdout logs + in-memory counters.

No paid SaaS here by design (subscription-first / cost-conscious). Railway
captures stdout, so a structured, single-line log record IS the whole transport:
`railway logs | grep event=pipeline_failure` is the "dashboard". Counters are
process-local and reset on restart, which is fine for a single-instance service
(see the caveat on the GET /api/metrics endpoint).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping
from typing import Any

# A dedicated logger name so these records are easy to filter in Railway logs
# and can be tuned independently of the noisy uvicorn/root loggers.
logger = logging.getLogger("observability")

# Cap on any single field's rendered length. Error strings and stack traces can
# be unbounded; we never want one report to blow up a log line (or costs).
_MAX_FIELD_CHARS = 2000

_lock = threading.Lock()
_counters: dict[str, int] = {}


def increment(name: str, amount: int = 1) -> int:
    """Bump a named counter and return its new value. Thread-safe."""
    with _lock:
        _counters[name] = _counters.get(name, 0) + amount
        return _counters[name]


def snapshot() -> dict[str, int]:
    """Return a copy of all counters. Thread-safe."""
    with _lock:
        return dict(_counters)


def _reset_counters_for_test() -> None:
    """Clear all counters. Test-only helper; not used in production paths."""
    with _lock:
        _counters.clear()


def format_fields(fields: Mapping[str, Any]) -> str:
    """Render an ordered mapping as one grep-friendly `key=value` line.

    - Keys with a value of None are dropped (keeps optional fields tidy).
    - Every value is coerced to str with internal whitespace/newlines collapsed
      to single spaces, so one event is always exactly one log line.
    - Values are truncated to a fixed budget so no single field can produce an
      unbounded log record.
    """
    parts: list[str] = []
    for key, value in fields.items():
        if value is None:
            continue
        text = " ".join(str(value).split())
        if len(text) > _MAX_FIELD_CHARS:
            text = text[:_MAX_FIELD_CHARS] + "...(truncated)"
        parts.append(f"{key}={text}")
    return " ".join(parts)


def log_pipeline_failure(
    *,
    job_id: str,
    stage: str,
    http_status: int,
    error: BaseException,
    duration_sec: float,
) -> None:
    """Emit one structured line for a failed /api/process run.

    Deliberately excludes the uploaded audio and any secret; the fields are the
    minimum needed to debug from Railway logs: which job, which pipeline stage,
    what kind of error, how long it ran, and the HTTP status the client saw.
    """
    increment("pipeline_failures")
    line = format_fields(
        {
            "event": "pipeline_failure",
            "job_id": job_id,
            "stage": stage,
            "http_status": http_status,
            "error_type": type(error).__name__,
            "error": str(error),
            "duration_sec": round(duration_sec, 2),
        }
    )
    logger.warning(line)
