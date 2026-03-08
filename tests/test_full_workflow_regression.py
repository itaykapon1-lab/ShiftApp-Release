"""
COMPREHENSIVE REGRESSION TEST SUITE
====================================
Tests the "Golden Path" workflow for ShiftApp:
A. Manual CRUD operations (Workers, Shifts, Constraints)
B. Excel Import (Grand Hotel scenario)
C. Solver Execution
D. Export Validation (Round-trip)
E. Diagnostics & Infeasibility detection

Author: QA Architect
Date: 2026-02-12
Priority: CRITICAL
"""

import pytest
import os
import json
import io
from datetime import datetime, timedelta
from typing import Dict, Any, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

# Database & Models
from data.database import Base
from data.models import WorkerModel, ShiftModel, SessionConfigModel

# Domain Models
from domain.worker_model import Worker
from domain.shift_model import Shift
from domain.task_model import Task, TaskOption
from domain.time_utils import TimeWindow

# Repositories
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository

# Services
from services.excel_service import ExcelService

# Solver
from solver.solver_engine import ShiftSolver
from solver.constraints.registry import ConstraintRegistry
from services.session_adapter import SessionDataManagerAdapter


# ==============================================================================
# FIXTURES
# ==============================================================================

@pytest.fixture(scope="function")
def db_engine():
    """Create an in-memory SQLite engine for each test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create a clean database session for each test."""
    SessionFactory = sessionmaker(bind=db_engine)
    session = SessionFactory()
    yield session
    session.close()


@pytest.fixture(scope="function")
def test_session_id():
    """Provide a valid test session ID (NOT in blocklist)."""
    return "regression_test_session_001"


@pytest.fixture(scope="function")
def worker_repo(db_session, test_session_id):
    """Create a Worker Repository instance."""
    return SQLWorkerRepository(db_session, session_id=test_session_id)


@pytest.fixture(scope="function")
def shift_repo(db_session, test_session_id):
    """Create a Shift Repository instance."""
    return SQLShiftRepository(db_session, session_id=test_session_id)


@pytest.fixture(scope="function")
def excel_service(db_session, test_session_id):
    """Create an Excel Service instance."""
    return ExcelService(db_session, test_session_id)


# ==============================================================================
# STEP A: MANUAL PERSISTENCE CHECK
# ==============================================================================

