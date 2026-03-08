"""SQLAlchemy ORM Models.

This module defines the database schema structure using SQLAlchemy's ORM.
It implements a 'Hybrid' architecture where relational columns are used for
indexing and lookups, while JSON columns are used for complex data structures.

The models inherit from `data.base.Base` to register with the engine.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, JSON, DateTime, Float, Text, UniqueConstraint, Index
from data.base import Base


def utc_now():
    """Returns current UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc)

class WorkerModel(Base):
    """Represents a worker (employee) in the system.

    This model serves as a persistent store for the `Worker` domain object.
    It uses a JSON column (`attributes`) to store flexible properties like
    skills, availability, and preferences, avoiding rigid schema changes.

    Attributes:
        worker_id (str): Primary Key. Unique UUID or ID of the worker.
        session_id (str): Indexed. Used for multi-tenancy isolation.
        name (str): The worker's display name.
        attributes (dict): JSON blob containing:
            - skills (List[str]): e.g., ['Chef', 'Driver']
            - availability (List[dict]): e.g., [{'start': '...', 'end': '...'}]
            - preferences (List[str]): Worker specific preferences.
    """
    __tablename__ = "workers"
    __table_args__ = (
        # Prevent duplicate workers with same name within a session
        UniqueConstraint('session_id', 'name', name='uq_worker_session_name'),
        # Optimize session-scoped lookups
        Index('ix_worker_session_name', 'session_id', 'name'),
    )

    worker_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)

    # Stores all complex domain properties
    attributes = Column(JSON, nullable=True)

    # Audit timestamps
    created_at = Column(DateTime, default=utc_now, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=True)


class ShiftModel(Base):
    """Represents a scheduled shift in the system.

    This model stores the time window as native SQL DateTime objects for
    efficient time-range queries, while storing the complex task hierarchy
    (requirements, options) in a JSON document.

    Attributes:
        shift_id (str): Primary Key. Unique identifier.
        session_id (str): Indexed. Used for multi-tenancy isolation.
        name (str): Human-readable shift name (e.g., 'Monday Morning').
        start_time (datetime): Start of the shift.
        end_time (datetime): End of the shift.
        tasks_data (list): JSON blob representing the tasks and requirements
            tree needed for this shift.
    """
    __tablename__ = "shifts"
    __table_args__ = (
        # Prevent duplicate shifts with same name within a session
        UniqueConstraint('session_id', 'name', name='uq_shift_session_name'),
        # Optimize session-scoped lookups
        Index('ix_shift_session_name', 'session_id', 'name'),
    )

    shift_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)

    # Native DateTime columns for correct DB sorting and filtering
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)

    # Flexible storage for Task/Option/Requirement objects
    tasks_data = Column(JSON, nullable=True)

    # Audit timestamps
    created_at = Column(DateTime, default=utc_now, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=True)


class SessionConfigModel(Base):
    """Stores session-wide configuration including constraints.

    This model persists global settings that are either parsed from Excel
    or manually configured through the UI. Each session has one config record.

    Attributes:
        session_id (str): Primary Key. Links to workers/shifts.
        constraints (list): JSON array of constraint objects with structure:
            [
                {
                    "id": 1,
                    "type": "HARD" | "SOFT",
                    "category": "max_hours" | "coverage" | etc,
                    "name": "Max Hours Per Week",
                    "description": "Limit weekly hours",
                    "params": {"max_hours": 40, "penalty": -50},
                    "enabled": true
                }
            ]
    """
    __tablename__ = "session_configs"

    session_id = Column(String, primary_key=True, index=True)
    constraints = Column(JSON, nullable=True, default=list)

    # Audit timestamps
    created_at = Column(DateTime, default=utc_now, nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=True)


class SolverJobModel(Base):
    """Persistent storage for solver job status and results.

    This replaces the in-memory _job_store dictionary to support:
    - Multi-worker deployments (Gunicorn with multiple workers)
    - Server restarts without losing job results
    - Cross-process visibility (ProcessPoolExecutor workers)

    Job Lifecycle:
        PENDING -> RUNNING -> COMPLETED | FAILED

    Attributes:
        job_id (str): Primary Key. UUID of the solver job.
        session_id (str): Indexed. Links to the user session.
        status (str): Current status (PENDING, RUNNING, COMPLETED, FAILED).
        created_at (datetime): When the job was created.
        started_at (datetime): When the solver started running.
        completed_at (datetime): When the solver finished.
        error_message (str): Error details if status is FAILED.
        result_status (str): Solver result (Optimal, Feasible, Infeasible).
        objective_value (float): Optimization score.
        theoretical_max_score (float): Best possible score.
        assignments (list): JSON array of worker-shift assignments.
        violations (dict): JSON object of constraint violations.
        diagnosis_message (str): Infeasibility diagnostic info.
    """
    __tablename__ = "solver_jobs"
    __table_args__ = (
        # Optimize status-based queries (finding PENDING/RUNNING jobs)
        Index('ix_solverjob_status', 'status'),
        # Optimize session + status lookups
        Index('ix_solverjob_session_status', 'session_id', 'status'),
    )

    job_id = Column(String, primary_key=True, index=True)
    session_id = Column(String, index=True, nullable=False)

    # Job lifecycle
    status = Column(String, nullable=False, default="PENDING")
    created_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Error handling
    error_message = Column(Text, nullable=True)

    # Solver results
    result_status = Column(String, nullable=True)  # Optimal, Feasible, Infeasible
    objective_value = Column(Float, nullable=True)
    theoretical_max_score = Column(Float, nullable=True)

    # Result data (JSON blobs)
    assignments = Column(JSON, nullable=True)
    violations = Column(JSON, nullable=True)
    penalty_breakdown = Column(JSON, nullable=True)  # Score explainability

    # Diagnostics
    diagnosis_message = Column(Text, nullable=True)