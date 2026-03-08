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
    workers: List[Worker]
    shifts: List[Shift]
    constraint_config: ConstraintConfig
    week_start_date: datetime