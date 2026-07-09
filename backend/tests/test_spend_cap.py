"""Tests for the global daily spend cap."""

from datetime import datetime, timezone

from app.spend_cap import DailySpendTracker


def _clock(dt):
    """Return a callable that always yields the given datetime."""
    return lambda: dt


def test_allows_spend_under_cap():
    tracker = DailySpendTracker(cap_usd=1.0, clock=_clock(datetime(2026, 7, 8, tzinfo=timezone.utc)))
    assert tracker.try_spend(0.4) is True
    assert tracker.try_spend(0.4) is True


def test_rejects_spend_that_would_exceed_cap():
    tracker = DailySpendTracker(cap_usd=1.0, clock=_clock(datetime(2026, 7, 8, tzinfo=timezone.utc)))
    assert tracker.try_spend(0.6) is True
    # 0.6 + 0.6 = 1.2 > 1.0, so this must be rejected and NOT recorded.
    assert tracker.try_spend(0.6) is False
    # The rejected attempt did not consume budget, so a smaller one still fits.
    assert tracker.try_spend(0.4) is True


def test_exact_cap_is_allowed():
    tracker = DailySpendTracker(cap_usd=1.0, clock=_clock(datetime(2026, 7, 8, tzinfo=timezone.utc)))
    assert tracker.try_spend(1.0) is True
    assert tracker.try_spend(0.01) is False


def test_counter_resets_on_new_utc_day():
    now = {"dt": datetime(2026, 7, 8, 23, 59, tzinfo=timezone.utc)}
    tracker = DailySpendTracker(cap_usd=1.0, clock=lambda: now["dt"])
    assert tracker.try_spend(1.0) is True
    assert tracker.try_spend(0.5) is False
    # Cross into the next UTC day — budget should reset.
    now["dt"] = datetime(2026, 7, 9, 0, 1, tzinfo=timezone.utc)
    assert tracker.try_spend(1.0) is True


def test_remaining_reflects_spend():
    tracker = DailySpendTracker(cap_usd=2.0, clock=_clock(datetime(2026, 7, 8, tzinfo=timezone.utc)))
    assert tracker.remaining() == 2.0
    tracker.try_spend(0.5)
    assert tracker.remaining() == 1.5


def test_zero_or_negative_cap_rejects_everything():
    tracker = DailySpendTracker(cap_usd=0.0, clock=_clock(datetime(2026, 7, 8, tzinfo=timezone.utc)))
    assert tracker.try_spend(0.01) is False
