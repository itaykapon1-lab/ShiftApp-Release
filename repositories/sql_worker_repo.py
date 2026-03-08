"""SQLAlchemy Worker Repository Implementation.

Provides the concrete implementation of IWorkerRepository using SQLAlchemy.
Bridges the gap between the relational database and the domain Worker objects.

DATE NORMALIZATION:
    Availability windows are always anchored to the Canonical Epoch Week
    (Jan 1-7, 2024) to prevent "Date Drift" bugs.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from repositories.base import BaseRepository
from repositories.interfaces import IWorkerRepository
from data.models import WorkerModel, ShiftModel
from domain.worker_model import Worker
from domain.time_utils import TimeWindow
from app.utils.date_normalization import (
    CANONICAL_ANCHOR_DATES,
    DAY_NAME_TO_WEEKDAY,
    normalize_to_canonical_week,
    parse_time_range_string,
)
from app.core.constants import (
    MAX_HOURS_PER_WEEK_DEFAULT,
    WORKER_PREFERENCE_REWARD,
    WORKER_PREFERENCE_PENALTY,
)

logger = logging.getLogger(__name__)


def _parse_availability_to_domain(
    availability: Any,
    worker_id: str,
    strict: bool = False,
) -> Tuple[List[Tuple[datetime, datetime]], Dict[TimeWindow, int]]:
    """Parses a raw availability value into (windows, preferences) for the Worker domain model.

    Handles both legacy list format and the current dict format.  Recognises the
    ``*`` (HIGH preference) and ``!`` (LOW preference) suffix conventions used by
    the Excel parser and strips them from the ``timeRange`` string before parsing.

    Args:
        availability: Either a list of ``{"start": "...", "end": "..."}`` dicts
            (legacy) or a dict in the format
            ``{"MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}, ...}``.
        worker_id: Worker identifier used only for log messages.
        strict: When ``True``, re-raise ``ValueError``/``KeyError`` on any
            unparseable entry instead of logging-and-continuing.  Pass ``True``
            on the API create-path so callers receive a proper error; leave
            ``False`` (the default) when hydrating existing DB records.

    Returns:
        Tuple of (windows, preferences) where ``windows`` is a list of
        (start_dt, end_dt) pairs and ``preferences`` maps TimeWindow → score.

    Raises:
        ValueError: If ``strict=True`` and any entry cannot be parsed.
    """
    windows: List[Tuple[datetime, datetime]] = []
    preferences: Dict[TimeWindow, int] = {}

    # Case A: Legacy List Format (from old Excel imports)
    # stored as: [{"start": "...", "end": "..."}, ...]
    if isinstance(availability, list):
        for item in availability:
            try:
                start_dt_raw = datetime.fromisoformat(item["start"])
                end_dt_raw = datetime.fromisoformat(item["end"])
                start_dt = normalize_to_canonical_week(start_dt_raw)
                end_dt = normalize_to_canonical_week(end_dt_raw)
                windows.append((start_dt, end_dt))
            except (ValueError, KeyError) as e:
                if strict:
                    raise ValueError(
                        f"Invalid legacy availability entry for worker '{worker_id}': {e}"
                    ) from e
                logger.warning(f"Skipping invalid availability window for worker {worker_id}: {e}")

    # Case B: New Dict Format (from Frontend / New Excel Logic)
    # stored as: {"MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}}
    elif isinstance(availability, dict):
        logger.debug("Using Canonical Epoch Week for availability (Jan 1-7, 2024)")
        for day_str, day_data in availability.items():
            try:
                if isinstance(day_data, str):
                    raw_range = day_data
                    preference = "NEUTRAL"
                elif isinstance(day_data, dict):
                    raw_range = day_data.get("timeRange", "08:00-16:00")
                    preference = day_data.get("preference", "NEUTRAL")
                else:
                    continue

                # Strip Excel-style suffix markers (* = HIGH, ! = LOW) that may
                # appear on raw strings before passing to the strict time-range parser.
                if isinstance(raw_range, str) and raw_range.endswith("*"):
                    raw_range = raw_range[:-1]
                    if preference == "NEUTRAL":
                        preference = "HIGH"
                elif isinstance(raw_range, str) and raw_range.endswith("!"):
                    raw_range = raw_range[:-1]
                    if preference == "NEUTRAL":
                        preference = "LOW"

                start_hour, start_min, end_hour, end_min = parse_time_range_string(raw_range)

                weekday = DAY_NAME_TO_WEEKDAY.get(day_str.upper())
                if weekday is None:
                    msg = f"Unknown day name '{day_str}' for worker '{worker_id}'"
                    if strict:
                        raise ValueError(msg)
                    logger.warning(msg + ", skipping")
                    continue

                target_date = CANONICAL_ANCHOR_DATES[weekday]
                start_dt = datetime.combine(target_date, datetime.min.time()).replace(
                    hour=start_hour, minute=start_min
                )
                end_dt = datetime.combine(target_date, datetime.min.time()).replace(
                    hour=end_hour, minute=end_min
                )

                # Handle overnight shifts (end time earlier than start time on same day)
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)

                windows.append((start_dt, end_dt))

                window = TimeWindow(start_dt, end_dt)
                if preference == "HIGH":
                    preferences[window] = WORKER_PREFERENCE_REWARD
                elif preference == "LOW":
                    preferences[window] = WORKER_PREFERENCE_PENALTY

            except (ValueError, KeyError, TypeError) as e:
                if strict:
                    raise ValueError(
                        f"Cannot parse availability for day '{day_str}' "
                        f"of worker '{worker_id}': {e}"
                    ) from e
                logger.warning(f"Failed to parse availability for day '{day_str}': {e}")

    return windows, preferences


class SQLWorkerRepository(BaseRepository[WorkerModel], IWorkerRepository):
    """Repository for managing Worker entities in a SQL database.

    Handles the persistence of Worker objects, including the serialization of
    their skills (with levels) and availability into a JSON 'attributes' column.
    """

    def __init__(self, session: Session, session_id: str):
        """Initializes the repository.

        Args:
            session: The active SQLAlchemy database session.
            session_id: The unique ID of the current user context.
        """
        super().__init__(session, WorkerModel, session_id)
        self._anchor_date: Optional[datetime] = None

    def _get_anchor_date(self) -> datetime:
        """Gets the dynamic anchor date for availability generation.

        Finds the earliest shift start_time in the current session to align
        worker availability with the actual schedule timeframe.

        Returns:
            datetime: The earliest shift date, or current date if no shifts exist.
        """
        if self._anchor_date is not None:
            return self._anchor_date

        try:
            earliest_shift = (
                self.session.query(ShiftModel)
                .filter(ShiftModel.session_id == self.session_id)
                .order_by(ShiftModel.start_time.asc())
                .first()
            )

            if earliest_shift and earliest_shift.start_time:
                if isinstance(earliest_shift.start_time, str):
                    anchor = datetime.fromisoformat(earliest_shift.start_time)
                else:
                    anchor = earliest_shift.start_time
                self._anchor_date = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
                logger.info(f"Dynamic Anchor Date: {self._anchor_date.date()} (from earliest shift)")
            else:
                self._anchor_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                logger.warning(
                    f"No shifts found, using current date as anchor: {self._anchor_date.date()}"
                )
        except Exception as e:
            logger.error(f"Error fetching anchor date: {e}")
            self._anchor_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        return self._anchor_date

    def _to_domain(self, model: WorkerModel) -> Worker:
        """Converts a DB WorkerModel to a domain Worker object.

        Args:
            model: The database row instance.

        Returns:
            Worker: The domain object ready for processing.
        """
        attrs: Dict[str, Any] = model.attributes or {}

        wage = attrs.get("wage", 0.0)
        min_hours = attrs.get("min_hours", 0)
        max_hours = attrs.get("max_hours", MAX_HOURS_PER_WEEK_DEFAULT)

        worker = Worker(
            name=model.name,
            worker_id=model.worker_id,
            wage=float(wage) if wage is not None else 0.0,
            min_hours=int(min_hours) if min_hours is not None else 0,
            max_hours=int(max_hours) if max_hours is not None else MAX_HOURS_PER_WEEK_DEFAULT,
        )

        # Hydrate Skills
        skills_data = attrs.get("skills", {})
        if isinstance(skills_data, dict):
            for skill_name, level in skills_data.items():
                try:
                    level_int = int(level)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Invalid skill level '{level}' for '{skill_name}', defaulting to 1"
                    )
                    level_int = 1

                if hasattr(worker, "set_skill_level"):
                    worker.set_skill_level(skill_name, level_int)
                else:
                    worker.add_skill(skill_name)
        elif isinstance(skills_data, list):
            for skill_name in skills_data:
                if hasattr(worker, "add_skill"):
                    worker.add_skill(skill_name)

        # Hydrate Availability using the shared parser
        availability_data = attrs.get("availability", [])
        windows, preferences = _parse_availability_to_domain(availability_data, model.worker_id)

        for start_dt, end_dt in windows:
            worker.add_availability(start_dt, end_dt)
        for window, score in preferences.items():
            worker.add_preference(window, score)

        return worker

    def _to_model(self, worker: Worker) -> WorkerModel:
        """Converts a domain Worker to a DB WorkerModel for persistence.

        Args:
            worker: The domain object to save.

        Returns:
            WorkerModel: The SQLAlchemy model instance.
        """
        skills_payload: Any = {}
        if isinstance(worker.skills, dict):
            for skill_name, level in worker.skills.items():
                try:
                    skills_payload[skill_name] = int(level)
                except (ValueError, TypeError):
                    skills_payload[skill_name] = 1
        else:
            skills_payload = list(worker.skills)

        # Always convert availability from domain TimeWindows to the dict format.
        # The _raw_availability_data monkey-patch has been removed; round-trip fidelity
        # is guaranteed by _convert_availability_to_dict_format().
        availability_payload = self._convert_availability_to_dict_format(
            worker.availability,
            worker.preferences,
        )

        attributes = {
            "skills": skills_payload,
            "availability": availability_payload,
            "wage": worker.wage,
            "min_hours": worker.min_hours,
            "max_hours": worker.max_hours,
        }

        return WorkerModel(
            worker_id=worker.worker_id,
            name=worker.name,
            attributes=attributes,
            session_id=self.session_id,
        )

    def _convert_availability_to_dict_format(
        self,
        availability_list: List[TimeWindow],
        preferences_dict: Dict[TimeWindow, int],
    ) -> Dict[str, Any]:
        """Converts a list of TimeWindow objects to the canonical dict format.

        Used when saving data from Excel or internal logic to ensure consistency
        in the database.

        Args:
            availability_list: List of availability TimeWindow objects.
            preferences_dict: Mapping of TimeWindow to preference score.

        Returns:
            Dict in the format ``{"MON": {"timeRange": "...", "preference": "..."}}``.
        """
        weekday_to_day = {
            0: "MON", 1: "TUE", 2: "WED", 3: "THU",
            4: "FRI", 5: "SAT", 6: "SUN",
        }

        # Pre-build O(1) preference lookup: (weekday, hour, minute) → label string.
        # Including the weekday prevents false matches when two days share the
        # same start time.  This replaces the previous O(n*m) nested-loop lookup.
        pref_lookup: Dict[tuple, str] = {}
        for pref_window, score in preferences_dict.items():
            key = (
                pref_window.start.weekday(),
                pref_window.start.hour,
                pref_window.start.minute,
            )
            if score >= WORKER_PREFERENCE_REWARD:
                pref_lookup[key] = "HIGH"
            elif score <= -50:
                pref_lookup[key] = "LOW"
            else:
                pref_lookup.setdefault(key, "NEUTRAL")

        result: Dict[str, Any] = {}

        for tw in availability_list:
            day_name = weekday_to_day.get(tw.start.weekday(), "MON")
            time_range = f"{tw.start.strftime('%H:%M')}-{tw.end.strftime('%H:%M')}"
            preference = pref_lookup.get(
                (tw.start.weekday(), tw.start.hour, tw.start.minute), "NEUTRAL"
            )

            if day_name in result:
                # Multiple windows on the same day: warn and keep the first entry
                # (the DB format is single-window-per-day; extra windows are logged).
                logger.warning(
                    f"Duplicate availability window for day '{day_name}' — "
                    f"keeping first entry, discarding '{time_range}'."
                )
                continue

            result[day_name] = {"timeRange": time_range, "preference": preference}

        return result

    # --- Interface Implementation ---

    def get_all(self) -> List[Worker]:
        """Retrieves all workers associated with the current session.

        Returns:
            List[Worker]: A list of domain objects.
        """
        db_models = super().get_all()
        return [self._to_domain(m) for m in db_models]

    def get_by_id(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a single worker by their ID.

        Args:
            worker_id: The worker's unique identifier.

        Returns:
            Optional[Worker]: The domain object if found, else None.
        """
        db_model = super().get_by_id(worker_id)
        if db_model:
            return self._to_domain(db_model)
        return None

    def add(self, worker: Worker) -> None:
        """Stages a worker for persistence (Upsert).

        Args:
            worker: The domain object to save.
        """
        db_model = self._to_model(worker)
        db_model.session_id = self.session_id
        self.session.merge(db_model)
        self.session.flush()

    def upsert_by_name(self, worker: Worker) -> Worker:
        """Insert or update a worker by name within the current session.

        Uses NAME as the natural key for upsert operations (not worker_id).
        Essential for Excel imports where the same worker name should update
        existing data rather than create duplicates.

        Args:
            worker: The Worker domain object to upsert.

        Returns:
            Worker: The upserted worker domain object.
        """
        existing = (
            self.session.query(WorkerModel)
            .filter(
                WorkerModel.session_id == self.session_id,
                WorkerModel.name == worker.name,
            )
            .first()
        )

        if existing:
            logger.info(
                f"UPSERT: Updating existing worker '{worker.name}' (ID: {existing.worker_id})"
            )
            new_model = self._to_model(worker)
            existing.attributes = new_model.attributes
            self.session.flush()
            return self._to_domain(existing)
        else:
            logger.info(
                f"UPSERT: Creating new worker '{worker.name}' (ID: {worker.worker_id})"
            )
            self.add(worker)
            return worker

    def delete(self, worker_id: str) -> None:
        """Deletes a worker by ID.

        Args:
            worker_id: The ID of the worker to delete.
        """
        super().delete(worker_id)

    def create_from_schema(self, schema: Any) -> Worker:
        """Creates and persists a worker from an API schema/payload.

        Args:
            schema: A Pydantic schema or dict-like object with worker data.

        Returns:
            Worker: The created domain object.
        """
        if hasattr(schema, "dict"):
            data = schema.dict()
        elif hasattr(schema, "model_dump"):
            data = schema.model_dump()
        else:
            data = dict(schema)

        attrs = data.get("attributes", {})

        worker = Worker(
            name=data.get("name", ""),
            worker_id=data.get("worker_id", ""),
            wage=attrs.get("wage", 0.0),
            min_hours=attrs.get("min_hours", 0),
            max_hours=attrs.get("max_hours", MAX_HOURS_PER_WEEK_DEFAULT),
        )

        skills_data = attrs.get("skills", {})
        if isinstance(skills_data, dict):
            for skill_name, level in skills_data.items():
                worker.set_skill_level(skill_name, int(level))

        # Parse availability using the shared helper (strict=True: API callers get a
        # clear ValueError instead of silent data loss on malformed entries).
        avail_data = attrs.get("availability", {})
        windows, preferences = _parse_availability_to_domain(
            avail_data, worker.worker_id, strict=True
        )

        for start_dt, end_dt in windows:
            worker.add_availability(start_dt, end_dt)
        for window, score in preferences.items():
            worker.add_preference(window, score)

        self.add(worker)
        return worker
