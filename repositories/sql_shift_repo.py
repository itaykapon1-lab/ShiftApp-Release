"""SQLAlchemy Shift Repository Implementation.

Provides the concrete implementation of IShiftRepository using SQLAlchemy.
Bridges the gap between the relational database and the domain Shift objects.

DATE NORMALIZATION:
    All datetime values are normalized to the Canonical Epoch Week
    (Jan 1-7, 2024) before persistence to prevent "Date Drift" bugs.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from repositories._session_guard import ensure_session_config_exists
from repositories.base import BaseRepository
from repositories.interfaces import IShiftRepository
from data.models import ShiftModel        # ORM model: maps to the `shifts` table
from domain.shift_model import Shift       # Pure domain dataclass (no SQLAlchemy)
from domain.time_utils import TimeWindow   # (start, end) datetime pair — canonical temporal primitive
# Shifts any datetime to the same weekday/time within the canonical epoch week (Jan 1–7, 2024)
from app.utils.date_normalization import normalize_to_canonical_week

logger = logging.getLogger(__name__)


class SQLShiftRepository(BaseRepository[ShiftModel], IShiftRepository):
    """Repository for managing Shift entities in a SQL database."""

    def __init__(self, session: Session, session_id: str):
        """Initializes the repository.

        Args:
            session: The active SQLAlchemy database session.
            session_id: The unique ID of the current user context.
        """
        super().__init__(session, ShiftModel, session_id)

    def _to_domain(self, model: ShiftModel) -> Shift:
        """Reconstructs the Shift domain object from a DB model.

        Args:
            model: The database row.

        Returns:
            Shift: The domain object.

        Raises:
            ValueError: If the model contains corrupt or unparseable time data.
        """
        try:
            start = model.start_time  # May be datetime or str depending on DB driver
            end = model.end_time

            # SQLite stores datetimes as ISO strings; PostgreSQL returns native datetimes.
            # Normalise both to Python datetime objects for the domain layer.
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            # Wrap in the canonical temporal primitive used by the solver
            window = TimeWindow(start, end)
        except (ValueError, TypeError) as e:
            # Corrupt time data in the DB is unrecoverable — raise loudly so the
            # operator can fix the offending row rather than silently propagating bad data.
            raise ValueError(
                f"Shift '{model.shift_id}' has corrupt time data in the database: {e}. "
                "This record must be corrected before it can be loaded."
            ) from e

        # Build the base domain object from relational columns
        shift = Shift(
            name=model.name,
            time_window=window,
            shift_id=model.shift_id,
        )

        # --- Hydrate Tasks ---
        # tasks_data is a JSON column storing the shift's staffing requirements
        # (Task → TaskOption → Requirement hierarchy).
        if model.tasks_data:
            try:
                tasks = self._deserialize_tasks_to_domain(model.tasks_data)
                shift.tasks = tasks
                logger.info(f"Hydrated {len(tasks)} tasks for shift {model.name}")
            except (KeyError, TypeError, ValueError) as e:
                # Graceful degradation: log the error but don't crash — shifts with
                # broken task data still need to appear in the UI for correction.
                # KeyError: missing expected key in JSON structure
                # TypeError: unexpected None/type in nested data
                # ValueError: invalid integer/string conversion
                logger.warning("Failed to hydrate tasks for shift %s: %s", model.shift_id, e)
                shift.tasks = []
        else:
            # No tasks defined — shift exists but has no staffing requirements yet
            logger.warning(f"Shift {model.name} has no tasks_data in DB")
            shift.tasks = []

        return shift

    def _deserialize_tasks_to_domain(self, tasks_data: Dict[str, Any]) -> List:
        """Deserializes tasks from JSON to domain objects.

        Args:
            tasks_data: Dictionary with structure
                ``{"tasks": [{task_id, name, options: [...]}]}``.

        Returns:
            List[Task]: List of hydrated Task domain objects.
        """
        # Deferred import to avoid circular dependencies (domain ← repo ← domain)
        from domain.task_model import Task, TaskOption, Requirement

        tasks_list = []

        # JSON structure polymorphism: the storage format evolved over time.
        # Current: {"tasks": [{...}, ...]}  — dict with "tasks" key
        # Legacy:  [{...}, ...]             — bare list of task dicts
        if isinstance(tasks_data, dict) and "tasks" in tasks_data:
            raw_tasks = tasks_data["tasks"]
        elif isinstance(tasks_data, list):
            raw_tasks = tasks_data
        else:
            logger.warning(f"Unknown tasks_data format: {type(tasks_data)}")
            return []

        # Reconstruct the 3-level domain hierarchy: Task → TaskOption → Requirement
        for task_data in raw_tasks:
            try:
                task = Task(name=task_data.get("name", "Unnamed Task"))

                if "task_id" in task_data:
                    task.task_id = task_data["task_id"]

                # Each task has multiple options (alternative staffing configurations).
                # The solver picks ONE option per task via Y variables.
                for option_data in task_data.get("options", []):
                    task_option = TaskOption(
                        preference_score=option_data.get("preference_score", 0),
                        priority=option_data.get("priority", 1),  # Lower = preferred
                    )

                    # Each option specifies one or more requirements (skill + headcount).
                    # The solver must fill ALL requirements if the option is selected.
                    for req_data in option_data.get("requirements", []):
                        requirement = Requirement(
                            count=req_data.get("count", 1),  # How many workers needed
                            required_skills=req_data.get("required_skills", {}),  # {skill: level}
                        )
                        task_option.requirements.append(requirement)

                    task.add_option(task_option)

                tasks_list.append(task)

            except (KeyError, TypeError, ValueError) as e:
                # Skip individual malformed tasks rather than failing the entire shift
                logger.warning("Error deserializing task: %s", e)
                continue

        return tasks_list

    def _to_model(self, shift: Shift) -> ShiftModel:
        """Converts a domain Shift to a DB ShiftModel.

        Args:
            shift: The domain object.

        Returns:
            ShiftModel: The SQLAlchemy model.
        """
        # Serialize the Task → TaskOption → Requirement hierarchy to JSON, or None
        # if the shift has no tasks defined yet.
        tasks_json = None
        if hasattr(shift, "tasks") and shift.tasks:
            tasks_json = self._serialize_tasks_from_domain(shift.tasks)

        return ShiftModel(
            shift_id=shift.shift_id,
            name=shift.name,
            start_time=shift.time_window.start,   # Datetime (already canonical from add())
            end_time=shift.time_window.end,
            tasks_data=tasks_json,                 # JSON blob with staffing requirements
            session_id=self.session_id,            # Multi-tenancy: stamp the tenant ID
        )

    def _serialize_tasks_from_domain(self, tasks: List) -> Dict[str, Any]:
        """Converts Task domain objects to the JSON storage structure.

        Args:
            tasks: List of Task domain objects.

        Returns:
            Dict with structure ``{"tasks": [...]}``.
        """
        # Deferred import to avoid circular dependencies
        from domain.task_model import Task, TaskOption, Requirement

        # Convert domain objects → JSON-serialisable dicts, mirroring the
        # _deserialize_tasks_to_domain() structure for round-trip fidelity.
        tasks_list = []
        for task in tasks:
            if not isinstance(task, Task):
                continue  # Skip non-Task objects that may be in the list

            options_list = []
            for option in task.options:
                if not isinstance(option, TaskOption):
                    continue

                # Serialize each requirement (skill + headcount) within the option
                reqs_list = []
                for req in option.requirements:
                    if isinstance(req, Requirement):
                        reqs_list.append(
                            {
                                "count": req.count,                       # Workers needed
                                "required_skills": req.required_skills,   # {skill: level}
                            }
                        )

                options_list.append(
                    {
                        "requirements": reqs_list,
                        # getattr with defaults: defensive against domain objects that
                        # may not have these attributes set (e.g., manually created Tasks).
                        "preference_score": getattr(option, "preference_score", 0),
                        "priority": getattr(option, "priority", 1),
                    }
                )

            tasks_list.append(
                {
                    "task_id": task.task_id,
                    "name": task.name,
                    "options": options_list,
                }
            )

        # Wrap in {"tasks": [...]} — the canonical JSON envelope expected by
        # _deserialize_tasks_to_domain() on the read path.
        return {"tasks": tasks_list}

    # --- Interface Implementation ---

    def get_all(self) -> List[Shift]:
        """Retrieves all shifts associated with the current session.

        Returns:
            List[Shift]: List of domain objects.
        """
        # super().get_all() applies session_id filtering via BaseRepository._get_base_query()
        db_models = super().get_all()
        # _to_domain() hydrates time windows and the Task→Option→Requirement hierarchy
        return [self._to_domain(m) for m in db_models]

    def get_by_id(self, shift_id: str) -> Optional[Shift]:
        """Retrieves a single shift by ID.

        Args:
            shift_id: The shift identifier.

        Returns:
            Optional[Shift]: Domain object if found, else None.
        """
        db_model = super().get_by_id(shift_id)
        if db_model:
            return self._to_domain(db_model)
        return None

    def add(self, shift: Shift) -> None:
        """Stages a shift for persistence with canonical week normalization.

        Canonical week hard-stop: start/end are normalized before persistence,
        regardless of caller path (API, service, or direct repository usage).

        Args:
            shift: The domain object to save.
        """
        # Ensure the parent session_config row exists (FK requirement).
        ensure_session_config_exists(self.session, self.session_id)

        # CANONICAL WEEK ENFORCEMENT: normalize real calendar dates to the
        # canonical epoch week (Jan 1–7, 2024) before any DB write.
        # This prevents Date Drift: schedule data must be date-independent.
        start_time = normalize_to_canonical_week(shift.time_window.start)
        end_time = normalize_to_canonical_week(shift.time_window.end)

        # Serialize the Task hierarchy to JSON (None if no tasks defined)
        tasks_json = None
        if hasattr(shift, "tasks") and shift.tasks:
            tasks_json = self._serialize_tasks_from_domain(shift.tasks)

        db_model = ShiftModel(
            shift_id=shift.shift_id,
            name=shift.name,
            start_time=start_time,         # Canonical epoch datetime
            end_time=end_time,             # Canonical epoch datetime
            tasks_data=tasks_json,         # JSON blob or None
            session_id=self.session_id,    # Multi-tenancy stamp
        )
        # merge() = upsert: INSERT if PK is new, UPDATE if PK already exists
        self.session.merge(db_model)
        # Flush synchronises to DB within the current transaction (no commit yet)
        self.session.flush()

    def upsert_by_name(self, shift: Shift) -> Shift:
        """DEPRECATED: Name is no longer a unique key. Use add() for new shifts.

        This method is retained for backward compatibility but will be removed
        in a future release. It now falls back to add() behavior.

        Args:
            shift: The Shift domain object to insert.

        Returns:
            Shift: The inserted shift domain object.
        """
        import warnings
        warnings.warn(
            "upsert_by_name() is deprecated — shift names are no longer unique. "
            "Use add().",
            DeprecationWarning,
            stacklevel=2,
        )
        self.add(shift)
        return shift

    def delete(self, shift_id: str) -> None:
        """Deletes a shift by ID.

        Args:
            shift_id: The ID of the shift to delete.
        """
        super().delete(shift_id)

    def create_from_schema(self, schema: Any) -> Shift:
        """Creates and persists a shift from an API schema/payload.

        CANONICAL WEEK ENFORCEMENT: All dates are normalized to the
        Canonical Epoch Week (Jan 1-7, 2024) to prevent Date Drift bugs.

        Args:
            schema: A Pydantic schema or dict-like object with shift data.

        Returns:
            Shift: The created domain object.

        Raises:
            ValueError: If ``start_time`` or ``end_time`` is absent or None.
        """
        # Ensure the parent session_config row exists (FK requirement).
        ensure_session_config_exists(self.session, self.session_id)

        # Pydantic v1/v2 compatibility: try .dict() then .model_dump(), fall back to dict()
        if hasattr(schema, "dict"):
            data = schema.dict()
        elif hasattr(schema, "model_dump"):
            data = schema.model_dump()
        else:
            data = dict(schema)

        # Extract raw time values — these come from the API as ISO datetime strings
        start_time_raw = data.get("start_time")
        end_time_raw = data.get("end_time")

        # Fail fast on missing required fields rather than propagating None downstream
        if start_time_raw is None:
            raise ValueError(
                "Shift 'start_time' is required and cannot be None. "
                "Provide a valid ISO datetime string."
            )
        if end_time_raw is None:
            raise ValueError(
                "Shift 'end_time' is required and cannot be None. "
                "Provide a valid ISO datetime string."
            )

        # CANONICAL WEEK ENFORCEMENT: normalize real calendar dates (e.g., 2026-05-15)
        # to the canonical epoch (2024-01-04 for Thursday) before persistence.
        start_time = normalize_to_canonical_week(start_time_raw)
        end_time = normalize_to_canonical_week(end_time_raw)

        logger.debug(f"Shift dates normalized: {start_time_raw} -> {start_time.isoformat()}")

        # Build the domain object with normalized times
        shift = Shift(
            name=data.get("name", ""),
            time_window=TimeWindow(start_time, end_time),
            shift_id=data.get("shift_id", ""),
        )

        # Build the ORM model for DB persistence
        db_model = ShiftModel(
            shift_id=shift.shift_id,
            name=shift.name,
            start_time=start_time,              # Canonical epoch datetime
            end_time=end_time,                  # Canonical epoch datetime
            tasks_data=data.get("tasks_data"),  # Optional JSON blob from the API
            session_id=self.session_id,         # Multi-tenancy stamp
        )

        # merge() = upsert: INSERT if new PK, UPDATE if existing PK.
        # Note: no flush() here — caller is expected to manage the transaction.
        self.session.merge(db_model)
        return shift
