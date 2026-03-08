"""Worker domain model.

This module defines the Worker class, integrating capabilities (Quantified Skills),
hard constraints (Availability), and soft constraints (Preferences).
"""

from dataclasses import dataclass, field
from typing import List, Dict
from datetime import datetime

from domain.time_utils import TimeWindow

@dataclass
class Worker:
    """Represents an employee in the scheduling system.

    Attributes:
        name (str): The worker's full name.
        worker_id (str): Unique identifier.
        skills (Dict[str, int]): A dictionary mapping skill names to their proficiency
            level (1-10). Example: {"Chef": 5, "French": 3}.
        availability (List[TimeWindow]): Hard constraints - times when the worker
            can physically work.
        preferences (Dict[TimeWindow, int]): A mapping of time windows to preference scores.
    """
    name: str
    worker_id: str
    wage: float = 0.0
    min_hours: int = 0
    max_hours: int = 40
    # Changed from Set[Skill] to Dict[str, int]
    skills: Dict[str, int] = field(default_factory=dict)
    availability: List[TimeWindow] = field(default_factory=list)
    preferences: Dict[TimeWindow, int] = field(default_factory=dict)

    def set_skill_level(self, skill_name: str, level: int) -> None:
        """Sets or updates a skill to a specific proficiency level.

        Args:
            skill_name: The name of the skill (case-insensitive).
            level: The proficiency level (must be between 1 and 10).

        Raises:
            ValueError: If the level is not within the valid range (1-10).
        """
        if not (1 <= level <= 10):
            raise ValueError(f"Skill level must be between 1 and 10, got {level}")

        # Normalize skill name to Title Case (e.g., "cook" -> "Cook")
        clean_name = skill_name.strip().title()
        self.skills[clean_name] = level

    def get_skill_level(self, skill_name: str) -> int:
        """Returns the worker's level for a given skill.

        Args:
            skill_name: The name of the skill to check.

        Returns:
            int: The skill level (1-10), or 0 if the worker does not possess the skill.
        """
        clean_name = skill_name.strip().title()
        return self.skills.get(clean_name, 0)

    def has_skill_at_level(self, skill_name: str, min_level: int) -> bool:
        """Checks if the worker possesses a skill at or above a minimum requirement.

        Args:
            skill_name: The skill required.
            min_level: The minimum level needed.

        Returns:
            bool: True if worker level >= min_level.
        """
        return self.get_skill_level(skill_name) >= min_level

    def add_preference(self, time_window: TimeWindow, score: int):
        """Adds a direct preference score for a specific time window."""
        self.preferences[time_window] = score

    def add_availability(self, start: datetime, end: datetime) -> None:
        """Adds a time window where the worker is available to work."""
        window = TimeWindow(start, end)
        self.availability.append(window)

    def is_available_for_shift(self, shift_window: TimeWindow) -> bool:
        """Checks if the worker can work during the specific shift window."""
        for window in self.availability:
            # Check containment: Worker Start <= Shift Start AND Worker End >= Shift End
            if window.start <= shift_window.start and window.end >= shift_window.end:
                return True
        return False

    def calculate_preference_score(self, shift_window: TimeWindow) -> int:
        """Calculates the preference score for a given shift assignment.
        
        CRITICAL FIX: Uses time-of-day comparison instead of full datetime.
        This fixes the issue where preferences have different dates than shifts
        (e.g., preference on 2026-01-20, shift on 2026-01-13) but same times.

        Args:
            shift_window: The time window of the shift.
            
        Returns:
            int: Preference score (positive for HIGH, negative for LOW, 0 for no match)
        """
        # Extract time-of-day as (hour, minute) tuples
        shift_start_time = (shift_window.start.hour, shift_window.start.minute)
        shift_end_time = (shift_window.end.hour, shift_window.end.minute)
        
        # Check all preference windows
        for pref_window, score in self.preferences.items():
            pref_start_time = (pref_window.start.hour, pref_window.start.minute)
            pref_end_time = (pref_window.end.hour, pref_window.end.minute)
            
            # EXACT MATCH: Times match exactly (ignoring dates)
            if shift_start_time == pref_start_time and shift_end_time == pref_end_time:
                return score
            
            # CONTAINMENT: Shift time is within preference time window
            # Compare tuples: (8, 0) <= (9, 30) <= (17, 0)
            if (pref_start_time <= shift_start_time and
                shift_end_time <= pref_end_time):
                return score
        
        return 0

    def __repr__(self) -> str:
        skill_list = ", ".join([f"{k}:{v}" for k, v in self.skills.items()])
        return (f"Worker(Name='{self.name}', "
                f"Skills=[{skill_list}], "
                f"Avail={len(self.availability)}, "
                f"Prefs={len(self.preferences)})")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Worker):
            return NotImplemented
        return self.worker_id == other.worker_id

    def __hash__(self) -> int:
        return hash(self.worker_id)

    def add_skill(self, skill_name: str, level: int = 5) -> None:
        """Legacy helper — delegates to set_skill_level.

        Kept for backward compatibility with callers that use the old
        list-based skill format (e.g., sql_repo legacy path).
        """
        self.set_skill_level(skill_name, level)