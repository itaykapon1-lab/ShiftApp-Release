"""
EXTREME EDGE CASE TESTS - AGGRESSIVE BOUNDARY TESTING
======================================================

These tests are designed to BREAK the system and find hidden bugs.
Focus on: Unicode, time boundaries, massive data, state mutations.
"""

import datetime as dt
from typing import List, Optional, Dict

import pytest

from domain.worker_model import Worker
from domain.shift_model import Shift
from domain.task_model import Task, TaskOption, Requirement
from domain.time_utils import TimeWindow
from solver.solver_engine import ShiftSolver
from solver.constraints.registry import ConstraintRegistry


class MockDataManager:
    """Minimal mock data manager."""
    
    def __init__(self, workers: List[Worker], shifts: List[Shift]):
        self._workers = {w.worker_id: w for w in workers}
        self._shifts = {s.shift_id: s for s in shifts}
        
    def get_eligible_workers(self, 
                           time_window: TimeWindow,
                           required_skills: Optional[Dict[str, int]] = None) -> List[Worker]:
        required_skills = required_skills or {}
        eligible = []
        
        for worker in self._workers.values():
            if not worker.is_available_for_shift(time_window):
                continue
                
            has_all_skills = True
            for skill_name, min_level in required_skills.items():
                if not worker.has_skill_at_level(skill_name, min_level):
                    has_all_skills = False
                    break
                    
            if has_all_skills:
                eligible.append(worker)
                
        return eligible
    
    def get_all_shifts(self) -> List[Shift]:
        return list(self._shifts.values())
    
    def get_all_workers(self) -> List[Worker]:
        return list(self._workers.values())
    
    def get_worker(self, worker_id: str) -> Optional[Worker]:
        return self._workers.get(worker_id)
    
    def get_shift(self, shift_id: str) -> Optional[Shift]:
        return self._shifts.get(shift_id)
    
    def refresh_indices(self) -> None:
        pass
    
    def add_worker(self, worker: Worker) -> None:
        self._workers[worker.worker_id] = worker
    
    def add_shift(self, shift: Shift) -> None:
        self._shifts[shift.shift_id] = shift
        
    def update_worker(self, worker: Worker) -> None:
        self._workers[worker.worker_id] = worker
        
    def get_statistics(self) -> Dict[str, int]:
        return {"worker_count": len(self._workers), "shift_count": len(self._shifts)}


@pytest.fixture
def base_dt():
    return dt.datetime(2024, 1, 15, 8, 0)


