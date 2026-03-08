"""Base Repository with Session-Based Multi-Tenancy.

This module provides a BaseRepository class that automatically applies
session_id filtering to all database operations, ensuring complete data
isolation between different sessions (multi-tenancy).
"""

from typing import Generic, TypeVar, Type, Optional, List
from sqlalchemy.orm import Session

from data.models import Base

# Type variable for the SQLAlchemy model
ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Base repository class with automatic session_id filtering.

    This class ensures that all database operations are automatically
    scoped to the current session_id, preventing cross-session data access.

    All query operations automatically include:
        .filter(Model.session_id == current_session_id)

    All write operations automatically set:
        model.session_id = current_session_id
    """

    def __init__(self, session: Session, model: Type[ModelType], session_id: str):
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy database session
            model: SQLAlchemy model class
            session_id: Current session ID for data isolation
        """
        self.session = session
        self.model = model
        self.session_id = session_id
        # Cache the primary key column to avoid repeated introspection
        self._pk_column = list(model.__table__.primary_key.columns)[0]

    def _get_base_query(self):
        """Returns a query filtered by session_id."""
        return self.session.query(self.model).filter(
            self.model.session_id == self.session_id
        )

    def get_all(self) -> List[ModelType]:
        """Get all entities for the current session."""
        return self._get_base_query().all()

    def get_by_id(self, entity_id: str) -> Optional[ModelType]:
        """Get an entity by ID, scoped to current session."""
        return self._get_base_query().filter(
            self._pk_column == entity_id
        ).first()

    def add(self, entity: ModelType) -> None:
        """Add a new entity, automatically setting session_id.

        Uses session.merge() for upsert semantics — consistent with update().
        """
        if hasattr(entity, 'session_id'):
            entity.session_id = self.session_id
        self.session.merge(entity)

    def update(self, entity: ModelType) -> None:
        """Update an entity, ensuring it belongs to current session."""
        if hasattr(entity, 'session_id'):
            entity.session_id = self.session_id
        self.session.merge(entity)

    def delete(self, entity_id: str) -> None:
        """Delete an entity, scoped to current session."""
        self._get_base_query().filter(
            self._pk_column == entity_id
        ).delete(synchronize_session=False)
        self.session.expire_all()
