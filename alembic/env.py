"""Alembic migration environment.

Configures the migration engine with:
- SQLite batch operations (render_as_batch=True) for ALTER TABLE support.
- SQLite PRAGMA foreign_keys=ON enforcement.
- Target metadata from data.base.Base.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool, text

from app.core.config import settings
from data.base import Base

# Ensure all models are registered on Base.metadata before autogenerate.
import data.models  # noqa: F401

config = context.config

# Only configure logging from alembic.ini when running standalone (CLI).
# Skip fileConfig when:
#   - A pre-supplied connection is provided (test fixtures), OR
#   - The caller sets configure_logger=False (embedded in FastAPI lifespan).
# Reason: fileConfig() calls logging.config.fileConfig() with
# disable_existing_loggers=True (Python default), which destroys uvicorn's
# loggers and silences all startup messages — making the server appear hung.
if (
    config.config_file_name is not None
    and not config.attributes.get("connection")
    and config.attributes.get("configure_logger", True)
):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _set_sqlite_pragma(dbapi_conn, connection_record):
    """Enable FK enforcement on every SQLite connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emits SQL to stdout."""
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode — connects to the database.

    Supports two modes:
    1. Normal: creates its own engine from settings.database_url.
    2. Pre-supplied connection: if config.attributes["connection"] is set
       (e.g. by test fixtures), uses that connection directly.  This allows
       running migrations on in-memory SQLite databases that can't be
       addressed by URL.
    """
    # Check for a pre-supplied connection (used by test fixtures).
    connectable = config.attributes.get("connection", None)

    if connectable is not None:
        # Connection already provided — run migrations directly on it.
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        # Normal mode — create engine from settings.
        configuration = config.get_section(config.config_ini_section, {})
        configuration["sqlalchemy.url"] = settings.database_url

        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )

        # Enable SQLite FK enforcement.
        if "sqlite" in settings.database_url:
            event.listen(connectable, "connect", _set_sqlite_pragma)

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )

            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