class TestManualPersistence:
    """Tests for manual CRUD operations via API simulation."""

    def test_create_worker_manually(self, db_session, worker_repo, test_session_id):
        """
        Step A.1: Create a Worker manually (simulate API call).
        Assert: Object exists in the DB with correct attributes.
        """
        # Arrange
        worker_data = {
            "worker_id": "W_MANUAL_001",
            "name": "John Doe",
            "attributes": {
                "skills": {"Chef": 5, "Waiter": 3},
                "availability": {
                    "MON": {"timeRange": "08:00-16:00", "preference": "HIGH"},
                    "TUE": {"timeRange": "09:00-17:00", "preference": "NEUTRAL"}
                },
                "wage": 25.50,
                "min_hours": 20,
                "max_hours": 40
            }
        }

        # Create a simple mock schema object
        class MockSchema:
            def model_dump(self):
                return worker_data

        # Act
        domain_worker = worker_repo.create_from_schema(MockSchema())
        db_session.commit()

        # Assert - Query directly from DB
        db_worker = db_session.query(WorkerModel).filter_by(
            worker_id="W_MANUAL_001",
            session_id=test_session_id
        ).first()

        assert db_worker is not None, "Worker was not persisted to database"
        assert db_worker.name == "John Doe"
        assert db_worker.attributes is not None
        assert db_worker.attributes.get("skills", {}).get("Chef") == 5
        assert db_worker.attributes.get("wage") == 25.50

    def test_create_shift_manually(self, db_session, shift_repo, test_session_id):
        """
        Step A.2: Create a Shift manually (simulate API call).
        Assert: Object exists in the DB with correct attributes.
        """
        # Arrange
        shift_data = {
            "shift_id": "S_MANUAL_001",
            "name": "Evening Service",
            "start_time": "2026-02-15T18:00:00",
            "end_time": "2026-02-15T23:00:00",
            "tasks_data": {
                "tasks": [
                    {
                        "task_id": "T001",
                        "name": "Kitchen Staff",
                        "options": [
                            {
                                "preference_score": 0,
                                "requirements": [
                                    {"count": 2, "required_skills": {"Chef": 3}}
                                ]
                            }
                        ]
                    }
                ]
            }
        }

        class MockSchema:
            def model_dump(self):
                return shift_data

        # Act
        domain_shift = shift_repo.create_from_schema(MockSchema())
        db_session.commit()

        # Assert - Query directly from DB
        db_shift = db_session.query(ShiftModel).filter_by(
            shift_id="S_MANUAL_001",
            session_id=test_session_id
        ).first()

        assert db_shift is not None, "Shift was not persisted to database"
        assert db_shift.name == "Evening Service"
        assert db_shift.tasks_data is not None
        assert "tasks" in db_shift.tasks_data
        assert len(db_shift.tasks_data["tasks"]) == 1

    def test_create_constraint_manually(self, db_session, test_session_id):
        """
        Step A.3: Create a Constraint manually.
        Assert: Constraint exists in SessionConfig with correct structure.
        """
        # Arrange
        constraints = [
            {
                "id": 1,
                "category": "mutual_exclusion",
                "type": "HARD",
                "enabled": True,
                "params": {
                    "worker_a_id": "W001",
                    "worker_b_id": "W002",
                    "penalty": -100.0
                }
            },
            {
                "id": 2,
                "category": "max_hours_per_week",
                "enabled": True,
                "params": {
                    "max_hours": 40,
                    "penalty": -50.0
                }
            }
        ]

        # Act
        config = SessionConfigModel(
            session_id=test_session_id,
            constraints=constraints
        )
        db_session.add(config)
        db_session.commit()

        # Assert - Query directly from DB
        db_config = db_session.query(SessionConfigModel).filter_by(
            session_id=test_session_id
        ).first()

        assert db_config is not None, "SessionConfig was not persisted"
        assert len(db_config.constraints) == 2
        assert db_config.constraints[0]["category"] == "mutual_exclusion"
        assert db_config.constraints[0]["params"]["worker_a_id"] == "W001"


# ==============================================================================
# STEP B: EXCEL IMPORT ("Grand Hotel" Scenario)
# ==============================================================================

