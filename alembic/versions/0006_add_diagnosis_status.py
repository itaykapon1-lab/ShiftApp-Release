"""Add diagnosis_status column to solver_jobs

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.add_column(sa.Column("diagnosis_status", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("solver_jobs") as batch_op:
        batch_op.drop_column("diagnosis_status")
