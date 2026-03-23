"""In-Memory Repository Implementations.

This module provides concrete, in-memory implementations of the domain repositories.
These classes are primarily used for:
1. Stateless execution (e.g., CLI tools loading data from CSVs).
2. Unit testing (mocking the persistence layer).
3. Rapid prototyping before integrating a real database.

They strictly adhere to the IWorkerRepository and IShiftRepository interfaces.
"""

import logging
from typing import List, Dict, Optional

# Interface Imports — Protocol classes defining the CRUD contract
from repositories.interfaces import IWorkerRepository, IShiftRepository

# Domain Imports — pure dataclasses with no I/O or ORM dependencies
from domain.worker_model import Worker
from domain.shift_model import Shift

# Configure module-level logger
logger = logging.getLogger(__name__)


class MemoryWorkerRepository(IWorkerRepository):
    """A volatile, in-memory storage for Worker entities.

    This repository stores workers in a Python dictionary for O(1) access by ID.
    It does not persist data to disk; data is lost when the process terminates.

    Attributes:
        _storage (Dict[str, Worker]): The internal hash map storing workers by ID.
    """

    def __init__(self, initial_data: Optional[List[Worker]] = None):
        """Initializes the repository, optionally pre-loading it with data.

        Args:
            initial_data (Optional[List[Worker]]): A list of workers to load
                immediately upon initialization. Defaults to None.
        """
        # In-memory hash map: worker_id → Worker domain object (O(1) lookup)
        self._storage: Dict[str, Worker] = {}

        # Optionally seed the repository with pre-built worker objects
        if initial_data:
            for worker in initial_data:
                self.add(worker)
            logger.debug("MemoryWorkerRepository initialized with %d workers.", len(initial_data))

    def get_all(self) -> List[Worker]:
        """Retrieves all workers currently in storage.

        Returns:
            List[Worker]: A list of all stored Worker entities.
        """
        return list(self._storage.values())

    def get_by_id(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a specific worker by their unique identifier.

        Args:
            worker_id (str): The unique ID of the worker.

        Returns:
            Optional[Worker]: The Worker entity if found, otherwise None.
        """
        return self._storage.get(worker_id)

    def add(self, worker: Worker) -> None:
        """Adds a new worker to the repository.

        Args:
            worker (Worker): The worker entity to add.

        Raises:
            ValueError: If a worker with the same ID already exists. Use update() to modify.
        """
        # Enforce uniqueness: duplicate IDs are rejected (unlike SQL upsert behaviour).
        # Callers must use update() explicitly to modify existing records.
        if worker.worker_id in self._storage:
            raise ValueError(
                f"Worker '{worker.worker_id}' already exists. Use update() to modify."
            )
        self._storage[worker.worker_id] = worker
        # Logging at debug level to avoid cluttering the console during bulk loads
        logger.debug("Added worker to memory repo: %s", worker.worker_id)

    def update(self, worker: Worker) -> None:
        """Updates an existing worker's data.

        In this in-memory implementation, this is functionally identical to add(),
        but explicit separation clarifies intent in the domain logic.

        Args:
            worker (Worker): The worker entity with updated information.

        Raises:
            KeyError: (Optional strict mode) If the worker does not exist.
                      Currently, it performs an upsert for simplicity.
        """
        if worker.worker_id not in self._storage:
            logger.warning("Attempted to update non-existent worker: %s. Creating new entry.", worker.worker_id)

        self._storage[worker.worker_id] = worker
        logger.debug("Updated worker in memory repo: %s", worker.worker_id)

    def delete(self, worker_id: str) -> None:
        """Removes a worker from the repository.

        Args:
            worker_id (str): The ID of the worker to remove.
        """
        if worker_id in self._storage:
            del self._storage[worker_id]
            logger.debug("Removed worker: %s", worker_id)


class MemoryShiftRepository(IShiftRepository):
    """A volatile, in-memory storage for Shift entities.

    Stores shifts in a Python dictionary for fast lookup and retrieval.

    Attributes:
        _storage (Dict[str, Shift]): The internal hash map storing shifts by ID.
    """

    def __init__(self, initial_data: Optional[List[Shift]] = None, session_id: str = "memory-session"):
        """Initializes the repository with optional initial data.

        Args:
            initial_data (Optional[List[Shift]]): A list of shifts to load
                immediately. Defaults to None.
            session_id (str): Tenant identifier. Defaults to ``"memory-session"``
                for test convenience; callers that need deterministic shift IDs
                (e.g. Excel import) should pass a real session ID.
        """
        # In-memory hash map: shift_id → Shift domain object (O(1) lookup)
        self._storage: Dict[str, Shift] = {}
        self.session_id: str = session_id

        # Optionally seed the repository with pre-built shift objects
        if initial_data:
            for shift in initial_data:
                self.add(shift)
            logger.debug("MemoryShiftRepository initialized with %d shifts.", len(initial_data))

    def get_all(self) -> List[Shift]:
        """Retrieves all shifts currently in storage.

        Returns:
            List[Shift]: A list of all stored Shift entities.
        """
        return list(self._storage.values())

    def get_by_id(self, shift_id: str) -> Optional[Shift]:
        """Retrieves a specific shift by its unique identifier.

        Args:
            shift_id (str): The unique ID of the shift.

        Returns:
            Optional[Shift]: The Shift entity if found, otherwise None.
        """
        return self._storage.get(shift_id)

    def add(self, shift: Shift) -> None:
        """Adds a new shift to the repository.

        Args:
            shift (Shift): The shift entity to store.

        Raises:
            ValueError: If a shift with the same ID already exists. Use update() to modify.
        """
        # Enforce uniqueness: duplicate IDs are rejected (unlike SQL upsert behaviour)
        if shift.shift_id in self._storage:
            raise ValueError(
                f"Shift '{shift.shift_id}' already exists. Use update() to modify."
            )
        self._storage[shift.shift_id] = shift
        logger.debug("Added shift to memory repo: %s", shift.shift_id)

    def update(self, shift: Shift) -> None:
        """Updates an existing shift.

        Args:
            shift (Shift): The updated shift entity.
        """
        if shift.shift_id not in self._storage:
            logger.warning("Attempted to update non-existent shift: %s. Creating new entry.", shift.shift_id)

        self._storage[shift.shift_id] = shift

    def delete(self, shift_id: str) -> None:
        """Removes a shift from the repository.

        Args:
            shift_id (str): The ID of the shift to remove.
        """
        if shift_id in self._storage:
            del self._storage[shift_id]