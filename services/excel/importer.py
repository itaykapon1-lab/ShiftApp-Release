"""
Excel Importer — Handles parsing, validation, and worker/shift ingestion.

Extracted from services/excel_service.py.
All logic, variables, magic numbers, and comments are preserved exactly.
"""

import logging
import os
import tempfile
import re
from typing import Dict, Any, Optional, List

import pandas as pd
from sqlalchemy.orm import Session

# Database Models
from data.models import WorkerModel, ShiftModel

# Repositories
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository

# NOTE: ExcelParser is NOT imported at module level. It is imported
# lazily inside import_excel() so that test patches on
# "services.excel_service.ExcelParser" continue to work correctly.

# Configure logger
logger = logging.getLogger(__name__)


class ExcelImporter:
    SAFE_DEFAULT_TASK_STRING = "#1: [General:1] x 1"
    TASK_REQUIREMENT_RE = re.compile(r"\[[^\[\]:]+:\d+\]\s*x\s*\d+")

    def __init__(self, db: Session, session_id: str,
                 worker_repo: SQLWorkerRepository,
                 shift_repo: SQLShiftRepository):
        self.db = db
        self.session_id = session_id
        self.worker_repo = worker_repo
        self.shift_repo = shift_repo

    def _find_column(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """Find a column matching one of the candidate names (case-insensitive)."""
        df_cols_lower = {col.lower(): col for col in df.columns}
        for candidate in candidates:
            if candidate.lower() in df_cols_lower:
                return df_cols_lower[candidate.lower()]
        return None

    def _validate_excel_data(self, xls: pd.ExcelFile):
        """Pre-validate Excel data before importing.

        Returns an ImportValidationResult with all errors/warnings found.
        """
        from services.excel_service import ImportValidationResult

        result = ImportValidationResult()
        corrections_applied = False
        sheet_frames = {
            sheet_name: pd.read_excel(xls, sheet_name)
            for sheet_name in xls.sheet_names
        }

        # Validate Workers sheet
        workers_df = sheet_frames.get('Workers')
        if workers_df is not None:
            corrections_applied = self._validate_workers_sheet(workers_df, result) or corrections_applied
        else:
            result.add_error("Workers", None, None, "Missing required 'Workers' sheet.")

        # Validate Shifts sheet
        shifts_df = sheet_frames.get('Shifts')
        if shifts_df is not None:
            corrections_applied = self._validate_shifts_sheet(shifts_df, result) or corrections_applied
        else:
            result.add_error("Shifts", None, None, "Missing required 'Shifts' sheet.")

        # Validate Constraints sheet (optional but validate if present)
        constraints_df = sheet_frames.get('Constraints')
        if constraints_df is not None:
            corrections_applied = self._validate_constraints_sheet(constraints_df, result) or corrections_applied

        if corrections_applied:
            self._persist_corrected_workbook(xls, sheet_frames)

        return result

    def _persist_corrected_workbook(self, xls: pd.ExcelFile, sheets: Dict[str, pd.DataFrame]) -> None:
        """Persist in-memory sheet corrections back to the source workbook."""
        source = getattr(xls, "io", None)
        if not isinstance(source, (str, os.PathLike)):
            return

        if hasattr(xls, "close"):
            try:
                xls.close()
            except Exception:
                pass

        with pd.ExcelWriter(source, engine="openpyxl", mode="w") as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

    def _generate_unique_worker_id(self, base_id: str, seen_ids: set[str]) -> str:
        suffix = 1
        candidate = f"{base_id}_dup{suffix}"
        while candidate in seen_ids:
            suffix += 1
            candidate = f"{base_id}_dup{suffix}"
        return candidate

    def _is_valid_tasks_string(self, raw_tasks: str) -> bool:
        return bool(self.TASK_REQUIREMENT_RE.search(raw_tasks))

    def _validate_workers_sheet(self, df: pd.DataFrame, result) -> bool:
        """Validate the Workers sheet."""
        # Accept multiple column naming conventions
        id_col = self._find_column(df, ['ID', 'Worker ID', 'WorkerID', 'Worker_ID'])
        name_col = self._find_column(df, ['Name', 'Worker Name', 'WorkerName'])
        corrections_applied = False

        missing_required = False
        if not id_col:
            result.add_error("Workers", None, None, "Missing required column: ID (or 'Worker ID')")
            missing_required = True
        if not name_col:
            result.add_error("Workers", None, None, "Missing required column: Name")
            missing_required = True

        if missing_required:
            return corrections_applied

        seen_ids: set[str] = set()

        for idx, row in df.iterrows():
            excel_row = idx + 2  # Excel is 1-indexed, plus header row

            # Validate ID
            worker_id = row.get(id_col)
            if pd.isna(worker_id) or str(worker_id).strip() == '':
                result.add_error("Workers", excel_row, id_col, "Worker ID cannot be empty.")
            else:
                normalized_worker_id = str(worker_id).strip()
                if normalized_worker_id in seen_ids:
                    auto_generated_id = self._generate_unique_worker_id(normalized_worker_id, seen_ids)
                    df.at[idx, id_col] = auto_generated_id
                    seen_ids.add(auto_generated_id)
                    corrections_applied = True
                    result.add_warning(
                        "Workers",
                        excel_row,
                        id_col,
                        (
                            f"Duplicate ID '{normalized_worker_id}' found on row {excel_row}. "
                            f"Auto-assigned new ID '{auto_generated_id}'. Please check if constraints "
                            f"referencing the old ID need updating."
                        ),
                    )
                else:
                    seen_ids.add(normalized_worker_id)

            # Validate Name
            name = row.get(name_col)
            if pd.isna(name) or str(name).strip() == '':
                result.add_error("Workers", excel_row, name_col, "Worker name cannot be empty.")

            # Validate numeric fields (with flexible column names)
            numeric_fields = [
                (['Wage'], 'Wage'),
                (['MinHours', 'Min Hours', 'Min_Hours'], 'MinHours'),
                (['MaxHours', 'Max Hours', 'Max_Hours'], 'MaxHours'),
            ]
            for candidates, display_name in numeric_fields:
                col = self._find_column(df, candidates)
                if col:
                    val = row.get(col)
                    if not pd.isna(val):
                        try:
                            num = float(val)
                            if num < 0:
                                result.add_error("Workers", excel_row, col, f"{display_name} cannot be negative: {val}")
                        except (TypeError, ValueError):
                            result.add_error("Workers", excel_row, col, f"Invalid {display_name} value: {val}")

            # Validate MinHours <= MaxHours
            min_col = self._find_column(df, ['MinHours', 'Min Hours', 'Min_Hours'])
            max_col = self._find_column(df, ['MaxHours', 'Max Hours', 'Max_Hours'])
            if min_col and max_col:
                min_h = row.get(min_col)
                max_h = row.get(max_col)
                if not pd.isna(min_h) and not pd.isna(max_h):
                    try:
                        if float(min_h) > float(max_h):
                            result.add_error("Workers", excel_row, min_col,
                                             f"MinHours ({min_h}) cannot exceed MaxHours ({max_h})")
                    except (TypeError, ValueError):
                        pass  # Already reported

        return corrections_applied

    def _validate_shifts_sheet(self, df: pd.DataFrame, result) -> bool:
        """Validate the Shifts sheet."""
        # Accept flexible column names
        day_col = self._find_column(df, ['Day'])
        name_col = self._find_column(df, ['Shift Name', 'ShiftName', 'Shift_Name', 'Name'])
        tasks_col = self._find_column(df, ['Tasks'])
        corrections_applied = False

        if not day_col:
            result.add_error("Shifts", None, None, "Missing required column: Day")
            return corrections_applied
        if not name_col:
            result.add_error("Shifts", None, None, "Missing required column: Shift Name")
            return corrections_applied

        valid_days = {'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'}

        for idx, row in df.iterrows():
            excel_row = idx + 2

            # Validate Day
            day = row.get(day_col)
            if pd.isna(day) or str(day).strip() == '':
                result.add_error("Shifts", excel_row, day_col, "Day cannot be empty.")
            elif str(day).strip().title() not in valid_days:
                result.add_warning("Shifts", excel_row, day_col, f"Unrecognized day: '{day}'")

            # Validate Shift Name
            name = row.get(name_col)
            if pd.isna(name) or str(name).strip() == '':
                result.add_error("Shifts", excel_row, name_col, "Shift name cannot be empty.")

            # Validate tasks format and auto-default malformed cells
            if tasks_col:
                raw_tasks = row.get(tasks_col)
                if not pd.isna(raw_tasks):
                    tasks_text = str(raw_tasks).strip()
                    if tasks_text and not self._is_valid_tasks_string(tasks_text):
                        df.at[idx, tasks_col] = self.SAFE_DEFAULT_TASK_STRING
                        corrections_applied = True
                        result.add_warning(
                            "Shifts",
                            excel_row,
                            tasks_col,
                            (
                                f"Malformed task string '{tasks_text}' on row {excel_row}. "
                                f"Auto-defaulted to '{self.SAFE_DEFAULT_TASK_STRING}'."
                            ),
                        )

            # Validate time columns if present (flexible names)
            time_cols = [
                (['Start', 'Start Time', 'StartTime', 'Start_Time'], 'Start'),
                (['End', 'End Time', 'EndTime', 'End_Time'], 'End'),
            ]
            for candidates, display_name in time_cols:
                col = self._find_column(df, candidates)
                if col:
                    val = row.get(col)
                    if not pd.isna(val) and val:
                        # Basic time validation - allow datetime or HH:MM format
                        if isinstance(val, str):
                            import re
                            # Accept standard HH:MM (00-23) and overnight +24h notation (e.g. "30:00").
                            # Both forms are valid; only truly unparseable values (e.g. "banana") are rejected.
                            if not re.match(r'^\d{1,3}:[0-5][0-9]$', val.strip()):
                                result.add_error("Shifts", excel_row, col,
                                    f"Invalid time format '{val}'. Expected HH:MM (e.g. '08:00') "
                                    "or overnight notation (e.g. '30:00'). Row will be rejected.")

            # Cross-field: end time must be strictly after start time (FATAL).
            # This check is intentionally strict — the parser previously silently
            # added 1 day to correct inverted windows, which caused data corruption.
            #
            # OVERNIGHT SHIFTS: The state exporter writes overnight end times in
            # +24h notation (e.g. 06:00 the next day → "30:00").  We therefore
            # accept hours > 23 in End Time and compare as total-minutes to avoid
            # Python datetime.time()'s 0-23 hour restriction.
            start_col = self._find_column(df, ['Start', 'Start Time', 'StartTime', 'Start_Time'])
            end_col = self._find_column(df, ['End', 'End Time', 'EndTime', 'End_Time'])
            if start_col and end_col:
                sv = row.get(start_col)
                ev = row.get(end_col)
                if isinstance(sv, str) and isinstance(ev, str):
                    import re
                    # Accept both same-day (00-23) and overnight (+24h) notation
                    _time_re = r'^\d{1,2}:[0-5][0-9]$'
                    if re.match(_time_re, sv.strip()) and re.match(_time_re, ev.strip()):
                        try:
                            sh, sm = map(int, sv.strip().split(':'))
                            eh, em = map(int, ev.strip().split(':'))
                            # Integer-minute comparison handles hours > 23 correctly
                            if (eh * 60 + em) <= (sh * 60 + sm):
                                shift_label = str(row.get(name_col, '')).strip()
                                shift_label = f"'{shift_label}'" if shift_label else f"at row {excel_row}"
                                result.add_error(
                                    "Shifts", excel_row, end_col,
                                    f"Shift {shift_label} has an end time ({ev}) "
                                    f"before or equal to its start time ({sv}). "
                                    f"To represent an overnight shift, use the "
                                    f"+24h notation for the end time "
                                    f"(e.g. 06:00 the next day → '30:00')."
                                )
                        except (ValueError, TypeError):
                            pass  # Malformed values already flagged above

        return corrections_applied

    def _validate_constraints_sheet(self, df: pd.DataFrame, result) -> bool:
        """Validate the Constraints sheet."""
        if df.empty:
            return False  # Empty constraints sheet is OK

        corrections_applied = False
        strictness_col = self._find_column(df, ['Strictness'])

        for idx, row in df.iterrows():
            excel_row = idx + 2

            # Validate Type
            c_type = row.get('Type', '')
            if pd.isna(c_type) or str(c_type).strip() == '':
                result.add_warning("Constraints", excel_row, "Type", "Constraint type is empty.")
            else:
                valid_types = {
                    'mutual exclusion', 'mutualexclusion', 'mutual_exclusion', 'ban',
                    'co-location', 'colocation', 'co_location', 'pair',
                    'preference', 'prefer', 'prefers',
                    'max hours', 'maxhours', 'max_hours', 'max hours per week',
                    'min hours', 'minhours', 'min_hours', 'min hours per week',
                    'avoid consecutive shifts', 'avoid_consecutive_shifts',
                    'worker preferences', 'worker_preferences',
                    'task option priority', 'task_option_priority', 'option priority',
                }
                if str(c_type).strip().lower() not in valid_types:
                    result.add_warning("Constraints", excel_row, "Type",
                                       f"Unrecognized constraint type: '{c_type}'")

            # Validate Strictness
            strictness = row.get(strictness_col, '') if strictness_col else ''
            if not pd.isna(strictness) and str(strictness).strip():
                strictness_text = str(strictness).strip()
                if strictness_text.upper() not in {'HARD', 'SOFT'}:
                    if strictness_col:
                        df.at[idx, strictness_col] = "HARD"
                    corrections_applied = True
                    result.add_warning(
                        "Constraints",
                        excel_row,
                        strictness_col or "Strictness",
                        (
                            f"Unknown strictness '{strictness_text}' on row {excel_row}. "
                            "Auto-defaulted to 'HARD'."
                        ),
                    )

        return corrections_applied

    def import_excel(self, file_content: bytes) -> Dict[str, Any]:
        """
        Orchestrates the Excel import process:
        1. Saves upload to temp file.
        2. Pre-validates the data (collects all errors).
        3. Runs the external ExcelParser.
        4. Adapts and saves constraints to the DB.

        Raises:
            ImportValidationException: If validation errors are found.
            ValueError: If a server error occurs during import.
        """
        from services.excel_service import ImportValidationException

        tmp_path: Optional[str] = None

        logger.info(f"Starting Excel import for session: {self.session_id}")

        try:
            # 1. Create a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
                tmp.write(file_content)
                tmp_path = tmp.name

            logger.debug(f"Temporary file created at: {tmp_path}")

            # 2. PRE-VALIDATION: Check data before attempting import
            logger.debug("Running pre-validation on Excel data")
            xls = pd.ExcelFile(tmp_path)
            validation_result = self._validate_excel_data(xls)

            # If there are critical errors, fail early with detailed report
            if validation_result.has_errors():
                logger.warning(f"Validation failed: {len(validation_result.errors)} errors found")
                raise ImportValidationException(validation_result)

            # 3. NON-DESTRUCTIVE: Skip clearing - use upsert pattern instead
            logger.debug("Using non-destructive import (upsert mode)")

            # 4. Initialize the external Parser
            # Late import: use the reference from the facade module so that
            # tests that patch "services.excel_service.ExcelParser" work.
            import services.excel_service as _svc_mod
            _ExcelParser = _svc_mod.ExcelParser

            logger.debug("Initializing ExcelParser")
            parser = _ExcelParser(
                worker_repo=self.worker_repo,
                shift_repo=self.shift_repo
            )

            # 5. Run the parser
            if hasattr(parser, 'load_from_file'):
                parser.load_from_file(tmp_path)
            elif hasattr(parser, 'parse_file'):
                parser.parse_file(tmp_path)
            elif hasattr(parser, 'parse'):
                parser.parse(tmp_path)
            elif hasattr(parser, 'load'):
                parser.load(tmp_path)
            else:
                raise NotImplementedError("ExcelParser has no recognized entry method.")

            # 6. Extract and Transform Constraints (The Adapter Step)
            logger.debug("Extracting and adapting parsed constraints")
            from services.excel.constraint_mapper import ConstraintMapper
            constraint_mapper = ConstraintMapper(self.db, self.session_id)
            constraint_errors = constraint_mapper.save_constraints(parser)

            # 7. Commit Transaction
            logger.debug("Parsing finished, committing to DB")
            self.db.commit()

            # 8. Verify Results
            worker_count = self.db.query(WorkerModel).filter(WorkerModel.session_id == self.session_id).count()
            shift_count = self.db.query(ShiftModel).filter(ShiftModel.session_id == self.session_id).count()

            result: Dict[str, Any] = {
                "workers": worker_count,
                "shifts": shift_count
            }

            # Include warnings from validation (non-blocking)
            if validation_result.warnings:
                result["warnings"] = [
                    {"sheet": w.sheet, "row": w.row, "message": w.message}
                    for w in validation_result.warnings
                ]

            # Include constraint errors in response if any occurred
            if constraint_errors:
                result["constraint_errors"] = constraint_errors

            return result

        except ImportValidationException:
            self.db.rollback()
            raise  # Re-raise validation exceptions as-is
        except Exception as e:
            logger.error(f"Import failed: {e}", exc_info=True)
            self.db.rollback()
            raise ValueError(f"Server Error during import: {str(e)}")

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _clear_session_data(self) -> None:
        """
        Clears Workers and Shifts for the session.
        NOTE: We do NOT delete SessionConfigModel here because we simply update
        its 'constraints' column in _save_constraints. This prevents ID churn.
        """
        self.db.query(ShiftModel).filter(ShiftModel.session_id == self.session_id).delete()
        self.db.query(WorkerModel).filter(WorkerModel.session_id == self.session_id).delete()
        self.db.flush()
