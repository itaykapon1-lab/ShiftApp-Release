"""Mock data generator for the staff scheduling system.

This module creates a sample scenario with workers, skills, tasks, and shifts.
It serves as the input for testing the optimization solver.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any

import domain.task_model as task_model

# Imports assuming the file structure we defined
from domain.time_utils import TimeWindow
from domain.task_model import Skill, Talent, Task, TaskOption
from domain.shift_model import Shift
from domain.worker_model import Worker


def create_mock_data() -> Dict[str, Any]:
    """Generates a complete set of mock data for testing.

    Scenario: A small restaurant operating on a Sunday.
    - 2 Shifts: Morning (Breakfast) and Evening (Dinner).
    - Workers: A mix of Chefs, Cooks, and Waiters with different preferences.

    Returns:
        Dict containing lists of 'workers' and 'shifts'.
    """

    # --- 1. Create Workers ---
    # Each worker has skills (what they can do), talents (proficiency level),
    # and time preferences (soft constraints that influence the solver's scoring).

    # Worker 1: The Head Chef (Expensive, likes mornings, hates evenings)
    w_chef = Worker(name="Gordon", worker_id="101")
    w_chef.add_skill(Skill.CHEF)
    w_chef.add_talent(Talent.SENIOR)    # High proficiency tier
    w_chef.add_talent(Talent.LEADER)    # Can manage a team
    w_chef.add_preferred_hours(8, 14, weight=20)  # +20 soft score for morning assignment
    w_chef.add_unwanted_hours(16, 23, penalty=20)  # -20 soft penalty for evening assignment

    # Worker 2: The Sous Chef (Flexible, fast)
    w_sous = Worker(name="Ramsay", worker_id="102")
    w_sous.add_skill(Skill.SOUS_CHEF)
    w_sous.add_skill(Skill.COOK)  # Can also work as a regular cook
    w_sous.add_talent(Talent.FAST)
    # No strong time preferences

    # Worker 3: Junior Cook (Learning, prefers evenings)
    w_cook = Worker(name="Jamie", worker_id="103")
    w_cook.add_skill(Skill.COOK)
    w_cook.add_talent(Talent.JUNIOR)
    w_cook.add_preferred_hours(16, 23, weight=10)

    # Worker 4: Senior Waiter
    w_waiter1 = Worker(name="Penny", worker_id="104")
    w_waiter1.add_skill(Skill.WAITER)
    w_waiter1.add_talent(Talent.SENIOR)

    # Worker 5: Junior Waiter
    w_waiter2 = Worker(name="Leonard", worker_id="105")
    w_waiter2.add_skill(Skill.WAITER)
    w_waiter2.add_talent(Talent.JUNIOR)

    workers = [w_chef, w_sous, w_cook, w_waiter1, w_waiter2]

    # --- 2. Create Tasks & Options ---
    # Tasks define WHAT needs to be done. Each task has one or more Options
    # (alternative staffing configurations). The solver picks exactly one option
    # per task to satisfy the requirement.

    # Task A: Kitchen Management (Requires high skill)
    task_kitchen = Task(name="Kitchen Lead")

    # Option 1: 1 Senior Chef (Ideal) — preference_score=10 makes solver prefer this
    opt_k1 = TaskOption(preference_score=10)
    opt_k1.add_requirement(count=1, skills=[Skill.CHEF], talents=[Talent.SENIOR])

    # Option 2: 1 Sous Chef + 1 Cook (Fallback) — score=0 means solver only picks
    # this if Option 1 is infeasible (no senior chef available)
    opt_k2 = TaskOption(preference_score=0)
    opt_k2.add_requirement(count=1, skills=[Skill.SOUS_CHEF])
    opt_k2.add_requirement(count=1, skills=[Skill.COOK])

    task_kitchen.add_option(opt_k1)
    task_kitchen.add_option(opt_k2)

    # Task B: Service (General)
    task_service = Task(name="Floor Service")
    opt_s1 = TaskOption(preference_score=0)
    opt_s1.add_requirement(count=2, skills=[Skill.WAITER])  # Need 2 waiters
    task_service.add_option(opt_s1)

    # --- 3. Create Shifts ---
    # Shifts define WHEN work happens. Each shift has a time window and
    # one or more tasks that need to be staffed during that window.

    # Use canonical epoch anchor date (Monday 2024-01-01) as the base
    base_date = datetime(2024, 1, 1)

    # Shift 1: Morning (08:00 - 14:00)
    morning_win = TimeWindow(
        start=base_date.replace(hour=8, minute=0),
        end=base_date.replace(hour=14, minute=0)
    )
    shift_morning = Shift(name="Sun Morning", time_window=morning_win)
    shift_morning.add_task(task_kitchen)  # Needs kitchen staff
    shift_morning.add_task(task_service)  # Needs waiters

    # Shift 2: Evening (16:00 - 22:00)
    evening_win = TimeWindow(
        start=base_date.replace(hour=16, minute=0),
        end=base_date.replace(hour=22, minute=0)
    )
    shift_evening = Shift(name="Sun Dinner", time_window=evening_win)
    shift_evening.add_task(task_kitchen)  # Needs kitchen staff
    # Note: Using the same task definition is fine, or create new ones if requirements differ

    shifts = [shift_morning, shift_evening]

    print(f"Generated {len(workers)} workers and {len(shifts)} shifts.")
    return {
        "workers": workers,
        "shifts": shifts
    }


if __name__ == "__main__":
    # Test the generator
    data = create_mock_data()

    # Simple validation print
    chef = data['workers'][0]
    morning_shift = data['shifts'][0]
    score = chef.calculate_preference_score(morning_shift)

    print(f"\nTest Preference Calculation:")
    print(f"Worker {chef.name} preference for {morning_shift.name}: {score}")
    # Expected: 20 (because he likes 08:00-14:00)