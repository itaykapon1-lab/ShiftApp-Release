"""Workbook Validator — Pre-import validation for Excel workbooks.

Extracted from services/excel/importer.py (ExcelImporter).
All validation logic, constants, and comments are preserved exactly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Optional, List, Dict, Tuple

import pandas as pd

if TYPE_CHECKING:
    from services.excel_service import ImportValidationResult


def _get_validation_result_class() -> type[ImportValidationResult]:
    """Lazy import to avoid circular dependency at module level."""
    from services.excel_service import ImportValidationResult
    return ImportValidationResult


class WorkbookValidator:
    """Validates Excel workbook structure and data before import.

    Performs pre-validation checks on Workers, Shifts, and Constraints sheets.
    Collects errors (blocking) and warnings (non-blocking) into an
    ImportValidationResult. Auto-corrects recoverable issues (duplicate IDs,
    malformed task strings, invalid strictness values) in-place on the
    DataFrames.
    """

    # Fallback task string used when an uploaded shift has a malformed/unparseable
    # Tasks cell.  "#1: [] x 1" means "option #1: one worker, no skill requirement".
    SAFE_DEFAULT_TASK_STRING = "#1: [] x 1"

    # Regex matching a single valid task requirement bracket, e.g.:
    #   "[Cook:5, Waiter:3] x 2"  or  "[] x 1"
    # Used by is_valid_tasks_string() to verify the entire cell is well-formed.
    TASK_REQUIREMENT_RE = re.compile(r"\[(?:[^\[\]:]+:\d+(?:,\s*[^\[\]:]+:\d+)*)?\]\s*x\s*\d+")

    def find_column(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """Find a column matching one of the candidate names (case-insensitive).

        Users name columns inconsistently ("Worker ID", "WorkerID", "Worker_ID"),
        so we accept any of the candidate variants and return the actual column
        name from the DataFrame for subsequent access.

        Args:
            df: The DataFrame whose columns are searched.
            candidates: Column name variants to try, in priority order.

        Returns:
            The actual DataFrame column name matching one of the candidates,
            or None if no match is found.
        """
        # Build a lower-cased lookup from the DataFrame's actual column names.
        df_cols_lower = {col.lower(): col for col in df.columns}
        for candidate in candidates:
            if candidate.lower() in df_cols_lower:
                return df_cols_lower[candidate.lower()]
        return None

    def is_valid_tasks_string(self, raw_tasks: str) -> bool:
        """Return True only if the entire string is composed of valid task grammar.

        Strips all recognised requirement brackets and known separators
        (``#N:``, ``|``, ``OR``, ``+``).  If anything remains, the cell
        contains garbage and should be auto-corrected.

        Args:
            raw_tasks: The raw string from the Excel Tasks cell.

        Returns:
            True if the string consists entirely of valid task syntax.
        """
        stripped = raw_tasks.strip()
        if not stripped:
            return False
        # Remove all valid [Skill:Level] x Count / [] x Count patterns
        residual = self.TASK_REQUIREMENT_RE.sub('', stripped)
        # Remove known grammar tokens between requirements
        residual = re.sub(r'#\d+\s*:', '', residual)
        residual = re.sub(r'\|', '', residual)
        residual = re.sub(r'\bOR\b', '', residual)
        residual = re.sub(r'\+', '', residual)
        return residual.strip() == ''

    def validate(
        self, xls: pd.ExcelFile
    ) -> Tuple[ImportValidationResult, bool, Dict[str, pd.DataFrame]]:
        """Pre-validate Excel data before importing.

        Reads all sheets from the workbook, validates each in turn, and
        returns both the validation results and the (potentially corrected)
        DataFrames.

        Args:
            xls: An open pandas ExcelFile to validate.

        Returns:
            A 3-tuple of:
            - ImportValidationResult with all errors/warnings found.
            - bool indicating whether any auto-corrections were applied.
            - dict of sheet_name -> DataFrame (potentially corrected).
        """
        ImportValidationResult = _get_validation_result_class()
        result = ImportValidationResult()
        corrections_applied = False

        # Read all sheets into DataFrames upfront — avoids re-reading the file
        # multiple times during per-sheet validation.
        sheet_frames = {
            sheet_name: pd.read_excel(xls, sheet_name)
            for sheet_name in xls.sheet_names
        }

        # --- Workers sheet (REQUIRED) ---
        workers_df = sheet_frames.get('Workers')
        if workers_df is not None:
            corrections_applied = self._validate_workers_sheet(workers_df, result) or corrections_applied
        else:
            result.add_error("Workers", None, None, "Missing required 'Workers' sheet.")

        # --- Shifts sheet (REQUIRED) ---
        shifts_df = sheet_frames.get('Shifts')
        if shifts_df is not None:
            corrections_applied = self._validate_shifts_sheet(shifts_df, result) or corrections_applied
        else:
            result.add_error("Shifts", None, None, "Missing required 'Shifts' sheet.")

        # --- Constraints sheet (OPTIONAL) ---
        # Missing is OK; present-but-invalid triggers warnings.
        constraints_df = sheet_frames.get('Constraints')
        if constraints_df is not None:
            corrections_applied = self._validate_constraints_sheet(constraints_df, result) or corrections_applied

        return result, corrections_applied, sheet_frames

    def _generate_unique_worker_id(self, base_id: str, seen_ids: set[str]) -> str:
        """Generate a de-duplicated worker ID by appending _dupN suffixes.

        Called when the same Worker ID appears on multiple rows.  Incrementally
        tries _dup1, _dup2, etc. until a unique ID is found.

        Args:
            base_id: The original duplicate worker ID.
            seen_ids: Set of all IDs encountered so far in this import.

        Returns:
            A unique ID in the form ``{base_id}_dupN``.
        """
        suffix = 1
        candidate = f"{base_id}_dup{suffix}"
        while candidate in seen_ids:
            suffix += 1
            candidate = f"{base_id}_dup{suffix}"
        return candidate

    def _validate_workers_sheet(self, df: pd.DataFrame, result: ImportValidationResult) -> bool:
        """Validate the Workers sheet.

        Checks: required columns exist, no empty IDs/names, no duplicate IDs,
        numeric fields are valid and non-negative, MinHours <= MaxHours.

        COLUMN NAME CONVENTIONS:
        Standard format:  "Worker ID", "Name", "Min Hours", "Max Hours", "Wage", "Skills"
        Legacy variants:  "ID"/"WorkerID"/"Worker_ID", "Worker Name"/"WorkerName",
                          "MinHours"/"Min_Hours", "MaxHours"/"Max_Hours"
        All lookups are case-insensitive via find_column().

        Args:
            df: Workers sheet DataFrame (may be mutated for auto-corrections).
            result: Accumulator for errors and warnings.

        Returns:
            True if any auto-corrections were applied to the DataFrame.
        """
        # Accept multiple column naming conventions (case-insensitive).
        id_col = self.find_column(df, ['ID', 'Worker ID', 'WorkerID', 'Worker_ID'])
        name_col = self.find_column(df, ['Name', 'Worker Name', 'WorkerName'])
        corrections_applied = False

        # If essential columns are missing, we can't validate rows at all.
        missing_required = False
        if not id_col:
            result.add_error("Workers", None, None, "Missing required column: ID (or 'Worker ID')")
            missing_required = True
        if not name_col:
            result.add_error("Workers", None, None, "Missing required column: Name")
            missing_required = True

        if missing_required:
            return corrections_applied

        # Track seen IDs to detect duplicates within the same upload.
        seen_ids: set[str] = set()

        for idx, row in df.iterrows():
            # Convert pandas 0-based index to Excel-visible row number
            # (Excel is 1-indexed, plus 1 for the header row).
            excel_row = idx + 2

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

            # Validate numeric fields — must be non-negative numbers.
            # Each tuple: (list of column name variants, display name for errors).
            numeric_fields = [
                (['Wage'], 'Wage'),
                (['MinHours', 'Min Hours', 'Min_Hours'], 'MinHours'),
                (['MaxHours', 'Max Hours', 'Max_Hours'], 'MaxHours'),
            ]
            for candidates, display_name in numeric_fields:
                col = self.find_column(df, candidates)
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
            min_col = self.find_column(df, ['MinHours', 'Min Hours', 'Min_Hours'])
            max_col = self.find_column(df, ['MaxHours', 'Max Hours', 'Max_Hours'])
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

    def _validate_shifts_sheet(self, df: pd.DataFrame, result: ImportValidationResult) -> bool:
        """Validate the Shifts sheet.

        Checks: required columns exist, valid day names, non-empty shift names,
        well-formed task strings, valid time formats, and end > start.

        COLUMN NAME CONVENTIONS:
        Standard format:  "Day", "Shift Name", "Start Time", "End Time", "Tasks"
        Legacy variants:  "ShiftName"/"Shift_Name"/"Name",
                          "Start"/"StartTime"/"Start_Time", "End"/"EndTime"/"End_Time"

        TIME FORMAT:
        Standard:   "HH:MM" (00-23 range), e.g., "08:00", "16:00"
        Overnight:  "+24h notation", e.g., "30:00" = 06:00 next day
                    Used by state exporter for overnight shifts to avoid ambiguity.

        Args:
            df: Shifts sheet DataFrame (may be mutated for auto-corrections).
            result: Accumulator for errors and warnings.

        Returns:
            True if any auto-corrections were applied to the DataFrame.
        """
        day_col = self.find_column(df, ['Day'])
        name_col = self.find_column(df, ['Shift Name', 'ShiftName', 'Shift_Name', 'Name'])
        tasks_col = self.find_column(df, ['Tasks'])
        corrections_applied = False

        if not day_col:
            result.add_error("Shifts", None, None, "Missing required column: Day")
            return corrections_applied
        if not name_col:
            result.add_error("Shifts", None, None, "Missing required column: Shift Name")
            return corrections_applied

        # The set of accepted day names (Title Case).  Unrecognized days produce
        # a warning but don't block the import — the parser may still handle them.
        valid_days = {'Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'}

        for idx, row in df.iterrows():
            excel_row = idx + 2  # Pandas 0-index → Excel 1-index + header

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

            # Validate task grammar and auto-correct malformed cells.
            # A malformed task cell (e.g., "just text" instead of "[Cook:5] x 2")
            # would cause the parser to crash, so we replace it with a safe default.
            if tasks_col:
                raw_tasks = row.get(tasks_col)
                if not pd.isna(raw_tasks):
                    tasks_text = str(raw_tasks).strip()
                    if tasks_text and not self.is_valid_tasks_string(tasks_text):
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
                col = self.find_column(df, candidates)
                if col:
                    val = row.get(col)
                    if not pd.isna(val) and val:
                        # Basic time validation - allow datetime or HH:MM format
                        if isinstance(val, str):
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
            start_col = self.find_column(df, ['Start', 'Start Time', 'StartTime', 'Start_Time'])
            end_col = self.find_column(df, ['End', 'End Time', 'EndTime', 'End_Time'])
            if start_col and end_col:
                sv = row.get(start_col)
                ev = row.get(end_col)
                if isinstance(sv, str) and isinstance(ev, str):
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

    def _validate_constraints_sheet(self, df: pd.DataFrame, result: ImportValidationResult) -> bool:
        """Validate the Constraints sheet.

        Checks: recognized constraint types, valid strictness values (HARD/SOFT).
        Unknown types and invalid strictness produce warnings, not errors, because
        the constraint mapper will silently skip unrecognized entries.

        CONSTRAINT TYPE ALIASES (case-insensitive):
        Standard:  "Mutual Exclusion"    | Legacy: "mutualexclusion", "mutual_exclusion", "ban"
        Standard:  "Co-Location"         | Legacy: "colocation", "co_location", "pair"
        Standard:  "Preference"          | Legacy: "prefer", "prefers"
        Standard:  "Max Hours"           | Legacy: "maxhours", "max_hours", "max hours per week"
        Standard:  "Min Hours"           | Legacy: "minhours", "min_hours", "min hours per week"
        Standard:  "Avoid Consecutive Shifts" | Legacy: "avoid_consecutive_shifts"
        Standard:  "Worker Preferences"  | Legacy: "worker_preferences"
        Standard:  "Task Option Priority"| Legacy: "task_option_priority", "option priority"

        STRICTNESS COLUMN:
        Standard values: "HARD", "SOFT" (case-insensitive)
        Legacy/invalid:  Auto-corrected to "HARD" (safer default) with warning.

        Args:
            df: Constraints sheet DataFrame (may be mutated for auto-corrections).
            result: Accumulator for errors and warnings.

        Returns:
            True if any auto-corrections were applied to the DataFrame.
        """
        if df.empty:
            return False  # Empty constraints sheet is OK — defaults will be used

        corrections_applied = False
        strictness_col = self.find_column(df, ['Strictness'])

        for idx, row in df.iterrows():
            excel_row = idx + 2

            # Validate Type — check against the full set of recognized aliases.
            c_type = row.get('Type', '')
            if pd.isna(c_type) or str(c_type).strip() == '':
                result.add_warning("Constraints", excel_row, "Type", "Constraint type is empty.")
            else:
                # All known constraint type aliases (case-insensitive).
                # Each canonical type has multiple accepted spellings for UX flexibility.
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

            # Validate Strictness — must be "HARD" or "SOFT".
            # Invalid values are auto-corrected to "HARD" (the safer default).
            strictness = row.get(strictness_col, '') if strictness_col else ''
            if not pd.isna(strictness) and str(strictness).strip():
                strictness_text = str(strictness).strip()
                if strictness_text.upper() not in {'HARD', 'SOFT'}:
                    if strictness_col:
                        df.at[idx, strictness_col] = "HARD"  # Auto-correct to safe default
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