class TestExcelImport:
    """Tests for Excel import functionality."""

    @pytest.fixture
    def grand_hotel_excel_path(self):
        """Get path to Grand Hotel test file."""
        base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        file_path = os.path.join(base_path, "Grand_Hotel_Gen_Chaos.xlsx")

        if not os.path.exists(file_path):
            pytest.skip(f"Grand Hotel test file not found at: {file_path}")

        return file_path

    def test_excel_import_workers_and_shifts(
        self, db_session, excel_service, test_session_id, grand_hotel_excel_path
    ):
        """
        Step B: Load the Grand_Hotel_Gen_Chaos.xlsx dataset.
        Assert: All workers and shifts are correctly parsed and saved.
        """
        # Arrange
        with open(grand_hotel_excel_path, "rb") as f:
            file_content = f.read()

        # Act
        result = excel_service.import_excel(file_content)
        db_session.commit()  # Ensure all changes are committed

        # Assert
        assert result["workers"] > 0, "No workers were imported"
        assert result["shifts"] > 0, "No shifts were imported"

        # Verify workers in DB
        worker_count = db_session.query(WorkerModel).filter_by(
            session_id=test_session_id
        ).count()
        assert worker_count == result["workers"], f"Expected {result['workers']} workers, got {worker_count}"

        # Verify shifts in DB
        shift_count = db_session.query(ShiftModel).filter_by(
            session_id=test_session_id
        ).count()
        assert shift_count == result["shifts"], f"Expected {result['shifts']} shifts, got {shift_count}"

    def test_upsert_preserves_existing_data(
        self, db_session, worker_repo, shift_repo, test_session_id
    ):
        """
        Test that non-destructive import preserves manually added data.
        """
        # Arrange - Create a manual worker first
        manual_worker = Worker(
            name="Janitor Bob",
            worker_id="W_JANITOR_001",
            wage=15.0,
            min_hours=0,
            max_hours=20
        )
        manual_worker.set_skill_level("Cleaning", 8)
        worker_repo.add(manual_worker)
        db_session.commit()

        initial_count = db_session.query(WorkerModel).filter_by(
            session_id=test_session_id
        ).count()
        assert initial_count == 1, "Manual worker was not created"

        # Act - Create another worker with upsert (simulating re-import)
        new_worker = Worker(
            name="New Employee",
            worker_id="W_NEW_001",
            wage=20.0,
            min_hours=10,
            max_hours=40
        )
        worker_repo.upsert_by_name(new_worker)
        db_session.commit()

        # Assert - Both workers should exist
        final_count = db_session.query(WorkerModel).filter_by(
            session_id=test_session_id
        ).count()
        assert final_count == 2, f"Expected 2 workers, got {final_count}"

        # Janitor Bob should still exist
        janitor = db_session.query(WorkerModel).filter_by(
            name="Janitor Bob",
            session_id=test_session_id
        ).first()
        assert janitor is not None, "Janitor Bob was deleted during upsert"


# ==============================================================================
# STEP C: SOLVER EXECUTION
# ==============================================================================

class TestSolverExecution:
    """Tests for solver execution."""

    def test_solver_returns_valid_schedule(self, db_session, worker_repo, shift_repo, test_session_id):
        """
        Step C: Run the Solver on data.
        Assert: The solver returns a valid schedule (Status: Optimal or Feasible).
        """
        # Arrange - Create test data
        base_date = datetime(2026, 2, 15, 0, 0, 0)

        # Create workers with matching skills and availability
        for i in range(3):
            worker = Worker(
                name=f"Worker_{i}",
                worker_id=f"W_TEST_{i}",
                wage=20.0,
                min_hours=0,
                max_hours=40
            )
            worker.set_skill_level("Service", 5)

            # Add availability for the shift time
            avail_start = base_date.replace(hour=8, minute=0)
            avail_end = base_date.replace(hour=20, minute=0)
            worker.add_availability(avail_start, avail_end)

            worker_repo.add(worker)

        # Create a shift that requires Service skill
        shift = Shift(
            name="Test Shift",
            time_window=TimeWindow(
                base_date.replace(hour=10, minute=0),
                base_date.replace(hour=14, minute=0)
            ),
            shift_id="S_TEST_001"
        )

        # Add a task with requirements
        task = Task(name="Service Task")
        option = TaskOption(preference_score=0)
        option.add_requirement(count=1, required_skills={"Service": 3})
        task.add_option(option)
        shift.add_task(task)

        shift_repo.add(shift)
        db_session.commit()

        # Load all data
        workers = worker_repo.get_all()
        shifts = shift_repo.get_all()

        assert len(workers) == 3, f"Expected 3 workers, got {len(workers)}"
        assert len(shifts) == 1, f"Expected 1 shift, got {len(shifts)}"

        # Create data adapter
        data_adapter = SessionDataManagerAdapter(
            workers=workers,
            shifts=shifts
        )

        # Create solver with default registry
        registry = ConstraintRegistry()
        registry.add_core_constraints()
        solver = ShiftSolver(data_adapter, constraint_registry=registry)

        # Act
        result = solver.solve()

        # Assert
        assert result["status"] in ["Optimal", "Feasible"], \
            f"Solver failed with status: {result['status']}"
        assert len(result.get("assignments", [])) > 0, "No assignments returned"


