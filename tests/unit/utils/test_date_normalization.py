"""Unit tests for canonical week normalization utilities."""

from datetime import datetime

import pytest

from app.utils.date_normalization import (
    CANONICAL_ANCHOR_DATES,
    get_canonical_date_for_day,
    is_canonical_date,
    normalize_to_canonical_week,
)


pytestmark = [pytest.mark.unit]


def test_normalize_to_canonical_week_preserves_weekday_and_time():
    src = datetime(2026, 1, 22, 14, 30)  # Thursday
    out = normalize_to_canonical_week(src)
    assert out.weekday() == src.weekday()
    assert out.hour == 14
    assert out.minute == 30
    assert out.date() == CANONICAL_ANCHOR_DATES[3]


def test_get_canonical_date_for_day():
    assert get_canonical_date_for_day("MON").isoformat() == "2024-01-01"
    assert get_canonical_date_for_day("sunday").isoformat() == "2024-01-07"


def test_is_canonical_date():
    assert is_canonical_date(datetime(2024, 1, 1, 9, 0))
    assert not is_canonical_date(datetime(2026, 1, 1, 9, 0))

