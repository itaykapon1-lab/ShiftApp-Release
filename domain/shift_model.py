"""Shift domain model.

This module defines the Shift class, which aggregates a TimeWindow (when)
and a list of Tasks (what needs to be done).
"""

import uuid
from dataclasses import dataclass, field
from typing import List
from domain.time_utils import TimeWindow
from domain.task_model import Task  # Importing the Task model we wrote previously


@dataclass
class Shift:
    """Represents a scheduled work period containing one or more tasks.

    A Shift defines a specific time window. Inside this window, multiple
    tasks might need to be performed (simultaneously or covering the whole shift).

    The Solver will try to assign workers to fulfill the requirements of
    ALL tasks within this shift.

    Attributes:
        shift_id (str): Unique identifier.
        name (str): Human-readable name (e.g., "Sunday Morning Shift").
        time_window (TimeWindow): The duration of the shift.
        tasks (List[Task]): The list of jobs to be done during this shift.
    """
    name: str
    time_window: TimeWindow
    tasks: List[Task] = field(default_factory=list)
    shift_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def add_task(self, task: Task) -> None:
        """Adds a task requirement to this shift."""
        self.tasks.append(task)

    def __repr__(self) -> str:
        return (f"Shift(Name='{self.name}', "
                f"Time={self.time_window}, "
                f"Tasks={len(self.tasks)})")
                
    def __eq__(self, other: object) -> bool:
        """Equality based strictly on shift_id."""
        if not isinstance(other, Shift):
            return NotImplemented
        return self.shift_id == other.shift_id

    def __hash__(self) -> int:
        """Generates hash based on shift_id."""
        return hash(self.shift_id)