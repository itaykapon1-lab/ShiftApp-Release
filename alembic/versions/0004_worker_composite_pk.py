"""worker composite PK — drop surrogate id, PK on (session_id, worker_id)

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-20

Migrates the workers table from:
    PK: id (Integer, autoincrement surrogate)
    UNIQUE(session_id, worker_id)  -- name: uq_worker_session_id
    INDEX ix_worker_session_worker_id(session_id, worker_id)
To:
    PK: (session_id, worker_id)  -- composite, enforces uniqueness + creates index
    -- unique constraint dropped (redundant with composite PK)
    -- ix_worker_session_worker_id dropped (redundant with composite PK)

SQLite cannot ALTER PRIMARY KEY, so we recreate the table manually.
This is the standard SQLite migration pattern (the 12-step ALTER TABLE
procedure from https://www.sqlite.org/lang_altertable.html).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Step 1: Create the new table with composite PK ---
    op.execute(text("""
        CREATE TABLE workers_new (
            session_id  VARCHAR NOT NULL
                        REFERENCES session_configs(session_id) ON DELETE CASCADE,
            worker_id   VARCHAR NOT NULL,
            name        VARCHAR NOT NULL,
            attributes  JSON,
            created_at  DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
            updated_at  DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
            PRIMARY KEY (session_id, worker_id)
        )
    """))

    # --- Step 2: Copy data (id is dropped, all other columns transfer) ---
    op.execute(text("""
        INSERT INTO workers_new (session_id, worker_id, name, attributes, created_at, updated_at)
        SELECT session_id, worker_id, name, attributes, created_at, updated_at
        FROM workers
    """))

    # --- Step 3: Drop old table and its indexes ---
    op.drop_index("ix_worker_session_name", table_name="workers")
    op.drop_index("ix_worker_session_worker_id", table_name="workers")
    op.drop_table("workers")

    # --- Step 4: Rename new table ---
    op.rename_table("workers_new", "workers")

    # --- Step 5: Recreate the session+name index (the only one we keep) ---
    op.create_index("ix_worker_session_name", "workers", ["session_id", "name"])


def downgrade() -> None:
    # Restore: surrogate id PK + unique constraint + indexes.
    op.execute(text("""
        CREATE TABLE workers_old (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  VARCHAR NOT NULL
                        REFERENCES session_configs(session_id) ON DELETE CASCADE,
            worker_id   VARCHAR NOT NULL,
            name        VARCHAR NOT NULL,
            attributes  JSON,
            created_at  DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
            updated_at  DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
            UNIQUE (session_id, worker_id)
        )
    """))

    op.execute(text("""
        INSERT INTO workers_old (session_id, worker_id, name, attributes, created_at, updated_at)
        SELECT session_id, worker_id, name, attributes, created_at, updated_at
        FROM workers
    """))

    op.drop_index("ix_worker_session_name", table_name="workers")
    op.drop_table("workers")

    op.rename_table("workers_old", "workers")

    # Restore pre-0004 indexes.
    op.create_index("ix_worker_session_name", "workers", ["session_id", "name"])
    op.create_index("ix_worker_session_worker_id", "workers", ["session_id", "worker_id"])
