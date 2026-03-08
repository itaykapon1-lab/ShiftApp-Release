"""Time utility models for the scheduling system.

This module provides the TimeWindow class, which is used to define
durations for shifts and worker availability.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class TimeWindow:
    """Represents a specific immutable span of time.

    Used to define when a shift starts and ends, or when a worker is available.

    Attributes:
        start (datetime): The start time of the window.
        end (datetime): The end time of the window.
    """
    start: datetime
    end: datetime

    def __post_init__(self):
        """Validates that start time is before end time."""
        if self.start >= self.end:
            raise ValueError(f"Start time {self.start} must be before end time {self.end}.")

    @property
    def duration_hours(self) -> float:
        """Calculates the duration of the window in hours."""
        delta = self.end - self.start
        return delta.total_seconds() / 3600.0

    def overlaps(self, other: 'TimeWindow') -> bool:
        """Checks if this window overlaps with another window."""
        return max(self.start, other.start) < min(self.end, other.end)

    def __repr__(self) -> str:
        # Format explicitly for clarity, e.g., "Mon 08:00-16:00"
        return f"{self.start.strftime('%a %H:%M')} - {self.end.strftime('%H:%M')}"