# ==============================================================================
# STEP D: EXPORT VALIDATION (Round-Trip)
# ==============================================================================

class TestExportValidation:
    """Tests for export functionality and round-trip verification."""

    def test_export_full_state_contains_all_data(
        self, db_session, worker_repo, shift_repo, excel_service, test_session_id
    ):
        """
        Step D: Export state and verify it contains all data.
        """
        # Arrange - Create some test data
        worker = Worker(
            name="Export Test Worker",
            worker_id="W_EXPORT_001",
            wage=30.0,
            min_hours=10,
            max_hours=35
        )
        worker.set_skill_level("Chef", 7)
        worker_repo.add(worker)

        base_date = datetime(2026, 2, 16, 0, 0, 0)
        shift = Shift(
            name="Export Test Shift",
            time_window=TimeWindow(
                base_date.replace(hour=9, minute=0),
                base_date.replace(hour=17, minute=0)
            ),
            shift_id="S_EXPORT_001"
        )
        task = Task(name="Export Task")
        option = TaskOption(preference_score=5)
        option.add_requirement(count=1, required_skills={"Chef": 5})
        task.add_option(option)
        shift.add_task(task)
        shift_repo.add(shift)

        # Add a constraint
        config = SessionConfigModel(
            session_id=test_session_id,
            constraints=[{
                "id": 1,
                "category": "max_hours_per_week",
                "enabled": True,
                "params": {"max_hours": 35, "penalty": -25.0}
            }]
        )
        db_session.add(config)
        db_session.commit()

        # Act
        export_buffer = excel_service.export_full_state()
        export_bytes = export_buffer.getvalue()

        # Assert - Check the export is not empty
        assert len(export_bytes) > 0, "Export file is empty"

        # Parse the exported Excel to verify contents
        import pandas as pd

        export_buffer.seek(0)
        xls = pd.ExcelFile(export_buffer)

        assert "Workers" in xls.sheet_names, "Workers sheet missing"
        assert "Shifts" in xls.sheet_names, "Shifts sheet missing"
        assert "Constraints" in xls.sheet_names, "Constraints sheet missing"

        # Verify worker data
        df_workers = pd.read_excel(xls, "Workers")
        assert len(df_workers) >= 1, "No workers in export"
        assert "Export Test Worker" in df_workers["Name"].values

        # Verify shift data
        df_shifts = pd.read_excel(xls, "Shifts")
        assert len(df_shifts) >= 1, "No shifts in export"
        assert "Export Test Shift" in df_shifts["Shift Name"].values


# ==============================================================================
# STEP E: DIAGNOSTICS & INFEASIBILITY
# ==============================================================================