class TestUnicodeAndSpecialCharacters:
    """
    [AUTO-GENERATED SCENARIO] Reason: Unicode and special characters in names
    might break string matching, hashing, or serialization.
    """
    
    def test_unicode_skill_names(self, base_dt):
        """Test skills with unicode characters."""
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Shift", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        # Unicode skill name
        option.add_requirement(count=1, required_skills={"Français": 5})
        task.add_option(option)
        shift.add_task(task)
        
        worker = Worker(name="Émilie", worker_id="W001")
        worker.set_skill_level("français", 7)  # Different case
        worker.add_availability(base_dt, base_dt.replace(hour=20))
        
        dm = MockDataManager([worker], [shift])
        solver = ShiftSolver(dm)
        result = solver.solve()
        
        # Should handle unicode skills
        assert result["status"] in ["Optimal", "Feasible"]
    
    def test_emoji_in_worker_name(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: Emojis might break output formatting
        or string processing.
        """
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Shift 🌟", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        option.add_requirement(count=1, required_skills={"Cook": 3})
        task.add_option(option)
        shift.add_task(task)
        
        worker = Worker(name="Chef 👨‍🍳", worker_id="W-EMOJI-001")
        worker.set_skill_level("Cook", 5)
        worker.add_availability(base_dt, base_dt.replace(hour=20))
        
        dm = MockDataManager([worker], [shift])
        solver = ShiftSolver(dm)
        result = solver.solve()
        
        assert result["status"] in ["Optimal", "Feasible"]
        assert "👨‍🍳" in result["assignments"][0]["worker_name"]
    
    def test_special_characters_in_ids(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: Special chars in IDs might break
        variable naming in solver engine.
        """
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Shift", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        option.add_requirement(count=1, required_skills={"Cook": 3})
        task.add_option(option)
        shift.add_task(task)
        
        # Worker ID with special characters
        worker = Worker(name="Worker", worker_id="W-001@#$%")
        worker.set_skill_level("Cook", 5)
        worker.add_availability(base_dt, base_dt.replace(hour=20))
        
        dm = MockDataManager([worker], [shift])
        solver = ShiftSolver(dm)
        
        # Tests solver with special characters in IDs to ensure robustness
        try:
            result = solver.solve()
            assert result["status"] in ["Optimal", "Feasible"]
        except Exception as e:
            pytest.fail(f"[BUG DETECTED] Special chars in ID broke solver: {e}")


class TestTimeBoundaries:
    """
    [AUTO-GENERATED SCENARIO] Reason: Edge cases around time boundaries
    like midnight crossing, DST, year boundaries.
    """
    
    def test_shift_crossing_midnight(self):
        """Test shift that starts before and ends after midnight."""
        start = dt.datetime(2024, 1, 15, 22, 0)  # 10 PM
        end = dt.datetime(2024, 1, 16, 2, 0)     # 2 AM next day
        
        tw = TimeWindow(start, end)
        shift = Shift(name="Night Shift", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        option.add_requirement(count=1, required_skills={"Guard": 3})
        task.add_option(option)
        shift.add_task(task)
        
        worker = Worker(name="Night Owl", worker_id="W001")
        worker.set_skill_level("Guard", 5)
        worker.add_availability(start, end)
        
        dm = MockDataManager([worker], [shift])
        solver = ShiftSolver(dm)
        result = solver.solve()
        
        assert result["status"] in ["Optimal", "Feasible"]
    
    def test_year_boundary_crossing(self):
        """
        [AUTO-GENERATED SCENARIO] Reason: New Year's Eve shift might expose
        date comparison bugs.
        """
        start = dt.datetime(2024, 12, 31, 22, 0)
        end = dt.datetime(2025, 1, 1, 2, 0)
        
        tw = TimeWindow(start, end)
        shift = Shift(name="New Year Shift", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        option.add_requirement(count=1, required_skills={"Party": 5})
        task.add_option(option)
        shift.add_task(task)
        
        worker = Worker(name="Partier", worker_id="W001")
        worker.set_skill_level("Party", 10)
        worker.add_availability(start, end)
        
        dm = MockDataManager([worker], [shift])
        solver = ShiftSolver(dm)
        result = solver.solve()
        
        assert result["status"] in ["Optimal", "Feasible"]
    
    def test_microsecond_precision_overlap(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: Two shifts separated by 1 microsecond
        should NOT overlap.
        """
        # Shift 1: 8:00:00.000000 - 12:00:00.000000
        tw1 = TimeWindow(base_dt, base_dt.replace(hour=12))
        s1 = Shift(name="Morning", time_window=tw1)
        t1 = Task("Task 1")
        opt1 = TaskOption()
        opt1.add_requirement(count=1, required_skills={"Worker": 1})
        t1.add_option(opt1)
        s1.add_task(t1)
        
        # Shift 2: 12:00:00.000001 - 16:00:00.000000 (1 microsecond later)
        start2 = base_dt.replace(hour=12) + dt.timedelta(microseconds=1)
        tw2 = TimeWindow(start2, base_dt.replace(hour=16))
        s2 = Shift(name="Afternoon", time_window=tw2)
        t2 = Task("Task 2")
        opt2 = TaskOption()
        opt2.add_requirement(count=1, required_skills={"Worker": 1})
        t2.add_option(opt2)
        s2.add_task(t2)
        
        worker = Worker(name="Worker", worker_id="W001")
        worker.set_skill_level("Worker", 5)
        worker.add_availability(base_dt, base_dt.replace(hour=20))
        
        dm = MockDataManager([worker], [s1, s2])
        solver = ShiftSolver(dm)
        result = solver.solve()
        
        # Should allow both assignments (no overlap)
        assert result["status"] in ["Optimal", "Feasible"]
        # Worker should be assigned to both shifts
        assert len(result["assignments"]) == 2


class TestStateMutationIssues:
    """
    [AUTO-GENERATED SCENARIO] Reason: Solver might cache state between runs,
    causing issues when solving multiple times.
    """
    
    def test_multiple_solve_calls(self, base_dt):
        """Test that solver can be called multiple times safely."""
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Shift", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        option.add_requirement(count=1, required_skills={"Cook": 3})
        task.add_option(option)
        shift.add_task(task)
        
        worker = Worker(name="Worker", worker_id="W001")
        worker.set_skill_level("Cook", 5)
        worker.add_availability(base_dt, base_dt.replace(hour=20))
        
        dm = MockDataManager([worker], [shift])
        solver = ShiftSolver(dm)
        
        # Call solve twice
        result1 = solver.solve()
        result2 = solver.solve()
        
        # Both should succeed
        assert result1["status"] in ["Optimal", "Feasible"]
        assert result2["status"] in ["Optimal", "Feasible"]
        # Results should be identical
        assert result1["objective_value"] == result2["objective_value"]
    
    def test_data_mutation_after_solver_creation(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: If data is mutated after solver
        is created, does it use stale data?
        """
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Shift", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        option.add_requirement(count=1, required_skills={"Cook": 3})
        task.add_option(option)
        shift.add_task(task)
        
        worker = Worker(name="Worker", worker_id="W001")
        worker.set_skill_level("Cook", 5)
        worker.add_availability(base_dt, base_dt.replace(hour=20))
        
        dm = MockDataManager([worker], [shift])
        solver = ShiftSolver(dm)
        
        # Mutate worker AFTER solver creation
        worker.set_skill_level("Cooking", 10)  # Different skill
        
        # Does solver use old or new data?
        result = solver.solve()
        # Should still work with original data (Cook:5)
        assert result["status"] in ["Optimal", "Feasible"]


class TestPerformanceEdgeCases:
    """
    [AUTO-GENERATED SCENARIO] Reason: Performance bottlenecks might appear
    with specific data patterns.
    """
    
    def test_single_worker_many_shifts(self, base_dt):
        """One worker eligible for 100 non-overlapping shifts."""
        worker = Worker(name="Busy", worker_id="W001")
        worker.set_skill_level("Multi", 5)
        worker.add_availability(base_dt, base_dt + dt.timedelta(days=365))
        
        shifts = []
        for i in range(100):
            hour = (base_dt + dt.timedelta(hours=i*2))
            tw = TimeWindow(hour, hour + dt.timedelta(hours=1))
            s = Shift(name=f"S{i}", time_window=tw)
            t = Task(f"T{i}")
            opt = TaskOption()
            opt.add_requirement(count=1, required_skills={"Multi": 3})
            t.add_option(opt)
            s.add_task(t)
            shifts.append(s)
        
        dm = MockDataManager([worker], shifts)
        solver = ShiftSolver(dm)
        
        # Should handle without timeout
        result = solver.solve()
        assert result["status"] in ["Optimal", "Feasible"]
    
    def test_many_options_per_task(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: Task with 50 options might cause
        combinatorial explosion in variable creation.
        """
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Complex", time_window=tw)
        task = Task("Many Options Task")
        
        # Add 50 different options
        for i in range(50):
            opt = TaskOption(preference_score=i)
            opt.add_requirement(count=1, required_skills={f"Skill{i}": 3})
            task.add_option(opt)
        
        shift.add_task(task)
        
        # Create workers for each skill
        workers = []
        for i in range(50):
            w = Worker(name=f"Worker{i}", worker_id=f"W{i:03d}")
            w.set_skill_level(f"Skill{i}", 5)
            w.add_availability(base_dt, base_dt.replace(hour=20))
            workers.append(w)
        
        dm = MockDataManager(workers, [shift])
        solver = ShiftSolver(dm)
        
        result = solver.solve()
        assert result["status"] in ["Optimal", "Feasible"]
        # Should choose option with highest score (49)
        assert result["objective_value"] >= 49


class TestRequirementCountEdgeCases:
    """
    [AUTO-GENERATED SCENARIO] Reason: Testing extreme requirement counts.
    """
    
    def test_zero_count_requirement(self, base_dt):
        """
        Requirement(count=0) is semantically invalid and must be rejected
        at construction time with a ValueError.
        """
        with pytest.raises(ValueError, match="count must be >= 1"):
            Requirement(count=0, required_skills={"Cook": 3})
    
    def test_massive_requirement_count(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: Requiring 1000 workers tests
        scalability of coverage constraint.
        """
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Mass Event", time_window=tw)
        task = Task("Stadium")
        option = TaskOption()
        option.add_requirement(count=1000, required_skills={"Security": 1})
        task.add_option(option)
        shift.add_task(task)
        
        # Only 10 workers available
        workers = []
        for i in range(10):
            w = Worker(name=f"Guard{i}", worker_id=f"W{i:03d}")
            w.set_skill_level("Security", 5)
            w.add_availability(base_dt, base_dt.replace(hour=20))
            workers.append(w)
        
        dm = MockDataManager(workers, [shift])
        solver = ShiftSolver(dm)
        result = solver.solve()
        
        # Should be infeasible (need 1000, have 10)
        assert result["status"] == "Infeasible"


class TestDuplicateData:
    """
    [AUTO-GENERATED SCENARIO] Reason: Duplicate workers or shifts might
    break uniqueness assumptions.
    """
    
    def test_duplicate_worker_ids(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: What if two workers have same ID?
        MockDataManager will overwrite, but real system might break.
        """
        tw = TimeWindow(base_dt, base_dt.replace(hour=16))
        shift = Shift(name="Shift", time_window=tw)
        task = Task("Task")
        option = TaskOption()
        option.add_requirement(count=1, required_skills={"Cook": 3})
        task.add_option(option)
        shift.add_task(task)
        
        # Two workers with SAME ID
        w1 = Worker(name="Alice", worker_id="W001")
        w1.set_skill_level("Cook", 5)
        w1.add_availability(base_dt, base_dt.replace(hour=20))
        
        w2 = Worker(name="Bob", worker_id="W001")  # DUPLICATE ID
        w2.set_skill_level("Cook", 3)
        w2.add_availability(base_dt, base_dt.replace(hour=20))
        
        # MockDataManager will keep only the last one (Bob)
        dm = MockDataManager([w1, w2], [shift])
        
        # Verify only Bob exists
        assert len(dm.get_all_workers()) == 1
        assert dm.get_all_workers()[0].name == "Bob"


class TestConstraintInteractions:
    """
    [AUTO-GENERATED SCENARIO] Reason: Complex interactions between multiple
    constraints might create unexpected conflicts.
    """
    
    def test_overlapping_shifts_with_preferences(self, base_dt):
        """
        [AUTO-GENERATED SCENARIO] Reason: Worker prefers shift A but it overlaps
        with shift B. Tests if preference vs hard constraint is handled correctly.
        """
        # Shift A: 8-12 (worker prefers this)
        tw1 = TimeWindow(base_dt, base_dt.replace(hour=12))
        s1 = Shift(name="Preferred", time_window=tw1)
        t1 = Task("Task A")
        opt1 = TaskOption()
        opt1.add_requirement(count=1, required_skills={"Worker": 1})
        t1.add_option(opt1)
        s1.add_task(t1)
        
        # Shift B: 10-14 (overlaps, no preference)
        tw2 = TimeWindow(base_dt.replace(hour=10), base_dt.replace(hour=14))
        s2 = Shift(name="Other", time_window=tw2)
        t2 = Task("Task B")
        opt2 = TaskOption()
        opt2.add_requirement(count=1, required_skills={"Worker": 1})
        t2.add_option(opt2)
        s2.add_task(t2)
        
        worker = Worker(name="Worker", worker_id="W001")
        worker.set_skill_level("Worker", 5)
        worker.add_availability(base_dt, base_dt.replace(hour=20))
        worker.add_preference(tw1, 100)  # Strong preference for shift A
        
        dm = MockDataManager([worker], [s1, s2])
        solver = ShiftSolver(dm)
        result = solver.solve()
        
        # Should choose shift A due to preference (can only do one)
        if result["status"] in ["Optimal", "Feasible"]:
            assert len(result["assignments"]) == 1
            assert result["assignments"][0]["shift_name"] == "Preferred"


"""
SUMMARY: EXTREME EDGE CASE TESTS

Coverage:
✓ Unicode and special characters in names/IDs
✓ Time boundaries (midnight, year crossing, microseconds)
✓ State mutation and multiple solve calls
✓ Performance with extreme data patterns
✓ Zero and massive requirement counts
✓ Duplicate data handling
✓ Constraint interaction edge cases

These tests are designed to find breaking points that normal usage wouldn't reveal.
"""
