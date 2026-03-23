"""Scheduling Data Structures.

This module defines the Data Transfer Objects (DTOs) used to transport
parsed scheduling data between the Input Layer (Parsers) and the
Processing Layer (Solver/Service).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List

from domain.worker_model import Worker
from domain.shift_model import Shift
# NOTE: This import references the DEPRECATED constraint config module.
# It is used here only as a type hint for the DTO field.
# See Tech Debt #1 — solver/constraints/config.py is scheduled for removal.
from solver.constraints.config import ConstraintConfig


@dataclass
class SchedulingData:
    """A container for all data required to define a scheduling problem.

    This class aggregates workers, shifts, constraints, and time metadata
    into a single object. It is typically instantiated by a Parser (e.g.,
    CsvScheduleParser) and consumed by the DataManager or SolverEngine.

    Attributes:
        workers (List[Worker]): A list of Worker domain objects representing
            the available staff, their skills, and availabilities.
        shifts (List[Shift]): A list of Shift domain objects representing
            the slots that need to be staffed.
        constraint_config (ConstraintConfig): A configuration object containing
            global rules (e.g., max hours) and dynamic rules (e.g.,
            mutual exclusions).
        week_start_date (datetime): The reference start date for the schedule.
            This is crucial for mapping generic days (e.g., "Monday") to
            concrete timestamps.
    """
    # All available staff with their skills, availability windows, and preferences
    workers: List[Worker]
    # All time slots that need to be staffed, each containing task requirements
    shifts: List[Shift]
    # Global constraint rules (max hours, mutual exclusions, co-locations)
    constraint_config: ConstraintConfig
    # Reference anchor for mapping day names (e.g., "Monday") to concrete dates.
    # In the canonical system, this is always 2024-01-01 (Monday of epoch week).
    week_start_date: datetime