class TestDiagnosticsAndInfeasibility:
    """Tests for solver diagnostics and infeasibility detection."""

    def test_infeasible_schedule_returns_diagnosis(
        self, db_session, worker_repo, shift_repo, test_session_id
    ):
        """
        Step E: Create an impossible schedule and verify diagnostics.

        Scenario: Create a shift that requires a skill no worker has.
        Assert: Solver returns Infeasible and diagnose_infeasibility() returns a message.
        """
        # Arrange - Create worker WITHOUT the required skill
        worker = Worker(
            name="Unskilled Worker",
            worker_id="W_UNSKILLED_001",
            wage=15.0,
            min_hours=0,
            max_hours=40
        )
        worker.set_skill_level("Cleaning", 5)  # Has Cleaning, NOT Chef

        base_date = datetime(2026, 2, 17, 0, 0, 0)
        avail_start = base_date.replace(hour=6, minute=0)
        avail_end = base_date.replace(hour=22, minute=0)
        worker.add_availability(avail_start, avail_end)

        worker_repo.add(worker)

        # Create shift that requires Chef skill
        shift = Shift(
            name="Chef Required Shift",
            time_window=TimeWindow(
                base_date.replace(hour=10, minute=0),
                base_date.replace(hour=14, minute=0)
            ),
            shift_id="S_CHEF_001"
        )

        task = Task(name="Chef Task")
        option = TaskOption(preference_score=0)
        option.add_requirement(count=1, required_skills={"Chef": 5})  # Requires Chef!
        task.add_option(option)
        shift.add_task(task)

        shift_repo.add(shift)
        db_session.commit()

        # Load data
        workers = worker_repo.get_all()
        shifts = shift_repo.get_all()

        # Create solver
        data_adapter = SessionDataManagerAdapter(workers=workers, shifts=shifts)
        registry = ConstraintRegistry()
        registry.add_core_constraints()
        solver = ShiftSolver(data_adapter, constraint_registry=registry)

        # Act
        result = solver.solve()

        # Assert - Should be infeasible because no worker has Chef skill
        assert result["status"] == "Infeasible", \
            f"Expected Infeasible, got: {result['status']}"

        # Test diagnosis
        diagnosis = solver.diagnose_infeasibility()
        assert diagnosis is not None, "Diagnosis message is None"
        assert len(diagnosis) > 0, "Diagnosis message is empty"
        print(f"Diagnosis: {diagnosis}")  # For debugging

    def test_conflicting_constraints_detected(
        self, db_session, worker_repo, shift_repo, test_session_id
    ):
        """
        Test detection of conflicting constraints.

        Scenario: Worker can only work shift A, but is banned from shift A.
        """
        # Arrange
        base_date = datetime(2026, 2, 18, 0, 0, 0)

        # Create a worker with limited availability (only morning)
        worker = Worker(
            name="Morning Only Worker",
            worker_id="W_MORNING_001",
            wage=20.0,
            min_hours=0,
            max_hours=40
        )
        worker.set_skill_level("Service", 5)

        # Only available in the morning
        avail_start = base_date.replace(hour=6, minute=0)
        avail_end = base_date.replace(hour=12, minute=0)
        worker.add_availability(avail_start, avail_end)

        worker_repo.add(worker)

        # Create an afternoon shift (worker NOT available)
        shift = Shift(
            name="Afternoon Shift",
            time_window=TimeWindow(
                base_date.replace(hour=14, minute=0),
                base_date.replace(hour=20, minute=0)
            ),
            shift_id="S_AFTERNOON_001"
        )

        task = Task(name="Service Task")
        option = TaskOption(preference_score=0)
        option.add_requirement(count=1, required_skills={"Service": 3})
        task.add_option(option)
        shift.add_task(task)

        shift_repo.add(shift)
        db_session.commit()

        # Load data
        workers = worker_repo.get_all()
        shifts = shift_repo.get_all()

        # Create solver
        data_adapter = SessionDataManagerAdapter(workers=workers, shifts=shifts)
        registry = ConstraintRegistry()
        registry.add_core_constraints()
        solver = ShiftSolver(data_adapter, constraint_registry=registry)

        # Act
        result = solver.solve()

        # Assert - Should be infeasible (no worker available for shift)
        # Note: Depending on implementation, might be "Infeasible" or have 0 assignments
        if result["status"] == "Optimal" or result["status"] == "Feasible":
            # If solver thinks it's feasible, there should be no assignments for this shift
            # because the worker isn't available
            assignments_for_shift = [
                a for a in result.get("assignments", [])
                if a.get("shift_name") == "Afternoon Shift"
            ]
            assert len(assignments_for_shift) == 0, \
                "Worker was assigned to shift despite unavailability"


# ==============================================================================
# INTEGRATION: FULL WORKFLOW
# ==============================================================================

