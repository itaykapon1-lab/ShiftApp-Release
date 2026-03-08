"""
Canonical Week Date Normalization Utility.

This module implements a "Zero Tolerance" date normalization policy to prevent
"Date Drift" bugs where shifts and worker availability exist on different dates.

ALL dates in the system are normalized to a single, fixed "Canonical Epoch Week":
- Monday:    2024-01-01
- Tuesday:   2024-01-02
- Wednesday: 2024-01-03
- Thursday:  2024-01-04
- Friday:    2024-01-05
- Saturday:  2024-01-06
- Sunday:    2024-01-07

This ensures that regardless of the input source (Excel, API, GUI), all dates
map to the same anchor week, making solver comparisons reliable.
"""

from datetime import datetime, date, timedelta
from typing import Union, Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# CANONICAL ANCHOR WEEK DEFINITION
# ============================================================================
# The week of January 1-7, 2024 (Monday through Sunday)
# January 1, 2024 is a Monday (weekday=0 in Python)

CANONICAL_ANCHOR_DATES = {
    0: date(2024, 1, 1),   # Monday
    1: date(2024, 1, 2),   # Tuesday
    2: date(2024, 1, 3),   # Wednesday
    3: date(2024, 1, 4),   # Thursday
    4: date(2024, 1, 5),   # Friday
    5: date(2024, 1, 6),   # Saturday
    6: date(2024, 1, 7),   # Sunday
}

# Day name mappings for convenience
DAY_NAME_TO_WEEKDAY = {
    'MON': 0, 'MONDAY': 0,
    'TUE': 1, 'TUESDAY': 1,
    'WED': 2, 'WEDNESDAY': 2,
    'THU': 3, 'THURSDAY': 3,
    'FRI': 4, 'FRIDAY': 4,
    'SAT': 5, 'SATURDAY': 5,
    'SUN': 6, 'SUNDAY': 6,
}

WEEKDAY_TO_DAY_NAME = {
    0: 'MON', 1: 'TUE', 2: 'WED', 3: 'THU', 4: 'FRI', 5: 'SAT', 6: 'SUN'
}


def normalize_to_canonical_week(dt: Union[datetime, date, str]) -> datetime:
    """
    Normalizes ANY datetime to the Canonical Epoch Week.

    Takes any date input, identifies its day of week, and returns the
    corresponding day in the anchor week (Jan 1-7, 2024), preserving
    the original time component.

    Args:
        dt: A datetime, date, or ISO string to normalize

    Returns:
        datetime: The normalized datetime in the canonical week

    Examples:
        >>> normalize_to_canonical_week(datetime(2030, 12, 9, 14, 30))  # Monday
        datetime(2024, 1, 1, 14, 30, 0)

        >>> normalize_to_canonical_week("2026-01-05T08:00:00")  # Monday
        datetime(2024, 1, 1, 8, 0, 0)

        >>> normalize_to_canonical_week(datetime(2025, 7, 13, 9, 0))  # Sunday
        datetime(2024, 1, 7, 9, 0, 0)
    """
    # Parse input to datetime
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    elif isinstance(dt, date) and not isinstance(dt, datetime):
        dt = datetime.combine(dt, datetime.min.time())

    # Get the weekday (0=Monday, 6=Sunday)
    weekday = dt.weekday()

    # Get the canonical anchor date for this weekday
    anchor_date = CANONICAL_ANCHOR_DATES[weekday]

    # Combine anchor date with original time
    normalized = datetime.combine(anchor_date, dt.time())

    logger.debug(
        f"📅 Date normalized: {dt.date()} ({dt.strftime('%A')}) → "
        f"{normalized.date()} (Canonical {normalized.strftime('%A')})"
    )

    return normalized


def normalize_time_range_to_canonical_week(
    start_time: Union[datetime, str],
    end_time: Union[datetime, str]
) -> tuple[datetime, datetime]:
    """
    Normalizes a time range (start, end) to the Canonical Week.

    Handles overnight shifts where end_time might be the next day.

    Args:
        start_time: Start of the time range
        end_time: End of the time range

    Returns:
        tuple: (normalized_start, normalized_end)
    """
    start_normalized = normalize_to_canonical_week(start_time)
    end_normalized = normalize_to_canonical_week(end_time)

    # Handle overnight shifts: if end is before start (time-wise), add a day
    if end_normalized <= start_normalized:
        # Check if it's actually an overnight shift (end time < start time)
        if isinstance(start_time, str):
            start_time = datetime.fromisoformat(start_time)
        if isinstance(end_time, str):
            end_time = datetime.fromisoformat(end_time)

        if end_time.time() < start_time.time():
            end_normalized += timedelta(days=1)

    return start_normalized, end_normalized


