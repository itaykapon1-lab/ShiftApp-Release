"""Data Manager Service Layer.

This module implements the IDataManager protocol, acting as an intelligent
optimization and caching layer between the raw data storage (Repositories)
and the Solver Engine.

It is designed to be **Storage Agnostic**. It does not know if the data comes
from a SQL database, a CSV file, or an in-memory list. It relies solely on
injected repositories adhering to the `IWorkerRepository` and `IShiftRepository`
interfaces.

Key Responsibilities:
1.  **Caching:** Loads data from repositories into memory for fast access.
2.  **Indexing:** Builds O(1) lookup indices (e.g., Skill -> Level -> Workers)
    to avoid full table scans during the solving process.
3.  **Filtering:** Provides sophisticated logic to find eligible workers for
    specific time windows and skill requirements.
"""

import logging
from typing import Dict, List, Set, Tuple, Optional, DefaultDict
from collections import defaultdict

# Domain Imports
from domain.worker_model import Worker
from domain.shift_model import Shift, TimeWindow
from repositories.interfaces import IDataManager, IWorkerRepository, IShiftRepository

# Configure Logger
logger = logging.getLogger(__name__)


class SchedulingDataManager(IDataManager):
    """Robust In-Memory Cache & Optimization Layer over Repositories.

    This class decouples the Solver from the persistence layer. It pre-loads
    data from the provided repositories and organizes it into optimized
    data structures that allow the solver to query worker availability
    and skill matching in constant or near-constant time.

    Attributes:
        _worker_repo (IWorkerRepository): The source of truth for workers.
        _shift_repo (IShiftRepository): The source of truth for shifts.
        _availability_index (Dict): The core optimization structure mapping
            time windows to skilled workers.
        _worker_registry (Dict): A reverse index mapping workers to the
            time windows they are available in.
        _worker_cache (Dict[str, Worker]): Fast lookup cache by ID.
        _shift_cache (Dict[str, Shift]): Fast lookup cache by ID.
    """

    def __init__(self,
                 worker_repo: IWorkerRepository,
                 shift_repo: IShiftRepository):
        """Initializes the manager with data sources.

        Args:
            worker_repo (IWorkerRepository): Repository to fetch workers from.
            shift_repo (IShiftRepository): Repository to fetch shifts from.
        """
        self._worker_repo = worker_repo
        self._shift_repo = shift_repo

        # --- Optimization Indices ---
        # Structure: TimeWindow -> Dict[SkillName, Dict[Level, Set[Worker]]]
        # Example: window -> "Cook" -> {5: {w1, w2}, 3: {w3}}
        self._availability_index: Dict[
            TimeWindow,
            DefaultDict[str, DefaultDict[int, Set[Worker]]]
        ] = {}

        # Reverse Index for O(1) Updates/Removals:
        # Key: Worker ID -> Value: Set of TimeWindows currently indexed for this worker.
        self._worker_registry: DefaultDict[str, Set[TimeWindow]] = defaultdict(set)

        # Entity Caches for O(1) Retrieval
        self._worker_cache: Dict[str, Worker] = {}
        self._shift_cache: Dict[str, Shift] = {}

        # Initial data load
        self.refresh_indices()

    # =========================================================================
    # Read Methods (Solver Interface)
    # =========================================================================

    def get_eligible_workers(self,
                             time_window: TimeWindow,
                             required_skills: Optional[Dict[str, int]] = None) -> List[Worker]:
        """Retrieves eligible workers using cached indices with threshold filtering.

        This method performs a set intersection of workers who:
        1. Are available during the specified `time_window`.
        2. Possess ALL the `required_skills` at the minimum specified level.

        Args:
            time_window (TimeWindow): The time slot to check availability for.
            required_skills (Dict[str, int], optional): A dictionary mapping
                skill names to minimum required levels. Example: {"Cook": 5}.

        Returns:
            List[Worker]: A list of unique workers matching all criteria.
        """
        # 1. Lazy Load / Safety Check
        # If the window isn't indexed, no workers are available in cache.
        if time_window not in self._availability_index:
            return []

        skill_level_map = self._availability_index[time_window]

        # 2. Base Case: No specific skills required
        # Return all workers available in this window.
        if not required_skills:
            all_in_window = set()
            for lvl_map in skill_level_map.values():
                for w_set in lvl_map.values():
                    all_in_window.update(w_set)
            return list(all_in_window)

        candidate_sets: List[Set[Worker]] = []

        # 3. Filter by Skills (Intersection Logic)
        for req_skill, min_level in required_skills.items():
            # Normalize skill name to ensure case-insensitive lookup
            req_skill = req_skill.strip().title()

            if req_skill not in skill_level_map:
                # Optimization: If NOBODY available has this skill, impossible to fulfill.
                return []

            # Get the map of {Level -> Set[Workers]} for this skill
            levels_map = skill_level_map[req_skill]

            # Collect all workers with Level >= min_level
            valid_workers_for_skill = set()
            for level, workers in levels_map.items():
                if level >= min_level:
                    valid_workers_for_skill.update(workers)

            if not valid_workers_for_skill:
                return []

            candidate_sets.append(valid_workers_for_skill)

        # 4. Final Intersection (AND Logic)
        # Workers must appear in ALL candidate sets.
        if not candidate_sets:
            return []

        final_candidates = set.intersection(*candidate_sets)
        return list(final_candidates)

    def get_all_shifts(self) -> List[Shift]:
        """Retrieves all shifts currently loaded in the cache.

        Returns:
            List[Shift]: A list of Shift objects.
        """
        return list(self._shift_cache.values())

    def get_all_workers(self) -> List[Worker]:
        """Retrieves all workers currently loaded in the cache.

        Returns:
            List[Worker]: A list of Worker objects.
        """
        return list(self._worker_cache.values())

    def get_worker(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a worker by ID from the cache. O(1)."""
        return self._worker_cache.get(worker_id)

    def get_shift(self, shift_id: str) -> Optional[Shift]:
        """Retrieves a shift by ID from the cache. O(1)."""
        return self._shift_cache.get(shift_id)

    def get_statistics(self) -> Dict[str, int]:
        """Returns high-level statistics about the cached data."""
        return {
            "total_workers": len(self._worker_cache),
            "total_shifts": len(self._shift_cache),
            "indexed_windows": len(self._availability_index)
        }

    # =========================================================================
    # Write / Refresh Methods
    # =========================================================================

    def refresh_indices(self) -> None:
        """Reloads all data from the repositories and rebuilds internal indices.

        This method pulls the latest state from the injected `worker_repo` and
        `shift_repo`, clears the internal cache, and re-indexes everything.
        Crucial for ensuring the solver works with up-to-date data.
        """
        logger.info("Refreshing SchedulingDataManager indices from repositories...")

        # 1. Fetch Data from Source
        all_workers = self._worker_repo.get_all()
        all_shifts = self._shift_repo.get_all()

        # 2. Reset Caches
        self._availability_index.clear()
        self._worker_registry.clear()
        self._worker_cache = {w.worker_id: w for w in all_workers}
        self._shift_cache = {s.shift_id: s for s in all_shifts}

        # 3. Identify all relevant time windows
        # We index windows defined by shifts.
        unique_windows = {shift.time_window for shift in all_shifts}

        # (Optional) We could also index windows where workers are available
        # even if no shift currently exists there, but usually, we only care
        # about shift times.

        # 4. Rebuild Availability Index
        for window in unique_windows:
            self._initialize_index_for_window(window, all_workers)

        logger.info(
            "Refresh complete. Cached %d workers, %d shifts.",
            len(all_workers),
            len(all_shifts)
        )

    def add_worker(self, worker: Worker) -> None:
        """Persists a worker to the repo and updates the cache.

        Args:
            worker (Worker): The worker to add.
        """
        self._worker_repo.add(worker)

        # Write-Through Cache Update
        self._worker_cache[worker.worker_id] = worker
        self._index_worker_safely(worker)

    def update_worker(self, worker: Worker) -> None:
        """Updates a worker in the repo and refreshes their index entries.

        Args:
            worker (Worker): The updated worker object.
        """
        self._worker_repo.update(worker)

        # Update Cache
        self._worker_cache[worker.worker_id] = worker

        # Re-index: Remove old entries -> Add new entries
        self._remove_worker_from_index(worker.worker_id)
        self._index_worker_safely(worker)

    def add_shift(self, shift: Shift) -> None:
        """Persists a shift to the repo and updates the cache.

        Args:
            shift (Shift): The shift to add.
        """
        self._shift_repo.add(shift)

        self._shift_cache[shift.shift_id] = shift

        # Ensure the shift's time window is indexed
        if shift.time_window not in self._availability_index:
            self._initialize_index_for_window(
                shift.time_window,
                list(self._worker_cache.values())
            )

    # =========================================================================
    # Internal Indexing Logic (Helpers)
    # =========================================================================

    def _initialize_index_for_window(self,
                                     window: TimeWindow,
                                     workers: List[Worker]) -> None:
        """Builds the hash maps for a specific time window.

        Creates the mapping: SkillName -> Level -> Set[Worker].

        Args:
            window (TimeWindow): The window to index.
            workers (List[Worker]): All workers to check against this window.
        """
        # Dict[SkillName, Dict[Level, Set[Worker]]]
        index_map: DefaultDict[str, DefaultDict[int, Set[Worker]]] = defaultdict(
            lambda: defaultdict(set)
        )

        for worker in workers:
            if worker.is_available_for_shift(window):
                # 1. Index every skill the worker has
                for skill_name, level in worker.skills.items():
                    index_map[skill_name][level].add(worker)

                # 2. Track general availability (even for unskilled workers)
                # We update the reverse registry here to ensure we know
                # this worker is "active" in this window.
                self._worker_registry[worker.worker_id].add(window)

        self._availability_index[window] = index_map

    def _index_worker_safely(self, worker: Worker) -> None:
        """Injects a single worker into all existing window indices.

        Used during `add_worker` or `update_worker` to avoid a full rebuild.

        Args:
            worker (Worker): The worker to index.
        """
        for window in self._availability_index:
            if worker.is_available_for_shift(window):
                skill_level_map = self._availability_index[window]

                for skill_name, level in worker.skills.items():
                    skill_level_map[skill_name][level].add(worker)

                self._worker_registry[worker.worker_id].add(window)

    def _remove_worker_from_index(self, worker_id: str) -> None:
        """Removes a worker from cached indices using the reverse registry.

        Used before updating a worker to clear stale data.

        Args:
            worker_id (str): The ID of the worker to remove.
        """
        windows_to_check = self._worker_registry.get(worker_id, set())

        for window in windows_to_check:
            if window in self._availability_index:
                skill_level_map = self._availability_index[window]

                for level_map in skill_level_map.values():
                    for w_set in level_map.values():
                        # Efficiently remove the worker by ID
                        # (Requires Worker objects to be hashable/equal by ID)
                        to_remove = [w for w in w_set if w.worker_id == worker_id]
                        for w in to_remove:
                            w_set.discard(w)

        # Clear the reverse registry entry
        if worker_id in self._worker_registry:
            del self._worker_registry[worker_id]


class InMemoryDataManager(IDataManager):
    """Simple adapter for stateless execution or testing.

    This implementation wraps lists of Workers and Shifts and provides
    the `IDataManager` interface without complex indexing. Useful for
    small datasets or unit tests where performance is not critical.
    """

    def __init__(self, workers: List[Worker], shifts: List[Shift]):
        self._workers = workers
        self._shifts = shifts

    def get_all_workers(self) -> List[Worker]:
        return self._workers

    def get_all_shifts(self) -> List[Shift]:
        return self._shifts

    def get_worker(self, worker_id: str) -> Optional[Worker]:
        for worker in self._workers:
            if worker.worker_id == worker_id:
                return worker
        return None

    def get_shift(self, shift_id: str) -> Optional[Shift]:
        for shift in self._shifts:
            if shift.shift_id == shift_id:
                return shift
        return None

    def get_eligible_workers(
            self,
            time_window: TimeWindow,
            required_skills: Optional[Dict[str, int]] = None
    ) -> List[Worker]:
        """Linearly scans workers to find matches (O(N))."""
        eligible = []
        for worker in self._workers:
            # 1. Check Availability
            if not worker.is_available_for_shift(time_window):
                continue

            # 2. Check Skill Levels
            if required_skills:
                meets_criteria = True
                for s_name, min_lvl in required_skills.items():
                    if not worker.has_skill_at_level(s_name, min_lvl):
                        meets_criteria = False
                        break
                if not meets_criteria:
                    continue

            eligible.append(worker)

        return eligible

    # Stubs for write methods (In-Memory usually doesn't need persistence logic)
    def add_worker(self, worker: Worker): self._workers.append(worker)
    def add_shift(self, shift: Shift): self._shifts.append(shift)
    def update_worker(self, worker: Worker): pass
    def refresh_indices(self): pass
    def get_statistics(self): return {}