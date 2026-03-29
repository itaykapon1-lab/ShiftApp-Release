"""Session config guard — ensures parent row exists before FK-dependent inserts.

Uses an atomic INSERT ... ON CONFLICT DO NOTHING to safely create the
SessionConfigModel row in a single DB round-trip.  No Python-level cache,
no SELECT-then-INSERT race window, and no multi-worker drift.
"""

from sqlalchemy.orm import Session

from data.models import SessionConfigModel


def _get_dialect_insert(db: Session):
    """Return the dialect-specific ``insert`` function with ON CONFLICT support.

    SQLAlchemy's ``on_conflict_do_nothing()`` lives on dialect-specific insert
    constructs, not the generic ``sqlalchemy.insert()``.  This helper picks the
    right one at runtime so the same code works on both SQLite (dev/test) and
    PostgreSQL (production).

    Args:
        db: Active SQLAlchemy session (used to inspect the bound engine dialect).

    Returns:
        The dialect-specific ``insert`` callable.
    """
    dialect_name = db.bind.dialect.name
    if dialect_name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


def ensure_session_config_exists(db: Session, session_id: str) -> None:
    """Atomically ensures a SessionConfigModel row exists for *session_id*.

    Emits ``INSERT INTO session_configs ... ON CONFLICT DO NOTHING``.  If the
    row already exists the statement is a no-op; if it doesn't, the row is
    created with an empty constraints list.

    This is safe under:
    - Transaction rollbacks (no stale in-memory state to drift)
    - Multi-worker deployments (no process-local cache to invalidate)
    - Concurrent requests for the same session_id (DB enforces uniqueness)

    Args:
        db: Active SQLAlchemy session.
        session_id: The session identifier to ensure exists.
    """
    insert = _get_dialect_insert(db)
    stmt = (
        insert(SessionConfigModel.__table__)
        .values(session_id=session_id, constraints=[])
        .on_conflict_do_nothing(index_elements=["session_id"])
    )
    db.execute(stmt)
