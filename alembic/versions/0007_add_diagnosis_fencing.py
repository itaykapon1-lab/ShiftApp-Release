"""Add diagnosis fencing and reaper timestamp columns

Revision ID: 0007
Revises: 0006
Create Date: 2026-03-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.add_column(sa.Column("diagnosis_attempt", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("diagnosis_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        sa.text(
            """
            UPDATE solver_jobs
            SET diagnosis_attempt = 1
            WHERE diagnosis_status IS NOT NULL
              AND diagnosis_attempt IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE solver_jobs
            SET diagnosis_updated_at = COALESCE(completed_at, created_at, CURRENT_TIMESTAMP)
            WHERE diagnosis_status IS NOT NULL
              AND diagnosis_updated_at IS NULL
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.drop_column("diagnosis_updated_at")
        batch_op.drop_column("diagnosis_attempt")
