"""Session Data Manager Adapter.

This module implements the IDataManager interface using pure domain objects
(not SQLAlchemy models) to avoid DetachedInstanceError when accessing data
in background threads after the DB session closes.

The adapter is initialized with a snapshot of domain objects fetched from
the database, ensuring complete decoupling from SQLAlchemy.
"""
import logging
from typing import List, Dict, Optional
from collections import defaultdict

from repositories.interfaces import IDataManager
from domain.worker_model import Worker
from domain.shift_model import Shift, TimeWindow

logger = logging.getLogger(__name__)
class SessionDataManagerAdapter(IDataManager):
    """
    In-memory implementation of IDataManager using pure domain objects.
    
    This adapter is initialized with a snapshot of Workers and Shifts
    that have been converted from SQLAlchemy models to pure domain objects.
    This ensures the solver can access data safely in background threads
    without database session dependencies.
    
    Attributes:
        _workers: Dictionary mapping worker_id to Worker domain objects
        _shifts: Dictionary mapping shift_id to Shift domain objects
        _availability_index: Optimized index for fast worker lookup by time window
    """
    
    def __init__(self, workers: List[Worker], shifts: List[Shift]):
        """
        Initialize the adapter with pure domain objects.

        Args:
            workers: List of Worker domain objects (not SQLAlchemy models)
            shifts: List of Shift domain objects (not SQLAlchemy models)
        """
        # Store as ID-keyed dicts for O(1) lookup by the solver engine.
        # These are plain Python dataclasses — no SQLAlchemy session dependency.
        self._workers: Dict[str, Worker] = {w.worker_id: w for w in workers}
        self._shifts: Dict[str, Shift] = {s.shift_id: s for s in shifts}

        # Build the three-level availability index:
        #   TimeWindow → SkillName → SkillLevel → [Workers]
        # This pre-computation allows the solver to find eligible workers
        # for a given shift+skill combination in near-constant time.
        self._availability_index: Dict[TimeWindow, Dict[str, Dict[int, List[Worker]]]] = {}
        self._build_availability_index()
    
    def _build_availability_index(self) -> None:
        """Builds an index mapping time windows to available workers by skill."""
        # Extract the set of distinct TimeWindows from all shifts.
        # Only shift time windows are indexed — there's no need to index
        # hypothetical windows that no shift covers.
        unique_windows = {shift.time_window for shift in self._shifts.values()}

        for window in unique_windows:
            # skill_map[SkillName][Level] = list of workers with that skill at that level
            skill_map: Dict[str, Dict[int, List[Worker]]] = {}

            for worker in self._workers.values():
                # Check if the worker's declared availability overlaps this window.
                if worker.is_available_for_shift(window):
                    # Register every skill the worker has at its current level.
                    # Example: worker with {Cook: 5, Waiter: 3} is added to
                    #   skill_map["Cook"][5] AND skill_map["Waiter"][3].
                    for skill_name, level in worker.skills.items():
                        if skill_name not in skill_map:
                            skill_map[skill_name] = {}
                        if level not in skill_map[skill_name]:
                            skill_map[skill_name][level] = []
                        skill_map[skill_name][level].append(worker)

            self._availability_index[window] = skill_map
    
    def get_all_workers(self) -> List[Worker]:
        """Returns all workers in the system."""
        return list(self._workers.values())
    
    def get_all_shifts(self) -> List[Shift]:
        """Returns all shifts in the system."""
        return list(self._shifts.values())
    
    def get_eligible_workers(
        self,
        time_window: TimeWindow,
        required_skills: Optional[Dict[str, int]] = None
    ) -> List[Worker]:
        """
        Retrieves workers matching availability and skill requirements.
        
        Args:
            time_window: The time range to check availability for
            required_skills: Dictionary of {SkillName: MinLevel}
            
        Returns:
            List of eligible Worker domain objects
        """
        # If this time window was never indexed (no shift covers it),
        # no workers can possibly be available — short-circuit.
        if time_window not in self._availability_index:
            logger.debug("Time window %s not in availability index", time_window)
            return []

        skill_map = self._availability_index[time_window]

        # Base case: no specific skills required — return every worker who
        # is available during this window, regardless of their skills.
        if not required_skills:
            all_workers = set()
            for level_map in skill_map.values():
                for workers in level_map.values():
                    all_workers.update(workers)
            return list(all_workers)

        # Skill-filtered case: build one candidate set per required skill,
        # then intersect.  A worker must satisfy ALL required skills (AND logic).
        candidate_sets: List[set] = []

        for req_skill, min_level in required_skills.items():
            # Normalize skill name to Title Case for case-insensitive matching.
            req_skill = req_skill.strip().title()

            if req_skill not in skill_map:
                # No worker in this window has this skill at ANY level — impossible.
                return []

            # Collect workers whose skill level meets or exceeds the minimum.
            # E.g., if min_level=3, include workers at levels 3, 4, 5, etc.
            valid_workers = set()
            for level, workers in skill_map[req_skill].items():
                if level >= min_level:
                    valid_workers.update(workers)

            if not valid_workers:
                logger.debug("No workers meet minimum level for skill '%s' in time window %s", req_skill, time_window)
                return []  # No one meets the minimum level for this skill

            candidate_sets.append(valid_workers)

        # Final intersection: set.intersection(*candidate_sets) returns only
        # workers who appear in EVERY candidate set — i.e., possess ALL skills.
        if not candidate_sets:
            logger.debug("No valid workers available for time window %s", time_window)
            return []

        final_candidates = set.intersection(*candidate_sets)
        return list(final_candidates)
    
    def get_worker(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a worker by ID."""
        return self._workers.get(worker_id)
    
    def get_shift(self, shift_id: str) -> Optional[Shift]:
        """Retrieves a shift by ID."""
        return self._shifts.get(shift_id)
    
    # Write methods are forbidden — this adapter is read-only for solver use.
    def add_worker(self, worker: Worker) -> None:
        """Read-only adapter — mutation is not permitted."""
        raise NotImplementedError(
            "SessionDataManagerAdapter is read-only; add_worker() is not supported."
        )

    def add_shift(self, shift: Shift) -> None:
        """Read-only adapter — mutation is not permitted."""
        raise NotImplementedError(
            "SessionDataManagerAdapter is read-only; add_shift() is not supported."
        )

    def update_worker(self, worker: Worker) -> None:
        """Read-only adapter — mutation is not permitted."""
        raise NotImplementedError(
            "SessionDataManagerAdapter is read-only; update_worker() is not supported."
        )

    def refresh_indices(self) -> None:
        """No-op — indices are pre-built in __init__ and never change.

        The solver engine calls ``refresh_indices()`` before variable construction.
        For this read-only adapter the availability index is already up-to-date
        (built once during ``__init__``), so no work is needed.
        """
    
    def get_statistics(self) -> Dict[str, int]:
        """Returns statistics about cached data."""
        return {
            "total_workers": len(self._workers),
            "total_shifts": len(self._shifts),
            "indexed_windows": len(self._availability_index)
        }
