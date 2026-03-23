"""Excel Importer — Handles workbook correction persistence and validation delegation.

Validation logic has been extracted to WorkbookValidator. This class retains
file I/O (corrected workbook persistence) and delegates all validation calls
to the validator, preserving the proxy chain used by ExcelService and tests.
"""

import logging
import os
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

    def _validate_excel_data(self, xls: pd.ExcelFile) -> Any:
        """Pre-validate Excel data before importing.

        Args:
            xls: An open pandas ExcelFile to validate.

        Returns:
            ImportValidationResult with all errors/warnings found.
            (Return type is ``Any`` to avoid circular import at runtime;
            the actual type is ``services.excel_service.ImportValidationResult``.)
        """
        result, corrections_applied, sheet_frames = self._validator.validate(xls)

        # If any auto-corrections were applied (e.g., duplicate ID fix, malformed
        # task string default), persist the corrected DataFrames back to the temp
        # file so the parser reads the fixed values.
        if corrections_applied:
            self._persist_corrected_workbook(xls, sheet_frames)

        return result

    def _persist_corrected_workbook(self, xls: pd.ExcelFile, sheets: Dict[str, pd.DataFrame]) -> None:
        """Persist in-memory sheet corrections back to the source workbook.

        After auto-corrections (duplicate IDs, malformed tasks, invalid strictness),
        the corrected DataFrames must be written back to the temp file so that the
        downstream ExcelParser reads the fixed values, not the originals.
        """
        source = getattr(xls, "io", None)
        if not isinstance(source, (str, os.PathLike)):
            return  # Cannot write back to non-file sources (e.g., BytesIO)

        # Close the ExcelFile handle before overwriting the temp file.
        if hasattr(xls, "close"):
            try:
                xls.close()
            except Exception as e:
                logger.debug("Failed to close ExcelFile handle: %s", e)

        # Overwrite the temp file with corrected DataFrames.
        with pd.ExcelWriter(source, engine="openpyxl", mode="w") as writer:
            for sheet_name, df in sheets.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
