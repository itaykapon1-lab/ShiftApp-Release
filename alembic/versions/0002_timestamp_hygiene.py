"""timestamp hygiene — DateTime(timezone=True), NOT NULL, server_default

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables that have (created_at, updated_at) audit columns.
_AUDIT_TABLES = ["workers", "shifts", "session_configs"]


def upgrade() -> None:
    # Backfill NULLs before adding NOT NULL constraint.
    for table in _AUDIT_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
            )
        )
        op.execute(
            sa.text(
                f"UPDATE {table} SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
            )
        )

    # Workers
    with op.batch_alter_table("workers") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        )

    # Shifts
    with op.batch_alter_table("shifts") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        )

    # Session configs
    with op.batch_alter_table("session_configs") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        )
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        )

    # Solver jobs: only created_at/started_at/completed_at → timezone-aware.
    # These remain nullable (lifecycle columns set at specific state transitions).
    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "completed_at",
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=True,
        )


def downgrade() -> None:
    for table in _AUDIT_TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column(
                "created_at",
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(),
                nullable=True,
                server_default=None,
            )
            batch_op.alter_column(
                "updated_at",
                existing_type=sa.DateTime(timezone=True),
                type_=sa.DateTime(),
                nullable=True,
                server_default=None,
            )

    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "started_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "completed_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=True,
        )
