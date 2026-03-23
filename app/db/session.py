"""Database Session Management.

This module provides the SQLAlchemy engine and session factory for the application.
It supports HYBRID DATABASE MODE:
- SQLite: For local development (default, no config needed)
- PostgreSQL: For production (set DATABASE_URL environment variable)

The module automatically detects the database type and configures appropriate
connection arguments and pooling settings.
"""

import logging
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool, QueuePool

from app.core.config import settings
from data.base import Base

logger = logging.getLogger(__name__)


def create_db_engine() -> Engine:
    """
    Creates a SQLAlchemy engine with database-specific configuration.

    For SQLite:
    - Uses check_same_thread=False for multi-threaded access
    - Uses StaticPool for in-memory databases (testing)

    For PostgreSQL:
    - Uses connection pooling (QueuePool)
    - Configures pool_size, max_overflow, and pool_pre_ping

    Returns:
        Engine: Configured SQLAlchemy engine
    """
    connect_args = {}
    engine_kwargs = {
        "echo": False,  # Set to True for SQL query logging
    }

    if settings.is_sqlite:
        # SQLite-specific configuration
        connect_args["check_same_thread"] = False
        engine_kwargs["connect_args"] = connect_args

        # For in-memory SQLite (used in testing), use StaticPool
        if ":memory:" in settings.database_url:
            engine_kwargs["poolclass"] = StaticPool
            logger.info("Using SQLite in-memory database with StaticPool")
        else:
            logger.info(f"Using SQLite file database: {settings.database_url}")

    elif settings.is_postgres:
        # PostgreSQL-specific configuration with connection pooling
        engine_kwargs["pool_size"] = settings.db_pool_size
        engine_kwargs["max_overflow"] = settings.db_max_overflow
        engine_kwargs["pool_pre_ping"] = settings.db_pool_pre_ping
        engine_kwargs["poolclass"] = QueuePool
        engine_kwargs["pool_timeout"] = settings.db_pool_timeout
        engine_kwargs["pool_recycle"] = settings.db_pool_recycle
        # Protect Gunicorn workers against DB stalls:
        # - connect_timeout: abort if TCP handshake takes >10s
        # - statement_timeout: kill any query running longer than 30s
        engine_kwargs["connect_args"] = {
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",
        }
        logger.info(f"Using PostgreSQL with pool_size={settings.db_pool_size}, max_overflow={settings.db_max_overflow}")

    else:
        # Unknown database type - use defaults
        logger.warning(f"Unknown database type in URL: {settings.database_url}")

    return create_engine(settings.database_url, **engine_kwargs)


# Create the database engine
engine: Engine = create_db_engine()


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable FK enforcement on every SQLite connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


if settings.is_sqlite:
    event.listen(engine, "connect", _set_sqlite_pragma)

# Session factory - creates new Session objects
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


def get_db() -> Session:
    """
    Dependency function to get a database session.

    This is used as a FastAPI dependency to provide database sessions
    to route handlers. The session is automatically closed after the request.

    Yields:
        Session: A SQLAlchemy database session
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
