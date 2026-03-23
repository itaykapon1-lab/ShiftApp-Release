"""Base Repository with Session-Based Multi-Tenancy.

This module provides a BaseRepository class that automatically applies
session_id filtering to all database operations, ensuring complete data
isolation between different sessions (multi-tenancy).
"""

from typing import Any, Dict, Generic, TypeVar, Type, Optional, List, Tuple, Union
from sqlalchemy.orm import Session

# Base is the SQLAlchemy declarative base class shared by all ORM models
from data.models import Base

# Type variable for the SQLAlchemy model — bound to Base ensures only
# ORM model classes (WorkerModel, ShiftModel, etc.) can be used as generics.
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
        self.session = session   # Active SQLAlchemy session — shared across all repos in one request
        self.model = model       # The ORM model class (e.g., WorkerModel) for this repo
        self.session_id = session_id  # Tenant identifier — every query is scoped to this value
        # Cache the primary key columns via SQLAlchemy table introspection.
        # For composite PKs (e.g., WorkerModel), this list has >1 element.
        # get_by_id/delete use only the first column (valid for single-PK models);
        # composite-PK models override these methods in their own repositories.
        self._pk_columns = list(model.__table__.primary_key.columns)
        self._pk_column = self._pk_columns[0]

    def _build_pk_criteria(
        self,
        entity_id: Union[Any, Dict[str, Any], Tuple[Any, ...]],
    ) -> Dict[str, Any]:
        """Normalize a primary-key lookup into an exact column/value mapping."""
        pk_column_names = [column.name for column in self._pk_columns]

        if isinstance(entity_id, dict):
            missing = [name for name in pk_column_names if name not in entity_id]
            if missing:
                raise ValueError(
                    f"{self.model.__name__} requires primary-key fields "
                    f"{pk_column_names}; missing {missing}"
                )
            return {name: entity_id[name] for name in pk_column_names}

        if isinstance(entity_id, tuple):
            if len(entity_id) != len(self._pk_columns):
                raise ValueError(
                    f"{self.model.__name__} expects {len(self._pk_columns)} "
                    f"primary-key values ({pk_column_names}), got {len(entity_id)}"
                )
            return {
                column.name: value
                for column, value in zip(self._pk_columns, entity_id)
            }

        if len(self._pk_columns) > 1:
            raise ValueError(
                f"{self.model.__name__} has composite primary key {pk_column_names}; "
                "pass a dict or tuple with all primary-key values"
            )

        return {self._pk_column.name: entity_id}

    def _get_base_query(self):
        """Returns a query filtered by session_id."""
        # Multi-tenancy enforcement: every query starts with a session_id filter
        # to prevent cross-session data leakage between different users.
        return self.session.query(self.model).filter(
            self.model.session_id == self.session_id
        )

    def get_all(self) -> List[ModelType]:
        """Get all entities for the current session."""
        return self._get_base_query().all()

    def get_by_id(
        self,
        entity_id: Union[str, Dict[str, str], Tuple[str, ...]],
    ) -> Optional[ModelType]:
        """Get an entity by primary key, scoped to current session.

        Args:
            entity_id: For single-column PKs, a plain string.
                For composite PKs, either a dict mapping column names to values
                (e.g. ``{"session_id": "s1", "worker_id": "w1"}``) or a tuple
                whose positional order matches ``self._pk_columns``.

        Returns:
            The matching entity, or None if not found.
        """
        query = self._get_base_query()
        criteria = self._build_pk_criteria(entity_id)
        for column in self._pk_columns:
            query = query.filter(column == criteria[column.name])
        return query.first()

    def add(self, entity: ModelType) -> None:
        """Add a new entity, automatically setting session_id.

        Uses session.merge() for upsert semantics — consistent with update().
        """
        if hasattr(entity, 'session_id'):
            entity.session_id = self.session_id  # Stamp the tenant ID before writing
        # merge() implements upsert: if a row with the same PK exists, update it;
        # otherwise insert a new row.  This is intentionally identical to update()
        # because callers should not need to know whether a record pre-exists.
        self.session.merge(entity)

    def update(self, entity: ModelType) -> None:
        """Update an entity, ensuring it belongs to current session."""
        if hasattr(entity, 'session_id'):
            entity.session_id = self.session_id
        self.session.merge(entity)

    def delete(
        self,
        entity_id: Union[str, Dict[str, str], Tuple[str, ...]],
    ) -> None:
        """Delete an entity by primary key, scoped to current session.

        Args:
            entity_id: For single-column PKs, a plain string.
                For composite PKs, either a dict mapping column names to values
                or a tuple whose positional order matches ``self._pk_columns``.
        """
        query = self._get_base_query()
        criteria = self._build_pk_criteria(entity_id)
        for column in self._pk_columns:
            query = query.filter(column == criteria[column.name])
        # synchronize_session=False: skip ORM identity-map bookkeeping for this
        # bulk DELETE — faster than "fetch" mode and safe because we call
        # expire_all() immediately after to invalidate any stale cached objects.
        query.delete(synchronize_session=False)
        # Expire all ORM-cached instances so subsequent queries re-fetch from DB,
        # preventing stale reads of the just-deleted entity.
        self.session.expire_all()
