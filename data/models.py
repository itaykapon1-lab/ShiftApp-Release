"""SQLAlchemy ORM Models.

This module defines the database schema structure using SQLAlchemy's ORM.
It implements a 'Hybrid' architecture where relational columns are used for
indexing and lookups, while JSON columns are used for complex data structures.

The models inherit from `data.base.Base` to register with the engine.
"""

from datetime import datetime, timezone
from sqlalchemy import Column, String, JSON, DateTime, Float, Integer, Text, ForeignKey, Index, text
from sqlalchemy.orm import relationship
# All ORM models share this declarative Base; defined in data/base.py to break
# the circular import between models.py and database.py.
from data.base import Base


def utc_now():
    """Returns current UTC timestamp (timezone-aware)."""
    # Used as a SQLAlchemy column default/onupdate — called by the ORM at
    # INSERT/UPDATE time, NOT by application code.
    return datetime.now(timezone.utc)

class WorkerModel(Base):
    """Represents a worker (employee) in the system.

    This model serves as a persistent store for the `Worker` domain object.
    It uses a JSON column (`attributes`) to store flexible properties like
    skills, availability, and preferences, avoiding rigid schema changes.

    Identity is scoped to the session via composite PK ``(session_id, worker_id)``.

    Attributes:
        session_id (str): FK to session_configs. Part of composite PK.
        worker_id (str): Business identifier (e.g. from Excel "Worker ID"). Part of composite PK.
        name (str): The worker's display name.
        attributes (dict): JSON blob containing skills, availability, preferences.
    """
    __tablename__ = "workers"
    __table_args__ = (
        # Composite index for UI display/search that filters by session + name
        Index('ix_worker_session_name', 'session_id', 'name'),
    )

    # Composite PK — (session_id, worker_id) is the logical identity
    session_id = Column(
        String,
        ForeignKey('session_configs.session_id', ondelete='CASCADE'),
        primary_key=True, nullable=False,
    )
    # Business identifier from Excel import (e.g., "W001", "EMP-42")
    worker_id = Column(String, primary_key=True, nullable=False)
    name = Column(String, nullable=False)

    # Flexible JSON blob storing domain-specific properties (skills, availability,
    # preferences) — avoids rigid ALTER TABLE migrations when fields change
    attributes = Column(JSON, nullable=True)

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=text("(CURRENT_TIMESTAMP)"), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=text("(CURRENT_TIMESTAMP)"), default=utc_now,
                        onupdate=utc_now)

    # ORM relationship — navigates to the parent SessionConfigModel
    session_config = relationship("SessionConfigModel", back_populates="workers")


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
        # Composite index for session-scoped shift lookups (name is no longer unique)
        Index('ix_shift_session_name', 'session_id', 'name'),
    )

    # Natural PK — shift_id is a UUID generated at domain layer creation time
    shift_id = Column(String, primary_key=True, index=True)
    # Multi-tenancy key — FK to session_configs for CASCADE delete support
    session_id = Column(
        String,
        ForeignKey('session_configs.session_id', ondelete='CASCADE'),
        index=True, nullable=False,
    )
    name = Column(String, nullable=False)

    # Native DateTime columns (not strings) so the DB can sort/filter by time
    # range. IMPORTANT: These are stored in Canonical Epoch Week (Jan 1-7, 2024),
    # NOT real calendar dates — see repositories/sql_repo.py _to_model().
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)

    # JSON blob holding the full Task → Option → Requirement hierarchy.
    # Structured as a list of task dicts, each containing nested options and
    # skill requirements — deserialized by sql_repo.py _to_domain().
    tasks_data = Column(JSON, nullable=True)

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=text("(CURRENT_TIMESTAMP)"), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=text("(CURRENT_TIMESTAMP)"), default=utc_now,
                        onupdate=utc_now)

    # ORM relationship — navigates to the parent SessionConfigModel
    session_config = relationship("SessionConfigModel", back_populates="shifts")


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

    # One-to-one with session: session_id IS the PK (no surrogate needed)
    session_id = Column(String, primary_key=True, index=True)
    # JSON array of constraint configuration dicts — the UI reads/writes this
    # directly. Default is an empty list (new sessions start with no overrides).
    constraints = Column(JSON, nullable=True, default=list)

    # Audit timestamps
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=text("(CURRENT_TIMESTAMP)"), default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=text("(CURRENT_TIMESTAMP)"), default=utc_now,
                        onupdate=utc_now)

    # ORM relationships — parent side, navigates to child collections.
    # cascade="all, delete-orphan" mirrors the DB-level ON DELETE CASCADE so
    # the ORM session stays consistent when deleting a SessionConfigModel.
    # passive_deletes=True tells SQLAlchemy to let the DB handle CASCADE
    # instead of issuing individual DELETEs for each child row.
    workers = relationship(
        "WorkerModel", back_populates="session_config",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    shifts = relationship(
        "ShiftModel", back_populates="session_config",
        cascade="all, delete-orphan", passive_deletes=True,
    )
    solver_jobs = relationship(
        "SolverJobModel", back_populates="session_config",
        cascade="all, delete-orphan", passive_deletes=True,
    )


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
        # Index for polling active jobs: solver_service queries status=PENDING/RUNNING
        Index('ix_solverjob_status', 'status'),
        # Composite index for "does this session already have a running job?" check
        Index('ix_solverjob_session_status', 'session_id', 'status'),
    )

    # UUID generated when a solve request is initiated
    job_id = Column(String, primary_key=True, index=True)
    # Links back to the user session — FK for CASCADE delete support
    session_id = Column(
        String,
        ForeignKey('session_configs.session_id', ondelete='CASCADE'),
        index=True, nullable=False,
    )

    # Job lifecycle — state machine: PENDING -> RUNNING -> COMPLETED | FAILED
    status = Column(String, nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), nullable=False,
                        server_default=text("(CURRENT_TIMESTAMP)"), default=utc_now)  # When the job was enqueued
    started_at = Column(DateTime(timezone=True), nullable=True)    # When the solver process began
    completed_at = Column(DateTime(timezone=True), nullable=True)  # When the solver finished (success or failure)

    # Error handling — populated only when status=FAILED; contains the exception message
    error_message = Column(Text, nullable=True)

    # Solver results — populated only when status=COMPLETED
    result_status = Column(String, nullable=True)  # "Optimal", "Feasible", or "Infeasible"
    objective_value = Column(Float, nullable=True)  # Actual optimization score achieved
    theoretical_max_score = Column(Float, nullable=True)  # Best possible score (upper bound)

    # Result data (JSON blobs) — populated only when status=COMPLETED
    assignments = Column(JSON, nullable=True)   # List of {worker_id, shift_id, role} dicts
    violations = Column(JSON, nullable=True)    # Dict of constraint violations found
    penalty_breakdown = Column(JSON, nullable=True)  # Per-constraint penalty scores for explainability

    # Diagnostics — populated when result_status=Infeasible to explain why
    diagnosis_message = Column(Text, nullable=True)

    # Diagnostic lifecycle state machine: None → PENDING → RUNNING → COMPLETED | FAILED
    # Used to track async diagnostic execution independently of the solve job lifecycle.
    diagnosis_status = Column(String, nullable=True)
    diagnosis_attempt = Column(Integer, nullable=True)
    diagnosis_updated_at = Column(DateTime(timezone=True), nullable=True)

    # ORM relationship — navigates to the parent SessionConfigModel
    session_config = relationship("SessionConfigModel", back_populates="solver_jobs")
