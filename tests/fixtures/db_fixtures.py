"""Database fixture helpers for isolated tests.

Uses Alembic migrations (not Base.metadata.create_all()) so the test schema
is created through the same migration path as production databases.
"""

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool

from data.base import Base
# Import all models so Base.metadata registers every table (needed by Alembic).
import data.models  # noqa: F401


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable FK enforcement on every SQLite connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _run_alembic_migrations(engine) -> None:
    """Apply all Alembic migrations on the given engine.

    Passes the engine's connection directly to alembic/env.py via
    config.attributes["connection"], bypassing URL-based engine creation.
    This allows migrations to run on in-memory SQLite databases.
    """
    alembic_cfg = AlembicConfig("alembic.ini")
    with engine.begin() as connection:
        alembic_cfg.attributes["connection"] = connection
        command.upgrade(alembic_cfg, "head")


def create_isolated_engine(thread_safe: bool = True):
    """Return an in-memory SQLite engine with FK enforcement and Alembic schema.

    Args:
        thread_safe: If True (default), uses StaticPool with
            check_same_thread=False for TestClient compatibility.
            If False, creates a plain in-memory engine (faster for
            single-threaded test files).
    """
    kwargs = {"echo": False}
    if thread_safe:
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    engine = create_engine("sqlite://", **kwargs)
    event.listen(engine, "connect", _set_sqlite_pragma)
    _run_alembic_migrations(engine)
    return engine


def destroy_isolated_engine(engine) -> None:
    """Drop all tables and dispose engine."""
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
