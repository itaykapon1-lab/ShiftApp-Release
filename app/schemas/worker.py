"""Worker Pydantic Schemas.

UNIFIED SCHEMA - Aligned with Frontend Expectations
Accepts and returns complex nested structures (attributes with skills dict).
"""

import re
from typing import Dict, Optional, Any, List
from pydantic import BaseModel, Field, model_validator


# Time range validation pattern: HH:MM-HH:MM
TIME_RANGE_PATTERN = re.compile(
    r'^([01]?[0-9]|2[0-3]):([0-5][0-9])-([01]?[0-9]|2[0-3]):([0-5][0-9])$'
)

# Valid day codes
VALID_DAYS = {'SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT'}


def validate_time_range(time_str: str, context: str = "") -> List[str]:
    """Validate a time range string like '08:00-16:00'.

    Returns a list of error messages (empty if valid).
    """
    errors = []

    if not time_str or not isinstance(time_str, str):
        return errors  # Empty/null is allowed (means not available)

    time_str = time_str.strip()
    if not time_str:
        return errors

    # Check for invalid placeholder values
    invalid_values = {'anytime', 'any', 'n/a', 'na', 'none', 'all', 'flexible'}
    if time_str.lower() in invalid_values:
        errors.append(f"{context}Invalid availability '{time_str}'. Use format HH:MM-HH:MM (e.g., '08:00-16:00').")
        return errors

    # Handle comma-separated ranges
    ranges = [r.strip() for r in time_str.split(',')]

    for r in ranges:
        if not r:
            continue

        match = TIME_RANGE_PATTERN.match(r)
        if not match:
            errors.append(f"{context}Invalid time range '{r}'. Use format HH:MM-HH:MM (e.g., '08:00-16:00').")
            continue

        start_h, start_m, end_h, end_m = map(int, match.groups())

        # Validate logical time order (allow overnight shifts like 22:00-06:00)
        # Just ensure hours/minutes are valid (already checked by regex)
        start_mins = start_h * 60 + start_m
        end_mins = end_h * 60 + end_m

        # If end equals start, it's invalid (0-length shift)
        if start_mins == end_mins:
            errors.append(f"{context}Invalid time range '{r}': start and end times are the same.")

    return errors


def validate_availability_dict(availability: Dict[str, Any]) -> List[str]:
    """Validate an availability dictionary like {'MON': '08:00-16:00', ...}.

    Returns a list of error messages (empty if valid).
    """
    errors = []

    if not isinstance(availability, dict):
        return errors

    for day, time_range in availability.items():
        day_upper = day.upper() if isinstance(day, str) else str(day)

        # Validate day code
        if day_upper not in VALID_DAYS:
            errors.append(f"Invalid day code '{day}'. Valid codes: {', '.join(sorted(VALID_DAYS))}.")
            continue

        # Validate time range
        if time_range and isinstance(time_range, str):
            range_errors = validate_time_range(time_range, context=f"[{day}] ")
            errors.extend(range_errors)

    return errors


class WorkerCreate(BaseModel):
    """Schema for creating a new worker (Frontend -> Backend).

    CRITICAL: Frontend sends:
    {
        "worker_id": "W...",
        "name": "John Doe",
        "attributes": {
            "skills": {"Chef": 5, "Driver": 3},
            "availability": {"MON": "08:00-16:00", ...},
            "wage": 25.5,
            "min_hours": 0,
            "max_hours": 40
        }
    }
    """
    worker_id: str
    name: str
    # Use Dict[str, Any] to prevent validation errors when logic evolves
    attributes: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None  # Optional since middleware may inject it

    @model_validator(mode="after")
    def validate_worker_attributes(self) -> "WorkerCreate":
        """Validate worker attributes including availability."""
        errors = []

        # Validate name
        if not self.name or not self.name.strip():
            errors.append("Worker name cannot be empty.")

        # Validate availability if present
        availability = self.attributes.get("availability")
        if availability:
            avail_errors = validate_availability_dict(availability)
            errors.extend(avail_errors)

        # Validate wage if present
        wage = self.attributes.get("wage")
        if wage is not None:
            try:
                wage_val = float(wage)
                if wage_val < 0:
                    errors.append(f"Wage cannot be negative: {wage}")
            except (TypeError, ValueError):
                errors.append(f"Invalid wage value: {wage}")

        # Validate hours if present
        min_hours = self.attributes.get("min_hours")
        max_hours = self.attributes.get("max_hours")

        if min_hours is not None:
            try:
                min_h = float(min_hours)
                if min_h < 0:
                    errors.append(f"min_hours cannot be negative: {min_hours}")
            except (TypeError, ValueError):
                errors.append(f"Invalid min_hours value: {min_hours}")

        if max_hours is not None:
            try:
                max_h = float(max_hours)
                if max_h < 0:
                    errors.append(f"max_hours cannot be negative: {max_hours}")
            except (TypeError, ValueError):
                errors.append(f"Invalid max_hours value: {max_hours}")

        if min_hours is not None and max_hours is not None:
            try:
                if float(min_hours) > float(max_hours):
                    errors.append(f"min_hours ({min_hours}) cannot exceed max_hours ({max_hours}).")
            except (TypeError, ValueError):
                pass  # Already reported above

        if errors:
            raise ValueError("; ".join(errors))

        return self


class WorkerRead(BaseModel):
    """Schema for reading worker data (Backend -> Frontend).

    CRITICAL: Frontend expects the SAME structure it sent.
    We mirror the input structure to avoid breaking the UI.

    The ``warnings`` field carries non-fatal advisory messages about the worker's
    configuration state (e.g. missing availability). An empty list means no issues.
    """
    worker_id: str
    name: str
    attributes: Dict[str, Any] = Field(default_factory=dict)
    session_id: str
    warnings: List[str] = Field(default_factory=list)

    class Config:
        from_attributes = True  # Allow ORM models