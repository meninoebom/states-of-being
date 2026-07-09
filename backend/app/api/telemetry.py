"""Minimal client-side observability endpoints.

Three tiny routes, no dashboard, no paid SaaS:
  - POST /api/client-error : unhandled frontend errors (window.onerror /
    unhandledrejection) land here and are logged as one structured stdout line.
  - POST /api/client-event : increments a named counter (session_started,
    song_played) so we have a usage signal to tune mappings against.
  - GET  /api/metrics      : reads the in-memory counters back as JSON. Not a
    dashboard, just a verifiable readout. Counters are process-local and reset
    on deploy/restart; that is acceptable for a single-instance service.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app import telemetry
from app.client_ip import extract_client_ip
from app.limiter import limiter

router = APIRouter()

# These routes are public and unauthenticated. The frontend self-caps error
# reports, but that is client-side only; a per-IP limit stops a hostile client
# from flooding Railway logs (and our costs) with unbounded POSTs. Generous
# enough that legitimate use (one session_started + a few plays/errors) never
# trips it.
_TELEMETRY_LIMIT = "60/minute"

# Only these events increment a counter. An allowlist keeps a noisy or hostile
# client from inflating arbitrary counter names in memory.
ALLOWED_EVENTS = {"session_started", "song_played"}


class ClientError(BaseModel):
    """A shape mirroring the browser's ErrorEvent / unhandledrejection.

    Field lengths are capped so a runaway client cannot post huge payloads;
    pydantic rejects anything over the limit with a 422 before we log it.
    """

    message: str = Field(max_length=1000)
    source: str | None = Field(default=None, max_length=1000)
    lineno: int | None = None
    colno: int | None = None
    stack: str | None = Field(default=None, max_length=4000)
    page: str | None = Field(default=None, max_length=1000)
    user_agent: str | None = Field(default=None, max_length=500)


class ClientEvent(BaseModel):
    event: str = Field(max_length=100)


def _client_ip(request: Request) -> str:
    fallback = request.client.host if request.client else "unknown"
    return extract_client_ip(request.headers.get("x-forwarded-for"), fallback)


@router.post("/client-error")
@limiter.limit(_TELEMETRY_LIMIT)
async def report_client_error(request: Request, err: ClientError) -> dict:
    """Log an unhandled frontend error so a human can see it in Railway logs."""
    telemetry.increment("client_errors")
    line = telemetry.format_fields(
        {
            "event": "client_error",
            "message": err.message,
            "source": err.source,
            "lineno": err.lineno,
            "colno": err.colno,
            "page": err.page,
            "client_ip": _client_ip(request),
            "user_agent": err.user_agent,
            "stack": err.stack,
        }
    )
    telemetry.logger.warning(line)
    return {"ok": True}


@router.post("/client-event")
@limiter.limit(_TELEMETRY_LIMIT)
async def report_client_event(request: Request, evt: ClientEvent) -> dict:
    """Increment a usage counter for an allowlisted event."""
    if evt.event not in ALLOWED_EVENTS:
        raise HTTPException(422, f"Unknown event: {evt.event}")
    count = telemetry.increment(evt.event)
    telemetry.logger.info(
        telemetry.format_fields({"event": "counter", "name": evt.event, "count": count})
    )
    return {"ok": True, "count": count}


@router.get("/metrics")
async def metrics() -> dict:
    """Read the in-memory counters back as JSON (process-local, resets on restart)."""
    return telemetry.snapshot()
