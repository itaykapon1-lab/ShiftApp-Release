"""baseline — captures current schema

Revision ID: 0001
Revises: None
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op for existing databases — tables already created by create_all().

    For brand-new databases Alembic runs all migrations in order, so
    subsequent migrations will build the schema incrementally.
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # If core tables exist, this DB was created by create_all() — skip.
    if "workers" in existing_tables and "shifts" in existing_tables:
        return

    # Fresh DB: create the baseline schema (matches data/models.py at commit time).
    op.create_table(
        "session_configs",
        sa.Column("session_id", sa.String(), primary_key=True),
        sa.Column("constraints", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_session_configs_session_id", "session_configs", ["session_id"])

    op.create_table(
        "workers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("worker_id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("session_id", "worker_id", name="uq_worker_session_id"),
    )
    op.create_index("ix_worker_session_worker_id", "workers", ["session_id", "worker_id"])
    op.create_index("ix_worker_session_name", "workers", ["session_id", "name"])

    op.create_table(
        "shifts",
        sa.Column("shift_id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("tasks_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_shift_session_name", "shifts", ["session_id", "name"])

    op.create_table(
        "solver_jobs",
        sa.Column("job_id", sa.String(), primary_key=True),
        sa.Column("session_id", sa.String(), nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_status", sa.String(), nullable=True),
        sa.Column("objective_value", sa.Float(), nullable=True),
        sa.Column("theoretical_max_score", sa.Float(), nullable=True),
        sa.Column("assignments", sa.JSON(), nullable=True),
        sa.Column("violations", sa.JSON(), nullable=True),
        sa.Column("penalty_breakdown", sa.JSON(), nullable=True),
        sa.Column("diagnosis_message", sa.Text(), nullable=True),
    )
    op.create_index("ix_solverjob_status", "solver_jobs", ["status"])
    op.create_index("ix_solverjob_session_status", "solver_jobs", ["session_id", "status"])


def downgrade() -> None:
    op.drop_table("solver_jobs")
    op.drop_table("shifts")
    op.drop_table("workers")
    op.drop_table("session_configs")
