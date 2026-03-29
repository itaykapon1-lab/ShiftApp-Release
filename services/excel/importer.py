"""Excel Importer — Handles workbook correction persistence and validation delegation.

Validation logic has been extracted to WorkbookValidator. This class retains
file I/O (corrected workbook persistence) and delegates all validation calls
to the validator, preserving the proxy chain used by ExcelService and tests.
"""

import logging
from typing import Dict, Any, Optional, List

import pandas as pd
from sqlalchemy.orm import Session

# Repositories
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository

# Validation logic extracted to its own module
from services.excel.workbook_validator import WorkbookValidator

# Configure logger
logger = logging.getLogger(__name__)


class ExcelImporter:
    # Preserve class constants for backward compatibility — delegated from validator.
    SAFE_DEFAULT_TASK_STRING = WorkbookValidator.SAFE_DEFAULT_TASK_STRING
    TASK_REQUIREMENT_RE = WorkbookValidator.TASK_REQUIREMENT_RE

    def __init__(self, db: Session, session_id: str,
                 worker_repo: SQLWorkerRepository,
                 shift_repo: SQLShiftRepository):
        self.db = db
        self.session_id = session_id
        self.worker_repo = worker_repo
        self.shift_repo = shift_repo
        self._validator = WorkbookValidator()

    # ------------------------------------------------------------------
    # Delegation stubs — preserve the proxy chain:
    # test → ExcelService._find_column() → ExcelImporter._find_column()
    #      → WorkbookValidator.find_column()
    # ------------------------------------------------------------------

    def _find_column(self, df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        return self._validator.find_column(df, candidates)

    def _is_valid_tasks_string(self, raw_tasks: str) -> bool:
        return self._validator.is_valid_tasks_string(raw_tasks)

    def _validate_workers_sheet(self, df: pd.DataFrame, result) -> bool:
        return self._validator._validate_workers_sheet(df, result)

    def _validate_shifts_sheet(self, df: pd.DataFrame, result) -> bool:
        return self._validator._validate_shifts_sheet(df, result)

    def _validate_constraints_sheet(self, df: pd.DataFrame, result) -> bool:
        return self._validator._validate_constraints_sheet(df, result)

    def _validate_excel_data(self, xls: pd.ExcelFile) -> tuple[Any, Dict[str, pd.DataFrame]]:
        """Pre-validate Excel data before importing.

        Returns the validation result alongside the (potentially auto-corrected)
        sheet DataFrames so the caller can pass them directly to the parser
        without re-reading the file from disk.

        Args:
            xls: An open pandas ExcelFile to validate.

        Returns:
            A 2-tuple of:
            - ImportValidationResult with all errors/warnings found.
              (Return type component is ``Any`` to avoid circular import at
              runtime; the actual type is
              ``services.excel_service.ImportValidationResult``.)
            - Dict of sheet_name -> DataFrame (corrected in-memory if needed).
        """
        result, corrections_applied, sheet_frames = self._validator.validate(xls)

        # Auto-corrections (duplicate IDs, malformed tasks, invalid strictness)
        # are applied in-place on the DataFrames by the validator.  The corrected
        # frames are returned directly to the caller — no need to write back to
        # disk since the parser receives these frames via load_from_frames().

        return result, sheet_frames
