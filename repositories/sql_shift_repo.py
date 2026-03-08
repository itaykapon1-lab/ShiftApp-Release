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

from repositories.base import BaseRepository
from repositories.interfaces import IShiftRepository
from data.models import ShiftModel
from domain.shift_model import Shift
from domain.time_utils import TimeWindow
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
            start = model.start_time
            end = model.end_time

            # Robust conversion if DB driver returns strings
            if isinstance(start, str):
                start = datetime.fromisoformat(start)
            if isinstance(end, str):
                end = datetime.fromisoformat(end)

            window = TimeWindow(start, end)
        except (ValueError, TypeError) as e:
            raise ValueError(
                f"Shift '{model.shift_id}' has corrupt time data in the database: {e}. "
                "This record must be corrected before it can be loaded."
            ) from e

        shift = Shift(
            name=model.name,
            time_window=window,
            shift_id=model.shift_id,
        )

        if model.tasks_data:
            try:
                tasks = self._deserialize_tasks_to_domain(model.tasks_data)
                shift.tasks = tasks
                logger.info(f"Hydrated {len(tasks)} tasks for shift {model.name}")
            except Exception as e:
                logger.error(f"Failed to hydrate tasks for shift {model.shift_id}: {e}")
                shift.tasks = []
        else:
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
        from domain.task_model import Task, TaskOption, Requirement

        tasks_list = []

        if isinstance(tasks_data, dict) and "tasks" in tasks_data:
            raw_tasks = tasks_data["tasks"]
        elif isinstance(tasks_data, list):
            raw_tasks = tasks_data
        else:
            logger.warning(f"Unknown tasks_data format: {type(tasks_data)}")
            return []

        for task_data in raw_tasks:
            try:
                task = Task(name=task_data.get("name", "Unnamed Task"))

                if "task_id" in task_data:
                    task.task_id = task_data["task_id"]

                for option_data in task_data.get("options", []):
                    task_option = TaskOption(
                        preference_score=option_data.get("preference_score", 0),
                        priority=option_data.get("priority", 1),
                    )

                    for req_data in option_data.get("requirements", []):
                        requirement = Requirement(
                            count=req_data.get("count", 1),
                            required_skills=req_data.get("required_skills", {}),
                        )
                        task_option.requirements.append(requirement)

                    task.add_option(task_option)

                tasks_list.append(task)

            except Exception as e:
                logger.error(f"Error deserializing task: {e}")
                continue

        return tasks_list

    def _to_model(self, shift: Shift) -> ShiftModel:
        """Converts a domain Shift to a DB ShiftModel.

        Args:
            shift: The domain object.

        Returns:
            ShiftModel: The SQLAlchemy model.
        """
        tasks_json = None
        if hasattr(shift, "tasks") and shift.tasks:
            tasks_json = self._serialize_tasks_from_domain(shift.tasks)

        return ShiftModel(
            shift_id=shift.shift_id,
            name=shift.name,
            start_time=shift.time_window.start,
            end_time=shift.time_window.end,
            tasks_data=tasks_json,
            session_id=self.session_id,
        )

    def _serialize_tasks_from_domain(self, tasks: List) -> Dict[str, Any]:
        """Converts Task domain objects to the JSON storage structure.

        Args:
            tasks: List of Task domain objects.

        Returns:
            Dict with structure ``{"tasks": [...]}``.
        """
        from domain.task_model import Task, TaskOption, Requirement

        tasks_list = []
        for task in tasks:
            if not isinstance(task, Task):
                continue

            options_list = []
            for option in task.options:
                if not isinstance(option, TaskOption):
                    continue

                reqs_list = []
                for req in option.requirements:
                    if isinstance(req, Requirement):
                        reqs_list.append(
                            {
                                "count": req.count,
                                "required_skills": req.required_skills,
                            }
                        )

                options_list.append(
                    {
                        "requirements": reqs_list,
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

        return {"tasks": tasks_list}

    # --- Interface Implementation ---

    def get_all(self) -> List[Shift]:
        """Retrieves all shifts associated with the current session.

        Returns:
            List[Shift]: List of domain objects.
        """
        db_models = super().get_all()
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
        start_time = normalize_to_canonical_week(shift.time_window.start)
        end_time = normalize_to_canonical_week(shift.time_window.end)

        tasks_json = None
        if hasattr(shift, "tasks") and shift.tasks:
            tasks_json = self._serialize_tasks_from_domain(shift.tasks)

        db_model = ShiftModel(
            shift_id=shift.shift_id,
            name=shift.name,
            start_time=start_time,
            end_time=end_time,
            tasks_data=tasks_json,
            session_id=self.session_id,
        )
        self.session.merge(db_model)
        self.session.flush()

    def upsert_by_name(self, shift: Shift) -> Shift:
        """Insert or update a shift by name within the current session.

        Uses NAME as the natural key for upsert operations (not shift_id).
        Essential for Excel imports where the same shift name should update
        existing data rather than create duplicates.

        Args:
            shift: The Shift domain object to upsert.

        Returns:
            Shift: The upserted shift domain object.
        """
        existing = (
            self.session.query(ShiftModel)
            .filter(
                ShiftModel.session_id == self.session_id,
                ShiftModel.name == shift.name,
            )
            .first()
        )

        if existing:
            logger.info(
                f"UPSERT: Updating existing shift '{shift.name}' (ID: {existing.shift_id})"
            )
            existing.start_time = normalize_to_canonical_week(shift.time_window.start)
            existing.end_time = normalize_to_canonical_week(shift.time_window.end)

            if hasattr(shift, "tasks") and shift.tasks:
                existing.tasks_data = self._serialize_tasks_from_domain(shift.tasks)

            self.session.flush()
            return self._to_domain(existing)
        else:
            logger.info(
                f"UPSERT: Creating new shift '{shift.name}' (ID: {shift.shift_id})"
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
        if hasattr(schema, "dict"):
            data = schema.dict()
        elif hasattr(schema, "model_dump"):
            data = schema.model_dump()
        else:
            data = dict(schema)

        start_time_raw = data.get("start_time")
        end_time_raw = data.get("end_time")

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

        start_time = normalize_to_canonical_week(start_time_raw)
        end_time = normalize_to_canonical_week(end_time_raw)

        logger.debug(f"Shift dates normalized: {start_time_raw} -> {start_time.isoformat()}")

        shift = Shift(
            name=data.get("name", ""),
            time_window=TimeWindow(start_time, end_time),
            shift_id=data.get("shift_id", ""),
        )

        db_model = ShiftModel(
            shift_id=shift.shift_id,
            name=shift.name,
            start_time=start_time,
            end_time=end_time,
            tasks_data=data.get("tasks_data"),
            session_id=self.session_id,
        )

        self.session.merge(db_model)
        return shift
