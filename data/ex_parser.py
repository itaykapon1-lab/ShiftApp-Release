"""
Excel Parser Module.

This module is responsible ONLY for parsing the Excel file and populating
the provided repositories. It acts as an ETL (Extract, Transform, Load) component.

DATE NORMALIZATION:
    All dates are normalized to the Canonical Epoch Week (Jan 1-7, 2024) to
    prevent "Date Drift" bugs. See app/utils/date_normalization.py for details.
"""
import logging
import re
import pandas as pd
from datetime import datetime, timedelta, time
from typing import List, Dict, Any, Optional

# Domain Imports
from domain.worker_model import Worker
from domain.shift_model import Shift, TimeWindow
from domain.task_model import Task, TaskOption
from repositories.interfaces import IWorkerRepository, IShiftRepository
from solver.constraints.registry import ConstraintRegistry
from solver.constraints.base import ConstraintType
from solver.constraints.dynamic import MutualExclusionConstraint, CoLocationConstraint
from solver.constraints.static_soft import WorkerPreferencesConstraint

# Canonical Week Date Normalization
from app.utils.date_normalization import (
    CANONICAL_ANCHOR_DATES,
    DAY_NAME_TO_WEEKDAY,
)

# Configuration
PREF_SCORE_BONUS = 10
PREF_SCORE_PENALTY = -10
DEFAULT_SKILL_LEVEL = 5

logger = logging.getLogger(__name__)

