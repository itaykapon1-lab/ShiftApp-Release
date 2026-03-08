"""Main Entry Point for the SQL-Backed Shift Scheduler.

This script orchestrates the full pipeline:
1.  **Database Setup:** Initializes the SQLite DB schema.
2.  **ETL (Extract-Transform-Load):** Parses the Excel file and persists data to SQL.
3.  **Optimization:** Loads data from SQL into the Solver and computes the schedule.

Typical usage:
    $ python main.py
"""

import logging
import sys
import os
from typing import Dict, Any

# --- Infrastructure & DB ---
from data.database import DatabaseService
from data.models import Base
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository

# --- Logic Layers ---
from data.ex_parser import ExcelParser
from data.data_manager import SchedulingDataManager
from solver.solver_engine import ShiftSolver

# --- Configure Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Configuration
DB_URL = "sqlite:///scheduler.db"
INPUT_FILE = os.environ.get("INPUT_FILE", "test_data/sample.xlsx")


def reset_database(db_service: DatabaseService) -> None:
    """Drops and recreates tables to ensure a clean slate for this run."""
    logger.info("Resetting database schema...")
    Base.metadata.drop_all(bind=db_service._engine)
    db_service.create_tables()


def run_pipeline(file_path: str) -> None:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Input file not found: {file_path}")

    # 1. Initialize Database Infrastructure
    db_service = DatabaseService(DB_URL)
    reset_database(db_service)  # Optional: Clear DB for a fresh run from Excel

    # =========================================================================
    # PHASE 1: ETL (Excel -> SQL)
    # =========================================================================
    logger.info("--- PHASE 1: Loading Data (Excel -> SQL) ---")

    constraint_registry = None

    # We use a transaction to parse and save everything safely
    with db_service.provide_session() as write_session:
        # Initialize Repositories bound to this session
        worker_repo = SQLWorkerRepository(write_session)
        shift_repo = SQLShiftRepository(write_session)

        # Initialize Parser with the repositories
        # The parser acts as a "Pump", pushing data into the repos
        parser = ExcelParser(worker_repo, shift_repo)

        # Execute Parse & Load
        parser.load_from_file(file_path)

        # Get the constraints (Logic that lives in code/registry, not just DB rows)
        constraint_registry = parser.get_constraint_registry()

        # Commit happens automatically when exiting 'with' block
        logger.info("Data successfully persisted to SQLite.")

    # =========================================================================
    # PHASE 2: SOLVING (SQL -> Solver)
    # =========================================================================
    logger.info("--- PHASE 2: Optimization (SQL -> Solver) ---")

    # We open a NEW session for reading. This proves data is coming from DB.
    with db_service.provide_session() as read_session:
        # Repositories for reading
        read_worker_repo = SQLWorkerRepository(read_session)
        read_shift_repo = SQLShiftRepository(read_session)

        # Initialize the Generic Data Manager
        # It doesn't know about SQL; it just asks the Repos for data.
        data_manager = SchedulingDataManager(read_worker_repo, read_shift_repo)

        logger.info(
            "Data Loaded into Solver Memory: %d Workers, %d Shifts.",
            len(data_manager.get_all_workers()),
            len(data_manager.get_all_shifts())
        )

        # Initialize Solver
        solver = ShiftSolver(data_manager, constraint_registry)

        logger.info("Solving...")
        result = solver.solve()

        if result["status"] == "Infeasible":
            logger.warning("Infeasible Schedule.")
            print(f"\nReason: {solver.diagnose_infeasibility()}\n")
            return

        _print_results(result)


from collections import defaultdict

from collections import defaultdict

from collections import defaultdict

from collections import defaultdict
from typing import Dict, Any


def _print_results(result: Dict[str, Any]) -> None:
    """Formats results in a Tree structure showing specific skills per worker."""
    status = result.get("status", "Unknown")
    stats = result.get("statistics", {})
    assignments = result.get("assignments", [])

    # --- 1. Print Header ---
    print("\n" + "═" * 80)
    print(f"📊  OPTIMIZATION RESULTS")
    print("═" * 80)
    print(f"   🔹 Status: {status.upper()} | Score: {stats.get('objective_value', 0):.2f}")
    print("─" * 80 + "\n")

    if not assignments:
        print("❌ No assignments generated.")
        return

    # --- 2. Grouping Logic ---
    shifts_map = {}

    for assign in assignments:
        day = assign.get('day', str(assign.get('time', ''))[:10])
        raw_time = assign.get('time', 'N/A')
        time_range = raw_time[11:16] if len(raw_time) > 16 else raw_time
        shift_name = assign.get('shift_name', 'Unknown')

        shift_key = (day, time_range, shift_name)

        if shift_key not in shifts_map:
            shifts_map[shift_key] = {
                'day': day,
                'time': time_range,
                'name': shift_name,
                'tasks': defaultdict(list)
            }

        task_id = assign.get('task', 'General')
        shifts_map[shift_key]['tasks'][task_id].append(assign)

    sorted_shifts = sorted(shifts_map.values(), key=lambda x: (x['day'], x['time']))

    # --- 3. Tree Printing ---
    print("📅  WEEKLY SCHEDULE TREE")
    print("═" * 80)

    for shift in sorted_shifts:
        # Shift Root
        print(f"🔵 [{shift['day']}] {shift['time']} | {shift['name']}")

        tasks = shift['tasks']
        task_keys = list(tasks.keys())

        for t_idx, task_key in enumerate(task_keys):
            workers = tasks[task_key]
            is_last_task = (t_idx == len(task_keys) - 1)
            task_connector = "└──" if is_last_task else "├──"
            task_pipe = "    " if is_last_task else "│   "

            # --- Calculate Combined Task Requirements Title ---
            all_roles_in_task = []
            for w in workers:
                raw = w.get('role_details', '')
                clean = raw.replace('[', '').replace(']', '').replace("'", "").replace('"', '')
                if clean: all_roles_in_task.append(clean)

            display_title = task_key
            # If it's a generated task name, show the combined skills instead
            if ("Task_" in task_key or "General" in task_key) and all_roles_in_task:
                display_title = " + ".join(sorted(list(set(all_roles_in_task))))

            print(f"{task_connector} 📂 {display_title}")

            # --- Print Workers ---
            for w_idx, w in enumerate(workers):
                is_last_worker = (w_idx == len(workers) - 1)
                worker_connector = "└──" if is_last_worker else "├──"

                worker_name = w.get('worker_name', 'Unknown')
                score = w.get('score', 0)
                score_fmt = f"(+{score})" if score > 0 else f"({score})" if score < 0 else ""

                # Extract Specific Skill for this Worker
                raw_role = w.get('role_details', '')
                # Cleaning: ['Cook: 5'] -> Cook: 5
                role_clean = raw_role.replace('[', '').replace(']', '').replace("'", "").replace('"', '')

                # Only display the specific skill if it exists
                skill_display = f"🔧 {role_clean}" if role_clean else ""

                print(f"{task_pipe} {worker_connector} 👤 {worker_name:<15} {score_fmt:<6} {skill_display}")

        print("")

    # --- 4. Violations ---
    violations = result.get("violations", {})
    if violations:
        print("═" * 80)
        print("⚠️  VIOLATIONS:")
        for rule, v_list in violations.items():
            print(f"   🔸 {rule}: {len(v_list)} occurrences")

    print("═" * 80)


if __name__ == "__main__":
    try:
        run_pipeline(INPUT_FILE)
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    except Exception as e:
        logger.critical(f"Fatal Error: {e}", exc_info=True)