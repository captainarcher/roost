"""Unit tests for compute_pre_arrival_send_time() pure function.

Only tests the pure scheduling calculation — does NOT import
schedule_pre_arrival_job or rebuild_pre_arrival_jobs, which trigger
FastAPI app initialization via `from app.main import scheduler`.

Business rule: Pre-arrival message is sent 2 days before check-in at
14:00 UTC (9:00 AM EST / 10:00 AM EDT).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.communication.scheduler import compute_pre_arrival_send_time


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


def test_compute_send_time_basic():
    """2 days before July 10 at 14:00 UTC = July 8 14:00 UTC."""
    check_in_date = date(2026, 7, 10)
    result = compute_pre_arrival_send_time(check_in_date)
    assert result == datetime(2026, 7, 8, 14, 0, 0, tzinfo=timezone.utc)


def test_compute_send_time_is_timezone_aware():
    """Returned datetime must be timezone-aware (UTC)."""
    result = compute_pre_arrival_send_time(date(2026, 7, 10))
    assert result.tzinfo is not None
    assert result.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Boundary cases
# ---------------------------------------------------------------------------


def test_compute_send_time_cross_month():
    """August 1 check-in → July 30 send time (crosses month boundary)."""
    check_in_date = date(2026, 8, 1)
    result = compute_pre_arrival_send_time(check_in_date)
    assert result == datetime(2026, 7, 30, 14, 0, 0, tzinfo=timezone.utc)


def test_compute_send_time_cross_year():
    """January 1 check-in → December 30 send time (crosses year boundary)."""
    check_in_date = date(2027, 1, 1)
    result = compute_pre_arrival_send_time(check_in_date)
    assert result == datetime(2026, 12, 30, 14, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Parameterized suite
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "check_in, expected",
    [
        (
            date(2026, 3, 5),
            datetime(2026, 3, 3, 14, 0, 0, tzinfo=timezone.utc),
        ),
        (
            date(2026, 12, 25),
            datetime(2026, 12, 23, 14, 0, 0, tzinfo=timezone.utc),
        ),
        (
            date(2026, 2, 28),
            datetime(2026, 2, 26, 14, 0, 0, tzinfo=timezone.utc),
        ),
    ],
)
def test_compute_send_time_various_dates(check_in: date, expected: datetime):
    """Send time is always check-in minus 2 days at 14:00 UTC."""
    assert compute_pre_arrival_send_time(check_in) == expected


# ---------------------------------------------------------------------------
# Time-of-day invariant
# ---------------------------------------------------------------------------


def test_compute_send_time_always_at_1400_utc():
    """Send time is always 14:00:00 UTC regardless of check-in date."""
    dates = [
        date(2026, 1, 15),
        date(2026, 6, 1),
        date(2026, 9, 30),
        date(2027, 3, 20),
    ]
    for check_in in dates:
        result = compute_pre_arrival_send_time(check_in)
        assert result.hour == 14, f"Expected hour=14 for check_in={check_in}, got {result.hour}"
        assert result.minute == 0, f"Expected minute=0 for check_in={check_in}, got {result.minute}"
        assert result.second == 0, f"Expected second=0 for check_in={check_in}, got {result.second}"
