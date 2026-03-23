"""Database Connection and Session Management.

This module provides backward-compatible access to database services.
The actual engine and session factory are now defined in app/db/session.py.

For new code, prefer importing directly from app.db.session:
    from app.db.session import engine, SessionLocal, get_db, Base

This module is kept for backward compatibility with existing code that
imports DatabaseService or Base from here.
"""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy.orm import Session

# Re-export Base from data.base for backward compatibility
from data.base import Base

# Import engine and SessionLocal from the canonical location
from app.db.session import engine, SessionLocal


class DatabaseService:
    """Manages the database engine and session creation lifecycle.

    NOTE: This class is deprecated for new code. Use app.db.session instead.
    Kept for backward compatibility with existing code.

    Attributes:
        _engine (Engine): The SQLAlchemy engine instance managing the dialect
            and connection pool.
        _session_factory (sessionmaker): A factory for creating new Session objects.
    """

    def __init__(self, connection_string: str = None):
        """Initializes the database service.

        Args:
            connection_string (str): Ignored - uses app.db.session.engine.
                Parameter kept for backward compatibility.
        """
        # Reuse the singleton engine and session factory from app.db.session
        # rather than creating new ones — ensures consistent connection pooling
        self._engine = engine
        self._session_factory = SessionLocal

    def get_session(self) -> Session:
        """Creates and returns a raw new database session.

        Warning:
            The caller is responsible for closing this session!
            Prefer using `provide_session()` context manager instead.

        Returns:
            Session: A new SQLAlchemy session.
        """
        return self._session_factory()

    @contextmanager
    def provide_session(self) -> Generator[Session, None, None]:
        """Context manager for safe session handling.

        Ensures that the session is properly closed even if exceptions occur.
        Also handles automatic rollback on error.

        Yields:
            Session: An active database session.
        """
        session: Session = self._session_factory()
        try:
            yield session
            # If the caller's code completes without exception, persist all changes
            session.commit()
        except Exception:
            # On ANY exception, undo all uncommitted changes to leave DB clean
            session.rollback()
            raise
        finally:
            # Always return the connection to the pool, even after rollback
            session.close()
