"""
Repository Interfaces Module.

This module defines the abstract contracts (Protocols) for data persistence.
By relying on these interfaces instead of concrete implementations (like CSV or SQL),
the core business logic remains decoupled from the storage mechanism.

Key Concepts:
- Protocol: Python's structural typing (Duck Typing). Any class implementing
  these methods is automatically considered a valid repository.
- CRUD: The interfaces mandate full Create, Read, Update, Delete capabilities.
"""

from typing import List, Optional, Protocol, Dict, Set
from domain.worker_model import Worker
from domain.shift_model import Shift
from domain.time_utils import TimeWindow


class IWorkerRepository(Protocol):
    """Interface for Worker data access operations.

    Defines the contract for managing worker entities, regardless of whether
    they are stored in a CSV file, a database, or memory.
    """

    def get_all(self) -> List[Worker]:
        """Retrieves all registered workers from the storage.

        Returns:
            List[Worker]: A list of all Worker objects. Returns an empty list
            if no workers are found.
        """
        ...

    def get_by_id(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a single worker by their unique identifier.

        Args:
            worker_id (str): The unique ID of the worker to find.

        Returns:
            Optional[Worker]: The Worker object if found, otherwise None.
        """
        ...

    def add(self, worker: Worker) -> None:
        """Persists a new worker to the storage.

        Args:
            worker (Worker): The worker entity to save.

        Raises:
            ValueError: If a worker with the same ID already exists (integrity error).
            IOError: If the underlying storage fails to write.
        """
        ...

    def update(self, worker: Worker) -> None:
        """Updates an existing worker's details.

        This replaces the existing record for the worker's ID with the new object.

        Args:
            worker (Worker): The updated worker entity.

        Raises:
            ValueError: If the worker ID does not exist in the system.
            IOError: If the underlying storage fails to write.
        """
        ...

    def delete(self, worker_id: str) -> None:
        """Removes a worker from the storage permanently.

        Args:
            worker_id (str): The ID of the worker to remove.

        Raises:
            ValueError: If the worker ID does not exist.
            IOError: If the underlying storage fails to perform the deletion.
        """
        ...


class IShiftRepository(Protocol):
    """Interface for Shift data access operations.

    Defines the contract for managing shift definitions and their requirements.
    """

    def get_all(self) -> List[Shift]:
        """Retrieves all defined shifts from the storage.

        Returns:
            List[Shift]: A list of all Shift objects.
        """
        ...

    def get_by_id(self, shift_id: str) -> Optional[Shift]:
        """Retrieves a single shift by its unique identifier.

        Args:
            shift_id (str): The unique ID of the shift to find.

        Returns:
            Optional[Shift]: The Shift object if found, otherwise None.
        """
        ...

    def add(self, shift: Shift) -> None:
        """Persists a new shift definition to the storage.

        Args:
            shift (Shift): The shift entity to save.

        Raises:
            ValueError: If a shift with the same ID already exists.
        """
        ...

    def update(self, shift: Shift) -> None:
        """Updates an existing shift's details (e.g., time window, tasks).

        Args:
            shift (Shift): The updated shift entity.

        Raises:
            ValueError: If the shift ID does not exist.
        """
        ...

    def delete(self, shift_id: str) -> None:
        """Removes a shift definition from the storage.

        Args:
            shift_id (str): The ID of the shift to remove.

        Raises:
            ValueError: If the shift ID does not exist.
        """
        ...


class IDataManager(Protocol):
    """
    Contract for Data Management strategies.

    Any class implementing this protocol can serve as the data engine for the
    Solver, regardless of whether it caches data in RAM or queries a DB directly.
    """

    # --- Read Methods (Used by Solver) ---

    def get_eligible_workers(self,
                             time_window: TimeWindow,
                             required_skills: Optional[Dict[str, int]] = None) -> List[Worker]:
        """Retrieves workers matching availability and requirements.

        Args:
            time_window: The time range to check availability for.
            required_skills: A dictionary of {SkillName: MinLevel}.
                             Worker must have ALL skills at >= MinLevel.

        Returns:
            List[Worker]: Valid candidates.
        """
        ...

    def get_all_shifts(self) -> List[Shift]:
        """Retrieves all shifts needed for the schedule."""
        ...

    # --- Write/Update Methods (Used by UI/Service) ---
    def get_worker(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a specific worker by their unique ID. O(1) lookup."""
        ...

    def get_shift(self, shift_id: str) -> Optional[Shift]:
        """Retrieves a specific shift by its unique ID. O(1) lookup."""
        ...

    def add_worker(self, worker: Worker) -> None:
        """Adds a worker to the system and updates internal state/indices."""
        ...

    def add_shift(self, shift: Shift) -> None:
        """Adds a shift to the system and updates internal state/indices."""
        ...

    def refresh_indices(self) -> None:
        """Forces a reload/rebuild of internal structures from the source."""
        ...

    def get_statistics(self) -> Dict[str, int]:
        """Returns system stats (worker count, shift count, etc)."""
        ...

    def update_worker(self, worker: Worker) -> None:
        """Updates worker in storage AND refreshes internal indices immediately."""
        ...

    def get_all_workers(self) -> List[Worker]:
        """Retrieves all workers currently registered in the system.

        This method is essential for applying global constraints that affect
        the entire workforce, such as "Max hours per week" or "Fairness" rules,
        even for workers who might not be eligible for specific shifts.

        Returns:
            List[Worker]: A list of all Worker domain objects.
        """
        ...