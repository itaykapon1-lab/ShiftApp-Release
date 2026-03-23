"""Shift Pydantic Schemas.

UNIFIED SCHEMA - Aligned with Frontend Expectations
Accepts and returns complex nested task structures (tasks_data).

CRITICAL: All dates are normalized to the Canonical Epoch Week (Jan 1-7, 2024)
to prevent "Date Drift" bugs.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from app.utils.date_normalization import normalize_to_canonical_week


class ShiftCreate(BaseModel):
    """Schema for creating a new shift (Frontend -> Backend).

    CRITICAL: Frontend sends:
    {
        "shift_id": "S...",
        "name": "Evening Service",
        "start_time": "2026-01-14T18:00:00",
        "end_time": "2026-01-14T23:00:00",
        "tasks_data": {
            "tasks": [
                {
                    "task_id": "task_123",
                    "name": "Service Staff",
                    "options": [
                        {
                            "preference_score": 0,
                            "requirements": [
                                {"count": 2, "required_skills": {"Waiter": 5, "French": 3}}
                            ]
                        }
                    ]
                }
            ]
        }
    }

    DATE NORMALIZATION: start_time and end_time are automatically normalized
    to the Canonical Epoch Week (Jan 1-7, 2024) to ensure consistency.
    """
    shift_id: str
    name: str
    start_time: str  # ISO datetime string from frontend
    end_time: str    # ISO datetime string from frontend
    # Use Dict[str, Any] to prevent validation errors when task structure evolves
    tasks_data: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None  # Optional since middleware may inject it

    @field_validator('start_time')
    @classmethod
    def normalize_start_time(cls, v: str) -> str:
        """Normalize start_time to Canonical Epoch Week."""
        if not v:
            return v
        normalized = normalize_to_canonical_week(v)
        return normalized.isoformat()

    @field_validator('end_time')
    @classmethod
    def normalize_end_time(cls, v: str) -> str:
        """Normalize end_time to Canonical Epoch Week."""
        if not v:
            return v
        normalized = normalize_to_canonical_week(v)
        return normalized.isoformat()

    @model_validator(mode="after")
    def normalize_task_skill_keys(self) -> "ShiftCreate":
        """Normalize required_skills keys to Title Case in tasks_data.

        Ensures case-insensitive skill matching with Worker skills, which are
        normalized to Title Case by ``Worker.set_skill_level()``.  This prevents
        a mismatch where e.g. ``"cook"`` in a task fails to match ``"Cook"`` on
        a worker, causing false "SKILL GAP" errors in the solver preflight.
        """
        if not self.tasks_data:
            return self
        tasks: List[Dict[str, Any]] = self.tasks_data.get("tasks", [])
        for task in tasks:
            for option in task.get("options", []):
                for req in option.get("requirements", []):
                    raw_skills: Dict[str, Any] = req.get("required_skills", {})
                    if raw_skills:
                        req["required_skills"] = {
                            k.strip().title(): v
                            for k, v in raw_skills.items()
                        }
        return self


class ShiftRead(BaseModel):
    """Schema for reading shift data (Backend -> Frontend).

    CRITICAL: Frontend expects the SAME structure it sent.
    Dates are returned in Canonical Epoch Week format.
    """
    shift_id: str
    name: str
    start_time: str  # Return as ISO string for frontend consumption
    end_time: str    # Return as ISO string for frontend consumption
    tasks_data: Dict[str, Any] = Field(default_factory=dict)
    session_id: str

    class Config:
        from_attributes = True  # Allow ORM models
