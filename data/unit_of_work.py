"""Unit of Work Pattern Implementation.

This module defines the UnitOfWork class, which acts as a transaction boundary
for business operations. It ensures that multiple repository operations
(e.g., creating a worker and assigning them a shift) happen atomically.

Pattern Benefits:
1.  **Atomicity**: All changes are committed at once, or rolled back on error.
2.  **Consistency**: Repositories share the same database session.
3.  **Abstraction**: Business logic doesn't need to know about 'commits' or 'sessions'.
"""

from typing import Optional
from types import TracebackType

from sqlalchemy.orm import Session

# Infrastructure Imports
from data.database import DatabaseService

# Repository Imports
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository


class UnitOfWork:
    """Manages the transactional lifecycle of business operations.

    Implements the Context Manager protocol (`with` statement).

    Usage Example:
        uow = UnitOfWork(db_service, session_id="user-uuid")
        with uow:
            uow.workers.add(worker)
            uow.shifts.add(shift)
        # Automatic commit happens here if no exception was raised.

    Attributes:
        workers (SQLWorkerRepository): Repository for worker operations.
        shifts (SQLShiftRepository): Repository for shift operations.
    """

    def __init__(self, db_service: DatabaseService, session_id: str):
        """Initializes the UnitOfWork with a database service factory.

        Args:
            db_service (DatabaseService): The source for creating new sessions.
            session_id (str): The session ID for multi-tenancy isolation.
        """
        self._db_service = db_service
        self._session_id = session_id
        self._session: Optional[Session] = None

        # Repository instances (Initialized in __enter__)
        self.workers: Optional[SQLWorkerRepository] = None
        self.shifts: Optional[SQLShiftRepository] = None

    def __enter__(self) -> 'UnitOfWork':
        """Starts a new transaction scope.

        1. Opens a new Database Session.
        2. Initializes repositories with this shared session and session_id.

        Returns:
            UnitOfWork: The active UoW instance.
        """
        # Open a fresh DB session — this is the transaction boundary
        self._session = self._db_service.get_session()

        # All repositories share this SAME session so that a single commit/rollback
        # at __exit__ applies atomically to all operations across workers and shifts
        self.workers = SQLWorkerRepository(self._session, self._session_id)
        self.shifts = SQLShiftRepository(self._session, self._session_id)

        return self

    def __exit__(
            self,
            exc_type: Optional[type],
            exc_value: Optional[BaseException],
            traceback: Optional[TracebackType]
    ) -> None:
        """Ends the transaction scope.

        Handles the Commit/Rollback logic based on whether an exception occurred.
        Always closes the session to prevent connection leaks.
        """
        try:
            if exc_type:
                # An exception occurred inside the 'with' block — discard
                # all pending changes to leave the DB in a consistent state
                self._session.rollback()
            else:
                # Happy path: persist all accumulated changes from every
                # repository operation performed inside the 'with' block
                self._session.commit()
        except Exception as e:
            # If commit itself fails (e.g., constraint violation at DB level),
            # roll back to prevent a half-committed transaction
            self._session.rollback()
            raise e
        finally:
            # Always release the connection back to the pool
            self._session.close()