def get_canonical_date_for_day(day_name: str) -> date:
    """
    Gets the canonical anchor date for a given day name.

    Args:
        day_name: Day name (e.g., 'MON', 'Monday', 'TUE', etc.)

    Returns:
        date: The canonical date for that day

    Raises:
        ValueError: If day_name is not recognized
    """
    weekday = DAY_NAME_TO_WEEKDAY.get(day_name.upper())
    if weekday is None:
        raise ValueError(f"Unrecognized day name: '{day_name}'")

    return CANONICAL_ANCHOR_DATES[weekday]


def create_canonical_datetime(day_name: str, hour: int, minute: int = 0, second: int = 0) -> datetime:
    """
    Creates a canonical datetime from a day name and time components.

    Args:
        day_name: Day name (e.g., 'MON', 'Monday')
        hour: Hour (0-23)
        minute: Minute (0-59)
        second: Second (0-59)

    Returns:
        datetime: Canonical datetime for the specified day and time
    """
    anchor_date = get_canonical_date_for_day(day_name)
    return datetime.combine(anchor_date, datetime.min.time().replace(
        hour=hour, minute=minute, second=second
    ))


def parse_time_range_string(time_range: str) -> tuple[int, int, int, int]:
    """
    Parses a time range string like "08:00-16:00" into components.

    Args:
        time_range: Time range string in "HH:MM-HH:MM" format

    Returns:
        tuple: (start_hour, start_minute, end_hour, end_minute)
    """
    start_str, end_str = time_range.split('-')
    start_parts = start_str.strip().split(':')
    end_parts = end_str.strip().split(':')

    return (
        int(start_parts[0]),
        int(start_parts[1]) if len(start_parts) > 1 else 0,
        int(end_parts[0]),
        int(end_parts[1]) if len(end_parts) > 1 else 0,
    )


def normalize_availability_dict(
    availability_data: dict,
    preserve_preferences: bool = True
) -> dict:
    """
    Normalizes an availability dictionary to use canonical week dates.

    This is primarily for internal consistency checking. The Dict format
    itself is day-based (e.g., {"MON": {...}}) and doesn't contain dates,
    but this function validates and cleans the structure.

    Args:
        availability_data: Dict like {"MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}}
        preserve_preferences: Whether to keep preference data

    Returns:
        dict: Cleaned and validated availability dict
    """
    cleaned = {}

    for day_str, day_data in availability_data.items():
        # Validate day name
        day_upper = day_str.upper()
        if day_upper not in DAY_NAME_TO_WEEKDAY:
            logger.warning(f"Skipping unknown day name: {day_str}")
            continue

        # Normalize to standard 3-letter format
        normalized_day = WEEKDAY_TO_DAY_NAME[DAY_NAME_TO_WEEKDAY[day_upper]]

        # Handle both string and dict formats
        if isinstance(day_data, str):
            cleaned[normalized_day] = {
                "timeRange": day_data,
                "preference": "NEUTRAL"
            }
        elif isinstance(day_data, dict):
            cleaned[normalized_day] = {
                "timeRange": day_data.get("timeRange", "08:00-16:00"),
                "preference": day_data.get("preference", "NEUTRAL") if preserve_preferences else "NEUTRAL"
            }

    return cleaned


def is_canonical_date(dt: Union[datetime, date]) -> bool:
    """
    Checks if a date is already in the Canonical Epoch Week.

    Args:
        dt: Date or datetime to check

    Returns:
        bool: True if the date is in Jan 1-7, 2024
    """
    if isinstance(dt, datetime):
        dt = dt.date()

    return dt in CANONICAL_ANCHOR_DATES.values()


def get_day_name_from_datetime(dt: Union[datetime, date, str]) -> str:
    """
    Gets the 3-letter day name (MON, TUE, etc.) from a datetime.

    Args:
        dt: The datetime to extract day from

    Returns:
        str: 3-letter day name
    """
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)

    return WEEKDAY_TO_DAY_NAME[dt.weekday()]
