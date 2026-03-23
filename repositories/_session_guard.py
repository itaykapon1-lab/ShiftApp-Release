"""Session config guard — ensures parent row exists before FK-dependent inserts."""

from sqlalchemy.orm import Session

from data.models import SessionConfigModel


def ensure_session_config_exists(db: Session, session_id: str) -> None:
    """Creates a minimal SessionConfigModel if one doesn't exist for session_id.

    This is required by the FK constraints on workers, shifts, and solver_jobs:
    those tables reference session_configs.session_id as a foreign key.

    Idempotent — safe to call multiple times for the same session_id.

    Args:
        db: Active SQLAlchemy session.
        session_id: The session identifier to ensure exists.
    """
    existing = (
        db.query(SessionConfigModel)
        .filter_by(session_id=session_id)
        .first()
    )
    if not existing:
        db.add(SessionConfigModel(session_id=session_id, constraints=[]))
        db.flush()
