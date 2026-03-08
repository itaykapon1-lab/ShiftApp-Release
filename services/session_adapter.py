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
        # Store as dictionaries for O(1) lookup
        self._workers: Dict[str, Worker] = {w.worker_id: w for w in workers}
        self._shifts: Dict[str, Shift] = {s.shift_id: s for s in shifts}
        
        # Build availability index for fast queries
        self._availability_index: Dict[TimeWindow, Dict[str, Dict[int, List[Worker]]]] = {}
        self._build_availability_index()
    
    def _build_availability_index(self) -> None:
        """Builds an index mapping time windows to available workers by skill."""
        # Get all unique time windows from shifts
        unique_windows = {shift.time_window for shift in self._shifts.values()}
        
        for window in unique_windows:
            skill_map: Dict[str, Dict[int, List[Worker]]] = {}
            
            for worker in self._workers.values():
                if worker.is_available_for_shift(window):
                    # Index by all skills the worker has
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
        # Check if window is indexed
        if time_window not in self._availability_index:
            logger.warning("Time window %s is not available")
            return []
        
        skill_map = self._availability_index[time_window]
        
        # No specific skills required - return all available workers
        if not required_skills:
            all_workers = set()
            for level_map in skill_map.values():
                for workers in level_map.values():
                    all_workers.update(workers)
            return list(all_workers)
        
        # Filter by skills - intersection logic
        candidate_sets: List[set] = []
        
        for req_skill, min_level in required_skills.items():
            req_skill = req_skill.strip().title()
            
            if req_skill not in skill_map:
                return []  # No one has this skill
            
            # Get all workers with level >= min_level
            valid_workers = set()
            for level, workers in skill_map[req_skill].items():
                if level >= min_level:
                    valid_workers.update(workers)
            
            if not valid_workers:
                logger.warning("No valid workers meets the minimum level available for time window")
                return []  # No one meets the minimum level
            
            candidate_sets.append(valid_workers)
        
        # Intersection: workers must appear in ALL candidate sets
        if not candidate_sets:
            logger.warning(f"No valid workers available for time window %s")
            return []
        
        final_candidates = set.intersection(*candidate_sets)
        return list(final_candidates)
    
    def get_worker(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a worker by ID."""
        return self._workers.get(worker_id)
    
    def get_shift(self, shift_id: str) -> Optional[Shift]:
        """Retrieves a shift by ID."""
        return self._shifts.get(shift_id)
    
    # Write methods are stubs - this adapter is read-only for solver use
    def add_worker(self, worker: Worker) -> None:
        """Stub - not used by solver."""
        pass
    
    def add_shift(self, shift: Shift) -> None:
        """Stub - not used by solver."""
        pass
    
    def update_worker(self, worker: Worker) -> None:
        """Stub - not used by solver."""
        pass
    
    def refresh_indices(self) -> None:
        """Stub - not used by solver."""
        pass
    
    def get_statistics(self) -> Dict[str, int]:
        """Returns statistics about cached data."""
        return {
            "total_workers": len(self._workers),
            "total_shifts": len(self._shifts),
            "indexed_windows": len(self._availability_index)
        }
