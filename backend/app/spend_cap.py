"""Global daily spend cap for Replicate-backed processing.

Each accepted /api/process request spends real money on Replicate (Demucs +
allin1). This module enforces a cumulative per-UTC-day budget so a burst of
uploads cannot run up an unbounded bill.

LIMITATION: the counter lives in memory. It is correct for the current
single-instance Railway deployment but does NOT coordinate across multiple
instances/replicas, and it resets to zero on process restart. If we ever scale
horizontally or need the cap to survive restarts, move this to a shared store
(Redis, Railway Postgres, etc.) keyed by UTC date.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DailySpendTracker:
    """Thread-safe, in-memory tracker of cumulative spend within a UTC day.

    The cap is inclusive: a spend that brings the running total exactly to the
    cap is allowed; anything beyond is rejected.
    """

    def __init__(self, cap_usd: float, clock=_utc_now):
        self._cap = cap_usd
        self._clock = clock
        self._lock = threading.Lock()
        self._day = None  # date of the currently tracked window
        self._spent = 0.0

    def _roll_if_new_day(self) -> None:
        """Reset the running total when the UTC day has changed. Caller holds the lock."""
        today = self._clock().date()
        if today != self._day:
            self._day = today
            self._spent = 0.0

    def try_spend(self, cost_usd: float) -> bool:
        """Atomically reserve `cost_usd` against today's budget.

        Returns True and records the spend if it fits within the cap; returns
        False and records nothing if it would exceed the cap.
        """
        with self._lock:
            self._roll_if_new_day()
            if self._spent + cost_usd > self._cap:
                return False
            self._spent += cost_usd
            return True

    def remaining(self) -> float:
        """Budget left for the current UTC day, never negative."""
        with self._lock:
            self._roll_if_new_day()
            return max(0.0, self._cap - self._spent)