class ExcelParser:
    """
    Parses a scheduling Excel file and populates the given repositories.
    """

    def __init__(self,
                 worker_repo: IWorkerRepository,
                 shift_repo: IShiftRepository):
        """
        Args:
            worker_repo: The repository where parsed workers will be stored.
            shift_repo: The repository where parsed shifts will be stored.
        """
        self.worker_repo = worker_repo
        self.shift_repo = shift_repo

        # Internal state for parsing context (dates, constraints)
        self.start_date: Optional[datetime] = None
        self._raw_constraints: List[Dict] = []
        # Non-fatal warnings collected during parsing (availability failures,
        # empty sheets, etc.).  Callers should read this after load_from_file().
        self._warnings: List[str] = []

    def load_from_file(self, file_path: str, start_date: Optional[datetime] = None) -> None:
        """
        Main entry point. Reads the file and populates the repositories.

        CANONICAL WEEK ENFORCEMENT: The start_date parameter is ignored.
        All dates are normalized to the Canonical Epoch Week (Jan 1-7, 2024)
        to prevent Date Drift bugs.
        """
        self.file_path = file_path
        # Always use Canonical Sunday, ignore any provided start_date
        self.start_date = self._get_canonical_sunday()
        self._raw_constraints = []  # Reset constraints
        self._warnings = []  # Reset warnings
        logger.info(f"Using Canonical Epoch Week for import (start: {self.start_date.date()})")

        try:
            logger.info(f"Parsing data from: {self.file_path}")
            xls = pd.ExcelFile(self.file_path)

            # 1. Parse & Save Workers
            if 'Workers' in xls.sheet_names:
                df_workers = pd.read_excel(xls, 'Workers')
                self._process_workers(df_workers)
            else:
                raise ValueError("Missing 'Workers' sheet.")

            # 2. Parse & Save Shifts
            if 'Shifts' in xls.sheet_names:
                df_shifts = pd.read_excel(xls, 'Shifts')
                self._process_shifts(df_shifts)
            else:
                raise ValueError("Missing 'Shifts' sheet.")

            # 3. Parse Constraints (Stored internally to build Registry later)
            if 'Constraints' in xls.sheet_names:
                self._parse_raw_constraints(pd.read_excel(xls, 'Constraints'))

            logger.info("Parsing complete. Data loaded into repositories.")

        except Exception as e:
            logger.error(f"Parsing error: {e}", exc_info=True)
            raise

    def get_constraint_registry(self) -> ConstraintRegistry:
        """Builds and returns the constraint registry based on parsed data."""
        registry = ConstraintRegistry()
        registry.add_core_constraints()
        registry.register(WorkerPreferencesConstraint())

        for row in self._raw_constraints:
            ctype = row.get('Type', '').strip()
            strict = ConstraintType.HARD if row.get('Strictness', 'Hard').lower() == 'hard' else ConstraintType.SOFT
            subj = row.get('Subject', '').strip()
            trgt = row.get('Target', '').strip()

            if ctype == 'Mutual Exclusion' and subj and trgt:
                registry.register(MutualExclusionConstraint(subj, trgt, strict))
            elif ctype == 'Co-Location' and subj and trgt:
                registry.register(CoLocationConstraint(subj, trgt, strict))

        return registry

    # --- Internal Parsing Logic ---

    def _get_canonical_sunday(self) -> datetime:
        """Returns the Canonical Epoch Week Sunday (2024-01-07).

        CANONICAL WEEK ENFORCEMENT: Instead of using dynamic dates based on
        today's date, we always use the fixed Canonical Epoch Week to ensure
        all dates align regardless of when the import occurs.

        Returns:
            datetime: Sunday of the Canonical Epoch Week (2024-01-07)
        """
        # Sunday is weekday 6 in Python
        return datetime.combine(CANONICAL_ANCHOR_DATES[6], datetime.min.time())

    def _process_workers(self, df: pd.DataFrame):
        days_map = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

        if df.empty:
            self._warnings.append(
                "The Workers sheet contains no data rows. "
                "No workers were imported."
            )
            return

        for idx, row in df.iterrows():
            excel_row = idx + 2  # 1-indexed + header row offset
            try:
                w_id = str(row['Worker ID']).strip()
                if not w_id or w_id.lower() == 'nan': continue

                wage = 0.0
                if pd.notna(row.get('Wage')):
                    try: wage = float(row['Wage'])
                    except ValueError: pass

                worker = Worker(
                    name=str(row['Name']).strip(),
                    worker_id=w_id,
                    wage=wage,
                    min_hours=int(row.get('Min Hours', 0)),
                    max_hours=int(row.get('Max Hours', 40))
                )

                # Skills
                skills_str = str(row.get('Skills', ''))
                if skills_str.lower() != 'nan':
                    for part in skills_str.split(','):
                        self._parse_single_skill(worker, part)

                # Availability — collect warnings for any cells that fail to parse
                for day_idx, day_name in enumerate(days_map):
                    if day_name in df.columns:
                        raw_val = str(row[day_name])
                        parsed_ok = self._parse_availability_cell(worker, raw_val, day_idx)
                        if not parsed_ok and raw_val.upper() not in ('OFF', 'NAN', '', 'NONE'):
                            self._warnings.append(
                                f"Worker '{worker.name}' (row {excel_row}) has an invalid "
                                f"{day_name} availability format '{raw_val}'. "
                                f"That day's availability was defaulted to empty."
                            )

                # --- STORE IN REPO (using upsert_by_name for non-destructive import) ---
                if hasattr(self.worker_repo, 'upsert_by_name'):
                    self.worker_repo.upsert_by_name(worker)
                else:
                    self.worker_repo.add(worker)

            except Exception as e:
                logger.warning(f"Error parsing worker: {e}")

    def _process_shifts(self, df: pd.DataFrame):
        """Process shifts from Excel and normalize to Canonical Epoch Week."""
        for _, row in df.iterrows():
            try:
                day_name = self._normalize_text(row['Day'])

                # Get Python weekday from day name using canonical mapping
                weekday = DAY_NAME_TO_WEEKDAY.get(day_name.upper()[:3])
                if weekday is None:
                    logger.warning(f"Unknown day name: {day_name}, skipping shift")
                    continue

                # Use canonical anchor date for this weekday
                base_date = datetime.combine(CANONICAL_ANCHOR_DATES[weekday], datetime.min.time())
                start_dt = self._combine_dt(base_date, str(row['Start Time']))
                end_dt = self._combine_dt(base_date, str(row['End Time']))

                # end_dt <= start_dt is a FATAL error caught by pre-validation
                # in services/excel/importer.py before the parser ever runs.
                # If somehow reached here (e.g., direct parser use in tests),
                # skip the shift rather than silently corrupting the time window.
                if end_dt <= start_dt:
                    logger.warning(
                        f"Shift '{row.get('Shift Name', 'unknown')}': end time {end_dt.time()} "
                        f"is not after start time {start_dt.time()}. Skipping."
                    )
                    continue

                shift = Shift(str(row['Shift Name']), TimeWindow(start_dt, end_dt))
                logger.info(f"sift: {shift.name} and {shift.time_window}")

                raw_task = str(row['Tasks'])
                if raw_task.lower() != 'nan':
                    task_segments = [seg.strip() for seg in raw_task.split('|') if seg.strip()]
                    for seg_idx, segment in enumerate(task_segments):
                        task_container = Task(f"Task_{shift.shift_id}_{seg_idx}")
                        self._parse_complex_task_string(task_container, segment)
                        if task_container.options:
                            shift.add_task(task_container)

                # --- STORE IN REPO (using upsert_by_name for non-destructive import) ---
                if hasattr(self.shift_repo, 'upsert_by_name'):
                    self.shift_repo.upsert_by_name(shift)
                else:
                    self.shift_repo.add(shift)

            except Exception as e:
                logger.warning(f"Error parsing shift: {e}")

    def _parse_single_skill(self, worker: Worker, raw_skill: str):
        # (Same logic as before)
        raw_skill = raw_skill.strip()
        if not raw_skill: return
        name, level = raw_skill, DEFAULT_SKILL_LEVEL
        if ':' in raw_skill:
            parts = raw_skill.split(':')
            name = parts[0]
            try: level = int(parts[1])
            except ValueError: pass
        worker.set_skill_level(self._normalize_text(name), level)

    def _parse_availability_cell(self, worker: Worker, value: str, day_offset: int) -> bool:
        """Parse availability cell and normalize to Canonical Epoch Week.

        Args:
            worker: Worker object to add availability to.
            value: Cell value (e.g., "08:00-16:00", "OFF", "09:00-17:00*").
            day_offset: 0=Sunday, 1=Monday, ..., 6=Saturday (Excel column order).

        Returns:
            True if the cell was parsed successfully or intentionally empty
            (OFF/NAN/blank).  False if parsing failed — the caller should add
            a warning to self._warnings.
        """
        if value.upper() in ['OFF', 'NAN', '', 'NONE']:
            return True  # Intentionally absent — not a parse failure
        score, clean_value = 0, value
        if '*' in value: score, clean_value = PREF_SCORE_BONUS, value.replace('*', '')
        elif '!' in value: score, clean_value = PREF_SCORE_PENALTY, value.replace('!', '')

        try:
            start_str, end_str = clean_value.strip().split('-')

            # Convert Excel day offset (0=Sunday) to Python weekday (0=Monday)
            # Sunday(offset=0) -> weekday=6, Monday(offset=1) -> weekday=0, etc.
            python_weekday = (day_offset - 1) % 7 if day_offset > 0 else 6

            # Use canonical anchor date for this weekday
            base_date = datetime.combine(CANONICAL_ANCHOR_DATES[python_weekday], datetime.min.time())
            start_dt = self._combine_dt(base_date, start_str)
            end_dt = self._combine_dt(base_date, end_str)
            if end_dt <= start_dt: end_dt += timedelta(days=1)

            window = TimeWindow(start_dt, end_dt)
            worker.add_availability(window.start, window.end)
            if score != 0: worker.add_preference(window, score)
            return True
        except Exception as e:
            logger.debug(f"Could not parse availability '{value}': {e}")
            return False

    def _parse_complex_task_string(self, task: Task, task_str: str) -> None:
        """Parses a task string into TaskOption objects on the given Task.

        Supports three syntaxes:
        1. **Priority mode:** ``#1: [Chef:5] x 1 #2: [Cook:3] x 1``
        2. **Legacy OR mode:** ``[Chef:5] x 1 OR [Cook:3] x 1``
        3. **Single option:** ``[Chef:5] x 1 + [Waiter:3] x 2``

        Args:
            task: The Task container to populate with parsed options.
            task_str: The raw string from the Excel Tasks cell.
        """
        stripped = task_str.strip()
        if not stripped:
            return

        # Detect priority syntax: contains #<digit>: prefix
        if re.search(r'#\d+\s*:', stripped):
            self._parse_priority_syntax(task, stripped)
        elif 'OR' in stripped:
            self._parse_legacy_or_syntax(task, stripped)
        else:
            # Single option
            option = self._parse_single_option(stripped)
            if option and option.requirements:
                task.add_option(option)

    def _parse_priority_syntax(self, task: Task, task_str: str) -> None:
        """Parses ``#X: requirements`` priority syntax.

        Args:
            task: The Task container to populate.
            task_str: String containing ``#X:`` prefixed options.
        """
        # Split on #<digit>: boundaries using lookahead
        segments = re.split(r'(?=#\d+\s*:)', task_str)
        has_priority_1 = False

        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue

            # Extract priority and body
            m = re.match(r'#(\d+)\s*:\s*(.*)', segment, re.DOTALL)
            if not m:
                continue

            raw_priority = int(m.group(1))
            body = m.group(2).strip()

            # Clamp to valid range 1-5
            if raw_priority < 1:
                self._warnings.append(
                    f"Task option priority #{raw_priority} is below 1; clamped to #1."
                )
                raw_priority = 1
            elif raw_priority > 5:
                self._warnings.append(
                    f"Task option priority #{raw_priority} is above 5; clamped to #5."
                )
                raw_priority = 5

            if raw_priority == 1:
                has_priority_1 = True

            option = self._parse_single_option(body, priority=raw_priority)
            if option and option.requirements:
                task.add_option(option)

        if not has_priority_1 and task.options:
            self._warnings.append(
                f"Task '{task.name}' uses priority syntax but has no #1 option. "
                "The solver will penalize all options."
            )

    def _parse_legacy_or_syntax(self, task: Task, task_str: str) -> None:
        """Parses legacy ``OR``-separated options, all with priority 1.

        Emits a deprecation warning suggesting ``#X:`` syntax.

        Args:
            task: The Task container to populate.
            task_str: String containing ``OR`` separators.
        """
        parts = task_str.split('OR')
        for part in parts:
            option = self._parse_single_option(part.strip())
            if option and option.requirements:
                task.add_option(option)

        if len(task.options) > 1:
            self._warnings.append(
                f"Task '{task.name}' uses legacy 'OR' syntax. "
                "Consider using '#1: ... #2: ...' for priority control."
            )

    def _parse_single_option(
        self, option_str: str, priority: int = 1
    ) -> Optional[TaskOption]:
        """Parses a single option string into a TaskOption.

        Handles ``+``-separated simultaneous requirements and the
        ``[Skill:Level] x Count`` pattern.

        Args:
            option_str: Raw option body (e.g. ``[Chef:5] x 1 + [Cook:3] x 2``).
            priority: Priority rank for this option (1-5). Default 1.

        Returns:
            A populated TaskOption, or None if no requirements were found.
        """
        if not option_str.strip():
            return None

        task_option = TaskOption(priority=priority)
        reqs = option_str.split('+')
        for req_str in reqs:
            match = re.search(r"\[(.*?)\]\s*x\s*(\d+)", req_str)
            if match:
                content_str, count = match.group(1).strip(), int(match.group(2))
                required_skills: Dict[str, int] = {}
                if content_str:
                    for item in content_str.split(','):
                        item = item.strip()
                        if ':' in item:
                            s_name, s_lvl = item.split(':')
                            required_skills[self._normalize_text(s_name)] = int(s_lvl)
                        else:
                            required_skills[self._normalize_text(item)] = 1
                task_option.add_requirement(count, required_skills)

        return task_option if task_option.requirements else None

    def _parse_raw_constraints(self, df: pd.DataFrame):
        for _, row in df.iterrows():
            self._raw_constraints.append(row.to_dict())

    def _normalize_text(self, text: Any) -> str:
        return str(text).strip().title() if isinstance(text, str) else str(text)

    def _combine_dt(self, date_obj: datetime, time_val: Any) -> datetime:
        """Combine a date with a time value, handling the +24h overnight notation.

        The state exporter writes overnight shift end times in +24h notation
        (e.g. 06:00 next day → "30:00") to avoid ambiguity.  This method
        converts total_hours >= 24 into the correct date + timedelta.

        Args:
            date_obj: The base date (canonical epoch weekday date).
            time_val: Either a "HH:MM" string (hours may exceed 23 for overnight
                shifts), a ``datetime.time`` object, or a ``datetime`` object.

        Returns:
            A ``datetime`` combining the base date with the resolved time,
            advanced by any whole days implied by hours >= 24.
        """
        if isinstance(time_val, str):
            try:
                parts = time_val.strip().split(':')
                total_hours = int(parts[0])
                minutes = int(parts[1])
                extra_days = total_hours // 24
                hour = total_hours % 24
                base = datetime.combine(date_obj.date(), time(hour, minutes))
                return base + timedelta(days=extra_days)
            except Exception:
                return datetime.combine(date_obj.date(), time(0, 0))
        else:
            t = time_val if isinstance(time_val, time) else time_val.time()
            return datetime.combine(date_obj.date(), t)