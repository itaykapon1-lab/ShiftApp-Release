"""Database fixture helpers for isolated tests."""

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from data.base import Base
# Import all models so Base.metadata.create_all() registers every table.
import data.models  # noqa: F401


def create_isolated_engine():
    """Return an in-memory SQLite engine shared across threads for TestClient."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    return engine


def destroy_isolated_engine(engine) -> None:
    """Drop all tables and dispose engine."""
    Base.metadata.drop_all(bind=engine)
    engine.dispose()

