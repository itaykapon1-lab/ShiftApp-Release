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

from repositories._session_guard import ensure_session_config_exists

from repositories.base import BaseRepository
from repositories.interfaces import IWorkerRepository
from data.models import WorkerModel, ShiftModel
from domain.worker_model import Worker
from domain.time_utils import TimeWindow
from app.utils.date_normalization import (
    # Pre-computed date objects for Mon–Sun of the canonical epoch week (Jan 1–7, 2024)
    CANONICAL_ANCHOR_DATES,
    # Maps day abbreviations ("MON", "TUE", ...) → Python weekday ints (0–6)
    DAY_NAME_TO_WEEKDAY,
    # Shifts any datetime to the same weekday/time within the canonical epoch week
    normalize_to_canonical_week,
    # Parses "HH:MM-HH:MM" strings → (start_h, start_m, end_h, end_m) tuple
    parse_time_range_string,
)
from app.core.constants import (
    MAX_HOURS_PER_WEEK_DEFAULT,      # System-wide default cap (40 hours)
    WORKER_PREFERENCE_REWARD,        # Positive bonus for preferred shifts (+10)
    WORKER_PREFERENCE_PENALTY,       # Negative penalty for disliked shifts (-100)
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
    windows: List[Tuple[datetime, datetime]] = []    # Raw (start, end) datetime pairs
    preferences: Dict[TimeWindow, int] = {}            # TimeWindow → preference score mapping

    # Case A: Legacy List Format (from old Excel imports / early API versions)
    # stored as: [{"start": "2024-01-01T08:00", "end": "2024-01-01T16:00"}, ...]
    if isinstance(availability, list):
        for item in availability:
            try:
                # Parse ISO strings → datetime objects
                start_dt_raw = datetime.fromisoformat(item["start"])
                end_dt_raw = datetime.fromisoformat(item["end"])
                # Anchor to canonical epoch week (Jan 1–7, 2024) to prevent
                # Date Drift — real calendar dates must never reach the DB.
                start_dt = normalize_to_canonical_week(start_dt_raw)
                end_dt = normalize_to_canonical_week(end_dt_raw)
                windows.append((start_dt, end_dt))
            except (ValueError, KeyError) as e:
                # strict=True (API path): bubble up so the caller gets a clear error.
                # strict=False (DB hydration path): log and skip — don't break reads.
                if strict:
                    raise ValueError(
                        f"Invalid legacy availability entry for worker '{worker_id}': {e}"
                    ) from e
                logger.warning(f"Skipping invalid availability window for worker {worker_id}: {e}")

    # Case B: New Dict Format (from Frontend / New Excel Logic)
    # stored as: {"MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}}
    # Each key is a 3-letter day abbreviation; value is either a time-range
    # string or a dict with timeRange + preference fields.
    elif isinstance(availability, dict):
        logger.debug("Using Canonical Epoch Week for availability (Jan 1-7, 2024)")
        for day_str, day_data in availability.items():
            try:
                # Polymorphic value handling: string = time range only; dict = full entry
                if isinstance(day_data, str):
                    raw_range = day_data       # e.g., "08:00-16:00" or "08:00-16:00*"
                    preference = "NEUTRAL"     # No explicit preference in string-only format
                elif isinstance(day_data, dict):
                    raw_range = day_data.get("timeRange", "08:00-16:00")
                    preference = day_data.get("preference", "NEUTRAL")
                else:
                    continue  # Skip unrecognised value types (e.g., None, int)

                # Strip Excel-style suffix markers before time-range parsing:
                # "*" at end → worker PREFERS this shift (HIGH priority bonus)
                # "!" at end → worker AVOIDS this shift (LOW priority penalty)
                # Only override preference if it wasn't already set explicitly.
                if isinstance(raw_range, str) and raw_range.endswith("*"):
                    raw_range = raw_range[:-1]
                    if preference == "NEUTRAL":
                        preference = "HIGH"
                elif isinstance(raw_range, str) and raw_range.endswith("!"):
                    raw_range = raw_range[:-1]
                    if preference == "NEUTRAL":
                        preference = "LOW"

                # Decompose "HH:MM-HH:MM" into four integer components
                start_hour, start_min, end_hour, end_min = parse_time_range_string(raw_range)

                # Map day abbreviation ("MON", "TUE", ...) → Python weekday int (0–6)
                weekday = DAY_NAME_TO_WEEKDAY.get(day_str.upper())
                if weekday is None:
                    msg = f"Unknown day name '{day_str}' for worker '{worker_id}'"
                    if strict:
                        raise ValueError(msg)
                    logger.warning(msg + ", skipping")
                    continue

                # Look up the canonical epoch date for this weekday
                # e.g., weekday 0 (Mon) → date(2024, 1, 1), weekday 6 (Sun) → date(2024, 1, 7)
                target_date = CANONICAL_ANCHOR_DATES[weekday]
                # Build full datetime objects anchored to the canonical epoch
                start_dt = datetime.combine(target_date, datetime.min.time()).replace(
                    hour=start_hour, minute=start_min
                )
                end_dt = datetime.combine(target_date, datetime.min.time()).replace(
                    hour=end_hour, minute=end_min
                )

                # Handle overnight shifts: e.g., "22:00-06:00" → end is next day
                if end_dt <= start_dt:
                    end_dt += timedelta(days=1)

                windows.append((start_dt, end_dt))

                # Store preference scores for the solver's soft-constraint objective:
                # HIGH → positive reward (solver prefers assigning this worker here)
                # LOW → negative penalty (solver avoids assigning this worker here)
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
        # Cached anchor date for availability generation — lazily computed from
        # the earliest shift in the session on first access via _get_anchor_date().
        self._anchor_date: Optional[datetime] = None

    def _get_anchor_date(self) -> datetime:
        """Gets the dynamic anchor date for availability generation.

        Finds the earliest shift start_time in the current session to align
        worker availability with the actual schedule timeframe.

        Returns:
            datetime: The earliest shift date, or current date if no shifts exist.
        """
        # Return cached value if already computed (avoid repeated DB queries)
        if self._anchor_date is not None:
            return self._anchor_date

        try:
            # Query the earliest shift start_time in this session to align
            # worker availability windows with the actual schedule timeframe.
            # ORDER BY start_time ASC + LIMIT 1 (via .first()) is efficient.
            earliest_shift = (
                self.session.query(ShiftModel)
                .filter(ShiftModel.session_id == self.session_id)
                .order_by(ShiftModel.start_time.asc())
                .first()
            )

            if earliest_shift and earliest_shift.start_time:
                # SQLite may return strings; PostgreSQL returns native datetimes
                if isinstance(earliest_shift.start_time, str):
                    anchor = datetime.fromisoformat(earliest_shift.start_time)
                else:
                    anchor = earliest_shift.start_time
                # Zero out time components — we only need the date as the week anchor
                self._anchor_date = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
                logger.info(f"Dynamic Anchor Date: {self._anchor_date.date()} (from earliest shift)")
            else:
                # Fallback: no shifts exist yet, use today as a temporary anchor
                self._anchor_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                logger.warning(
                    f"No shifts found, using current date as anchor: {self._anchor_date.date()}"
                )
        except (ValueError, TypeError, AttributeError) as e:
            # Defensive fallback — anchor date parsing must never crash reads.
            # ValueError: malformed ISO string from SQLite
            # TypeError: unexpected None in arithmetic
            # AttributeError: missing .start_time on query result
            logger.warning("Error fetching anchor date: %s", e)
            self._anchor_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        return self._anchor_date

    def _to_domain(self, model: WorkerModel) -> Worker:
        """Converts a DB WorkerModel to a domain Worker object.

        Args:
            model: The database row instance.

        Returns:
            Worker: The domain object ready for processing.
        """
        # The `attributes` JSON column stores all non-relational worker data:
        # skills, availability, wage, min_hours, max_hours — packed into a single column.
        attrs: Dict[str, Any] = model.attributes or {}

        # Extract scalar attributes with safe defaults for missing/null values
        wage = attrs.get("wage", 0.0)
        min_hours = attrs.get("min_hours", 0)
        max_hours = attrs.get("max_hours", MAX_HOURS_PER_WEEK_DEFAULT)

        # Build the base domain object with scalar attributes
        worker = Worker(
            name=model.name,
            worker_id=model.worker_id,
            # Defensive type coercion: JSON may store numbers as strings or None
            wage=float(wage) if wage is not None else 0.0,
            min_hours=int(min_hours) if min_hours is not None else 0,
            max_hours=int(max_hours) if max_hours is not None else MAX_HOURS_PER_WEEK_DEFAULT,
        )

        # --- Hydrate Skills ---
        # Skills are stored as either {"Cook": 5, "Waiter": 3} (dict with levels)
        # or ["Cook", "Waiter"] (legacy list without levels).
        skills_data = attrs.get("skills", {})
        if isinstance(skills_data, dict):
            # Dict format: {skill_name: level} — preferred format with proficiency levels
            for skill_name, level in skills_data.items():
                try:
                    level_int = int(level)
                except (ValueError, TypeError):
                    # Graceful degradation: invalid level → minimum level 1
                    logger.warning(
                        f"Invalid skill level '{level}' for '{skill_name}', defaulting to 1"
                    )
                    level_int = 1

                # Prefer set_skill_level (sets name + level) over add_skill (name only)
                if hasattr(worker, "set_skill_level"):
                    worker.set_skill_level(skill_name, level_int)
                else:
                    worker.add_skill(skill_name)
        elif isinstance(skills_data, list):
            # Legacy list format: ["Cook", "Waiter"] — no proficiency levels
            for skill_name in skills_data:
                if hasattr(worker, "add_skill"):
                    worker.add_skill(skill_name)

        # --- Hydrate Availability ---
        # Uses the module-level _parse_availability_to_domain() which handles both
        # legacy list format and new dict format with canonical epoch normalization.
        # strict=False (default): skip unparseable entries gracefully during DB reads.
        availability_data = attrs.get("availability", [])
        windows, preferences = _parse_availability_to_domain(availability_data, model.worker_id)

        # Register each availability window on the domain object
        for start_dt, end_dt in windows:
            worker.add_availability(start_dt, end_dt)
        # Register preference scores (HIGH/LOW) that the solver uses as soft-constraint bonuses
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
        # Serialize skills: dict format preserves proficiency levels ({name: level}),
        # list format is a fallback for domain objects that store skills as a set/list.
        skills_payload: Any = {}
        if isinstance(worker.skills, dict):
            for skill_name, level in worker.skills.items():
                try:
                    skills_payload[skill_name] = int(level)
                except (ValueError, TypeError):
                    skills_payload[skill_name] = 1  # Default level on coercion failure
        else:
            skills_payload = list(worker.skills)  # Legacy: set/list → JSON array

        # Always convert availability from domain TimeWindows to the dict format.
        # The _raw_availability_data monkey-patch has been removed; round-trip fidelity
        # is guaranteed by _convert_availability_to_dict_format().
        # Output: {"MON": {"timeRange": "08:00-16:00", "preference": "HIGH"}, ...}
        availability_payload = self._convert_availability_to_dict_format(
            worker.availability,
            worker.preferences,
        )

        # Pack all non-relational fields into the JSON `attributes` column.
        # This single-column approach avoids schema migrations when adding new fields.
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
            attributes=attributes,         # JSON blob with all worker metadata
            session_id=self.session_id,    # Multi-tenancy: stamp the tenant ID
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
        # Map Python weekday() ints → 3-letter day abbreviations used as JSON keys
        weekday_to_day = {
            0: "MON", 1: "TUE", 2: "WED", 3: "THU",
            4: "FRI", 5: "SAT", 6: "SUN",
        }

        # Pre-build O(1) preference lookup: (weekday, hour, minute) → label string.
        # Including the weekday prevents false matches when two days share the
        # same start time (e.g., Monday 08:00 vs Tuesday 08:00).
        # This replaces the previous O(n*m) nested-loop lookup.
        pref_lookup: Dict[tuple, str] = {}
        for pref_window, score in preferences_dict.items():
            key = (
                pref_window.start.weekday(),
                pref_window.start.hour,
                pref_window.start.minute,
            )
            # Threshold-based classification: score >= reward → HIGH,
            # score <= -50 → LOW, otherwise NEUTRAL.
            if score >= WORKER_PREFERENCE_REWARD:
                pref_lookup[key] = "HIGH"
            elif score <= -50:
                pref_lookup[key] = "LOW"
            else:
                # setdefault: don't overwrite an existing HIGH/LOW with NEUTRAL
                pref_lookup.setdefault(key, "NEUTRAL")

        result: Dict[str, Any] = {}

        for tw in availability_list:
            day_name = weekday_to_day.get(tw.start.weekday(), "MON")
            # Format as "HH:MM-HH:MM" — the standard string representation
            time_range = f"{tw.start.strftime('%H:%M')}-{tw.end.strftime('%H:%M')}"
            # Look up the preference label for this window's (weekday, hour, minute)
            preference = pref_lookup.get(
                (tw.start.weekday(), tw.start.hour, tw.start.minute), "NEUTRAL"
            )

            if day_name in result:
                # DB format supports only one window per day — extra windows on the
                # same day are discarded with a warning (first-seen wins).
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
        # Fetch all ORM rows for this session, then convert each to a domain object.
        # The session_id filter ensures multi-tenant isolation.
        db_models = (
            self.session.query(WorkerModel)
            .filter(WorkerModel.session_id == self.session_id)
            .all()
        )
        # _to_domain() hydrates skills, availability, and preferences from JSON attrs
        return [self._to_domain(m) for m in db_models]

    def get_by_id(self, worker_id: str) -> Optional[Worker]:
        """Retrieves a single worker by their business ID within this session.

        Args:
            worker_id: The worker's business identifier (e.g. "W001").

        Returns:
            Optional[Worker]: The domain object if found, else None.
        """
        # Compound filter: session_id (tenant isolation) + worker_id (business key).
        # .first() returns None if no match — no exception on missing records.
        db_model = (
            self.session.query(WorkerModel)
            .filter(
                WorkerModel.session_id == self.session_id,
                WorkerModel.worker_id == worker_id,
            )
            .first()
        )
        if db_model:
            return self._to_domain(db_model)
        return None

    def add(self, worker: Worker) -> None:
        """Inserts or updates a worker within the current session.

        Uses an explicit ``(session_id, worker_id)`` lookup instead of
        a PK-based ``merge()`` to prevent cross-session data corruption.

        Args:
            worker: The domain object to save.
        """
        # Ensure the parent session_config row exists (FK requirement).
        ensure_session_config_exists(self.session, self.session_id)

        # Explicit (session_id + worker_id) lookup instead of PK-based merge()
        # to prevent cross-session data corruption — merge() uses PK only, which
        # could accidentally overwrite a different session's worker with the same PK.
        existing = (
            self.session.query(WorkerModel)
            .filter(
                WorkerModel.session_id == self.session_id,
                WorkerModel.worker_id == worker.worker_id,
            )
            .first()
        )
        db_model = self._to_model(worker)
        if existing:
            # UPDATE path: modify the existing row's mutable columns in-place.
            # SQLAlchemy dirty-tracking will emit an UPDATE on flush.
            existing.name = db_model.name
            existing.attributes = db_model.attributes
        else:
            # INSERT path: add a brand new row to the session
            self.session.add(db_model)
        # Flush (not commit) to synchronise the row to the DB within the current
        # transaction. The caller (typically ExcelService.import_excel) commits later.
        self.session.flush()

    def upsert_by_id(self, worker: Worker) -> Worker:
        """Insert or update a worker by worker_id within the current session.

        Uses ``worker_id`` as the identity key for upsert operations.  Two
        workers with the same display name but different IDs are treated as
        distinct individuals.

        Args:
            worker: The Worker domain object to upsert.

        Returns:
            Worker: The upserted worker domain object.
        """
        # Look up by business key (worker_id) within the current session
        existing = (
            self.session.query(WorkerModel)
            .filter(
                WorkerModel.session_id == self.session_id,
                WorkerModel.worker_id == worker.worker_id,
            )
            .first()
        )

        if existing:
            # UPDATE path: worker_id already exists in this session → update in place
            logger.info(
                f"UPSERT: Updating existing worker '{worker.name}' (ID: {existing.worker_id})"
            )
            new_model = self._to_model(worker)
            existing.name = new_model.name
            existing.attributes = new_model.attributes
            # Flush to synchronise the update within the active transaction
            self.session.flush()
            # Return a fresh domain object reflecting the DB state post-flush
            return self._to_domain(existing)
        else:
            # INSERT path: no existing row → create new worker via self.add()
            logger.info(
                f"UPSERT: Creating new worker '{worker.name}' (ID: {worker.worker_id})"
            )
            self.add(worker)
            return worker

    def delete(self, worker_id: str) -> None:
        """Deletes a worker by business ID within the current session.

        Args:
            worker_id: The worker's business identifier.
        """
        # Bulk DELETE scoped to (session_id + worker_id) — session_id prevents
        # accidentally deleting another tenant's worker with the same ID.
        self.session.query(WorkerModel).filter(
            WorkerModel.session_id == self.session_id,
            WorkerModel.worker_id == worker_id,
        # synchronize_session=False: skip identity-map sync for speed; expire_all follows.
        ).delete(synchronize_session=False)
        # Invalidate all ORM-cached instances to prevent stale reads of the deleted row
        self.session.expire_all()

    def create_from_schema(self, schema: Any) -> Worker:
        """Creates and persists a worker from an API schema/payload.

        Args:
            schema: A Pydantic schema or dict-like object with worker data.

        Returns:
            Worker: The created domain object.
        """
        # Pydantic v1/v2 compatibility: try .dict() (v1) then .model_dump() (v2),
        # fall back to dict() for plain mapping objects.
        if hasattr(schema, "dict"):
            data = schema.dict()
        elif hasattr(schema, "model_dump"):
            data = schema.model_dump()
        else:
            data = dict(schema)

        # Worker attributes (skills, availability, wage, etc.) are nested under "attributes"
        attrs = data.get("attributes", {})

        # Build the base domain object from API-provided scalar fields
        worker = Worker(
            name=data.get("name", ""),
            worker_id=data.get("worker_id", ""),
            wage=attrs.get("wage", 0.0),
            min_hours=attrs.get("min_hours", 0),
            max_hours=attrs.get("max_hours", MAX_HOURS_PER_WEEK_DEFAULT),
        )

        # Hydrate skills from the API payload (dict format with levels)
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

        # Register availability windows and preference scores on the domain object
        for start_dt, end_dt in windows:
            worker.add_availability(start_dt, end_dt)
        for window, score in preferences.items():
            worker.add_preference(window, score)

        # Persist to DB via the upsert-aware add() method, then return the domain object
        self.add(worker)
        return worker