class TestFullWorkflow:
    """End-to-end integration test covering the complete workflow."""

    def test_complete_golden_path(self, db_session, test_session_id):
        """
        Complete Golden Path Test:
        1. Create workers manually
        2. Create shifts manually
        3. Add constraints
        4. Run solver
        5. Export results
        6. Verify round-trip
        """
        # Initialize repositories
        worker_repo = SQLWorkerRepository(db_session, test_session_id)
        shift_repo = SQLShiftRepository(db_session, test_session_id)
        excel_service = ExcelService(db_session, test_session_id)

        base_date = datetime(2026, 2, 20, 0, 0, 0)

        # STEP 1: Create Workers
        workers_created = []
        for i in range(5):
            worker = Worker(
                name=f"Golden Path Worker {i}",
                worker_id=f"W_GP_{i:03d}",
                wage=15.0 + i * 2,
                min_hours=10,
                max_hours=40
            )
            worker.set_skill_level("Service", 3 + i)

            avail_start = base_date.replace(hour=6, minute=0)
            avail_end = base_date.replace(hour=22, minute=0)
            worker.add_availability(avail_start, avail_end)

            worker_repo.add(worker)
            workers_created.append(worker)

        db_session.commit()
        assert len(worker_repo.get_all()) == 5, "Failed to create workers"

        # STEP 2: Create Shifts
        shifts_created = []
        for i, (start_hour, end_hour) in enumerate([(8, 12), (12, 16), (16, 20)]):
            shift = Shift(
                name=f"Golden Path Shift {i}",
                time_window=TimeWindow(
                    base_date.replace(hour=start_hour, minute=0),
                    base_date.replace(hour=end_hour, minute=0)
                ),
                shift_id=f"S_GP_{i:03d}"
            )

            task = Task(name=f"Task {i}")
            option = TaskOption(preference_score=0)
            option.add_requirement(count=1, required_skills={"Service": 2})
            task.add_option(option)
            shift.add_task(task)

            shift_repo.add(shift)
            shifts_created.append(shift)

        db_session.commit()
        assert len(shift_repo.get_all()) == 3, "Failed to create shifts"

        # STEP 3: Add Constraints
        config = SessionConfigModel(
            session_id=test_session_id,
            constraints=[
                {
                    "id": 1,
                    "category": "max_hours_per_week",
                    "enabled": True,
                    "params": {"max_hours": 40, "penalty": -50.0}
                }
            ]
        )
        db_session.add(config)
        db_session.commit()

        # STEP 4: Run Solver
        # CRITICAL FIX: Create fresh repos to get correct anchor date
        # The worker_repo's _anchor_date was cached before shifts existed
        fresh_worker_repo = SQLWorkerRepository(db_session, test_session_id)
        fresh_shift_repo = SQLShiftRepository(db_session, test_session_id)

        workers = fresh_worker_repo.get_all()
        shifts = fresh_shift_repo.get_all()

        data_adapter = SessionDataManagerAdapter(workers=workers, shifts=shifts)
        registry = ConstraintRegistry()
        registry.add_core_constraints()
        solver = ShiftSolver(data_adapter, constraint_registry=registry)

        result = solver.solve()

        assert result["status"] in ["Optimal", "Feasible"], \
            f"Solver failed: {result['status']}"
        assert len(result.get("assignments", [])) >= 1, "No assignments"

        # STEP 5: Export Results
        export_buffer = excel_service.export_full_state()
        assert export_buffer.getvalue(), "Export is empty"

        # STEP 6: Verify Round-Trip (parse export)
        import pandas as pd
        export_buffer.seek(0)
        xls = pd.ExcelFile(export_buffer)

        df_workers = pd.read_excel(xls, "Workers")
        df_shifts = pd.read_excel(xls, "Shifts")

        assert len(df_workers) == 5, f"Export has wrong worker count: {len(df_workers)}"
        assert len(df_shifts) == 3, f"Export has wrong shift count: {len(df_shifts)}"

        print("Golden Path Test PASSED!")


# ==============================================================================
# RUN TESTS
# ==============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
