"""add foreign keys to workers, shifts, solver_jobs

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Child tables that need FK to session_configs.session_id.
_FK_TABLES = ["workers", "shifts", "solver_jobs"]


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1: Backfill orphaned rows — create parent SessionConfig for any
    # session_id that exists in a child table but not in session_configs.
    for table in _FK_TABLES:
        op.execute(
            text(
                f"INSERT INTO session_configs (session_id, constraints, created_at, updated_at) "
                f"SELECT DISTINCT t.session_id, '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
                f"FROM {table} t "
                f"WHERE t.session_id NOT IN (SELECT session_id FROM session_configs)"
            )
        )

    # Step 2: Add FK constraints via batch operations (required for SQLite).
    with op.batch_alter_table("workers") as batch_op:
        batch_op.create_foreign_key(
            "fk_workers_session_id",
            "session_configs",
            ["session_id"],
            ["session_id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("shifts") as batch_op:
        batch_op.create_foreign_key(
            "fk_shifts_session_id",
            "session_configs",
            ["session_id"],
            ["session_id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.create_foreign_key(
            "fk_solver_jobs_session_id",
            "session_configs",
            ["session_id"],
            ["session_id"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.drop_constraint("fk_solver_jobs_session_id", type_="foreignkey")

    with op.batch_alter_table("shifts") as batch_op:
        batch_op.drop_constraint("fk_shifts_session_id", type_="foreignkey")

    with op.batch_alter_table("workers") as batch_op:
        batch_op.drop_constraint("fk_workers_session_id", type_="foreignkey")
