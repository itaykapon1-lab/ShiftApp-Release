"""
Excel Service Implementation - Adapter Layer (Facade).

This module acts as a bridge between the raw ExcelParser and the strict API domain.
It handles file uploads, session scoping, and crucially, transforms raw parser data
into schema-compliant JSON structures before saving to the database.

The ExcelService class is a Facade that delegates to specialized sub-classes:
- ExcelImporter:    Validation + import orchestration
- ExcelExporter:    Schedule-to-Excel generation
- ConstraintMapper: Constraint transformation + dedup + default logic
- StateExporter:    Full session state export (round-trip compatible)
"""

import io
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

from sqlalchemy.orm import Session

# Repositories
from repositories.sql_repo import SQLWorkerRepository, SQLShiftRepository

# The Core Logic (External Parser) — kept at module level so existing
# tests that patch "services.excel_service.ExcelParser" continue to work.
from data.ex_parser import ExcelParser  # noqa: F401

# Specialized sub-modules
from services.excel.importer import ExcelImporter
from services.excel.exporter import ExcelExporter
from services.excel.constraint_mapper import ConstraintMapper
from services.excel.state_exporter import StateExporter

# Configure logger
import logging
logger = logging.getLogger(__name__)


# --- Validation Result Data Structures ---
# These dataclasses collect errors and warnings discovered during pre-validation
# of the uploaded Excel file, BEFORE the parser runs.  This allows the API to
# return a structured error report to the frontend rather than failing mid-parse.

@dataclass
class ImportError:
    """Represents a single import error."""
    sheet: str              # Which Excel sheet the error was found in
    row: Optional[int]      # Excel row number (1-indexed + header), or None for sheet-level errors
    field: Optional[str]    # Column name where the error occurred
    message: str            # Human-readable error description
    severity: str = "error"  # "error" (blocks import) or "warning" (non-blocking)


@dataclass
class ImportValidationResult:
    """Aggregates all validation errors from an import operation."""
    errors: List[ImportError] = field(default_factory=list)     # Blocking errors — import cannot proceed
    warnings: List[ImportError] = field(default_factory=list)   # Non-blocking — import proceeds with caveats

    def add_error(self, sheet: str, row: Optional[int], field: Optional[str], message: str):
        self.errors.append(ImportError(sheet=sheet, row=row, field=field, message=message))

    def add_warning(self, sheet: str, row: Optional[int], field: Optional[str], message: str):
        self.warnings.append(ImportError(sheet=sheet, row=row, field=field, message=message, severity="warning"))

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "errors": [
                {
                    "sheet": e.sheet,
                    "row": e.row,
                    "field": e.field,
                    "message": e.message,
                }
                for e in self.errors
            ],
            "warnings": [
                {
                    "sheet": w.sheet,
                    "row": w.row,
                    "field": w.field,
                    "message": w.message,
                }
                for w in self.warnings
            ],
        }

    def format_summary(self) -> str:
        """Return a human-readable summary of errors."""
        lines = []
        if self.errors:
            lines.append(f"{len(self.errors)} validation error(s):")
            for e in self.errors[:10]:  # Limit to first 10
                loc = f"[{e.sheet}"
                if e.row:
                    loc += f", row {e.row}"
                if e.field:
                    loc += f", field '{e.field}'"
                loc += "]"
                lines.append(f"  {loc}: {e.message}")
            if len(self.errors) > 10:
                lines.append(f"  ... and {len(self.errors) - 10} more errors")
        return "\n".join(lines)


class ImportValidationException(Exception):
    """Exception raised when Excel import validation fails.

    .. deprecated::
        Use :class:`app.core.exceptions.ImportValidationError` instead.
        This class is retained for backward compatibility with existing
        tests and route handlers that import it from this module.
    """

    def __init__(self, validation_result: ImportValidationResult):
        self.validation_result = validation_result
        super().__init__(validation_result.format_summary())


class ExcelService:
    """Facade that delegates to specialized Excel sub-modules.

    Public interface and attribute layout remain identical to the
    pre-refactor monolith so that callers (API routes, tests) are
    unaffected.
    """

    def __init__(self, db: Session, session_id: str):
        self.db = db
        self.session_id = session_id
        # Session-scoped repos ensure all queries are filtered by session_id.
        self.worker_repo = SQLWorkerRepository(db, session_id)
        self.shift_repo = SQLShiftRepository(db, session_id)

        # Instantiate specialised delegates — each handles one aspect of Excel I/O.
        # The Facade pattern keeps the public API surface small while splitting
        # the 600+ lines of Excel logic into focused, testable modules.
        self._importer = ExcelImporter(db, session_id, self.worker_repo, self.shift_repo)
        self._exporter = ExcelExporter(db, session_id, self.worker_repo, self.shift_repo)
        self._constraint_mapper = ConstraintMapper(db, session_id)
        self._state_exporter = StateExporter(db, session_id, self.worker_repo, self.shift_repo)

    # ------------------------------------------------------------------
    # Public methods — delegate to sub-modules
    # ------------------------------------------------------------------

    def import_excel(self, file_content: bytes) -> Dict[str, Any]:
        """Orchestrate the Excel import process.

        # FORGIVING IMPORT CONTRACT
        #
        # The import pipeline is deliberately *forgiving*: it skips bad rows,
        # imports all valid data, and returns a detailed warning report.
        #
        # FATAL vs WARNING distinction:
        #   - FATAL (HTTP 400, full DB rollback): raised as ImportValidationException
        #     when pre-validation finds structural errors (missing required sheets,
        #     missing required columns, empty Worker IDs).
        #   - WARNING (HTTP 200, data imported): non-blocking issues are collected
        #     and returned in result["warnings"] as list[str].
        #
        # Three warning pipelines feed into the unified warnings list:
        #   Pipeline A — Pre-validation (services/excel/importer.py):
        #       ImportValidationResult.warnings — duplicate IDs (auto-corrected),
        #       malformed task strings (auto-defaulted), invalid strictness
        #       (auto-defaulted to HARD).
        #   Pipeline B — Parser (data/ex_parser.py):
        #       ExcelParser._warnings — bad availability cells (defaulted to
        #       empty), empty Workers sheet, legacy OR syntax deprecation,
        #       priority range clamping.
        #   Pipeline C — Constraint mapper (services/excel/constraint_mapper.py):
        #       ConstraintMapper.save_constraints() return value — unknown
        #       constraint types (skipped), invalid parameter values (defaulted).

        Stages:
            1. Saves upload to temp file.
            2. Pre-validates the data (collects all errors).
            3. Runs the external ExcelParser.
            4. Adapts and saves constraints to the DB.

        Raises:
            ImportValidationException: If validation errors are found.
            ValueError: If a server error occurs during import.
        """
        tmp_path: Optional[str] = None

        logger.info(f"Starting Excel import for session: {self.session_id}")

        try:
            tmp_path = self._write_temp_file(file_content)
            validation_result = self._run_prevalidation(tmp_path)
            parser = self._run_parser(tmp_path)
            constraint_errors = self._save_constraints(parser)

            logger.debug("Parsing finished, committing to DB")
            self.db.commit()

            return self._build_import_result(validation_result, parser, constraint_errors)

        except ImportValidationException:
            self.db.rollback()
            raise
        except ValueError:
            self.db.rollback()
            raise
        except Exception as e:
            logger.error(f"Import failed: {e}", exc_info=True)
            self.db.rollback()
            raise ValueError(
                "An unexpected error occurred while processing the Excel file. "
                "Please verify the file format and structure."
            )
        finally:
            self._cleanup_temp_file(tmp_path)

    def _write_temp_file(self, file_content: bytes) -> str:
        """Write raw upload bytes to a temp file for pandas/openpyxl to read.

        Args:
            file_content: Raw bytes from the uploaded Excel file.

        Returns:
            Absolute path to the created temporary file.
        """
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(file_content)
            tmp_path = tmp.name

        logger.debug(f"Temporary file created at: {tmp_path}")
        return tmp_path

    def _run_prevalidation(self, tmp_path: str) -> ImportValidationResult:
        """Parse the workbook with pandas and check for structural errors.

        Args:
            tmp_path: Path to the temporary Excel file.

        Returns:
            ImportValidationResult containing any non-blocking warnings.

        Raises:
            ImportValidationException: If blocking validation errors are found.
        """
        import pandas as pd

        logger.debug("Running pre-validation on Excel data")
        xls = pd.ExcelFile(tmp_path)
        validation_result = self._validate_excel_data(xls)

        if validation_result.has_errors():
            logger.warning(f"Validation failed: {len(validation_result.errors)} errors found")
            raise ImportValidationException(validation_result)

        return validation_result

    def _run_parser(self, tmp_path: str) -> "ExcelParser":
        """Create and run the ExcelParser on the temp file.

        Uses the module-level ExcelParser import so that test patches on
        ``"services.excel_service.ExcelParser"`` continue to work.

        Args:
            tmp_path: Path to the (pre-validated) temporary Excel file.

        Returns:
            The populated ExcelParser instance (workers/shifts written to repos).

        Raises:
            NotImplementedError: If ExcelParser has no recognized entry method.
        """
        logger.debug("Using non-destructive import (upsert mode)")
        logger.debug("Initializing ExcelParser")
        parser = ExcelParser(
            worker_repo=self.worker_repo,
            shift_repo=self.shift_repo
        )

        # Dynamically invoke whichever entry method the parser exposes.
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

        logger.debug("Extracting and adapting parsed constraints")
        return parser

    def _build_import_result(
        self,
        validation_result: ImportValidationResult,
        parser: "ExcelParser",
        constraint_errors: List[str],
    ) -> Dict[str, Any]:
        """Count persisted records and aggregate warnings from all pipelines.

        Args:
            validation_result: Pre-validation result (Pipeline A warnings).
            parser: Populated parser instance (Pipeline B warnings).
            constraint_errors: Constraint mapping errors (Pipeline C warnings).

        Returns:
            Dict with ``workers``, ``shifts`` counts and optional ``warnings`` list.
        """
        from data.models import WorkerModel, ShiftModel

        worker_count = self.db.query(WorkerModel).filter(WorkerModel.session_id == self.session_id).count()
        shift_count = self.db.query(ShiftModel).filter(ShiftModel.session_id == self.session_id).count()

        result: Dict[str, Any] = {
            "workers": worker_count,
            "shifts": shift_count
        }

        # Aggregate non-fatal warnings from every pipeline stage into a
        # single unified list.  The frontend displays these as toast messages.
        all_warnings: list[str] = []

        # Pipeline A: pre-validation format warnings (non-blocking)
        for w in validation_result.warnings:
            loc = f"[{w.sheet}"
            if w.row:
                loc += f", row {w.row}"
            if w.field:
                loc += f", field '{w.field}'"
            loc += "]"
            all_warnings.append(f"{loc}: {w.message}")

        # Pipeline B: parser-collected warnings (availability failures, empty sheet)
        all_warnings.extend(getattr(parser, '_warnings', []))

        # Pipeline C: constraint mapper errors (silently-skipped constraints)
        for ce in constraint_errors:
            all_warnings.append(f"Constraint import: {ce}")

        if all_warnings:
            result["warnings"] = all_warnings

        return result

    def _cleanup_temp_file(self, tmp_path: Optional[str]) -> None:
        """Remove the temp file, ignoring errors.

        Args:
            tmp_path: Path to the temporary file, or None if it was never created.
        """
        import os

        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError as e:
                logger.debug("Failed to remove temp file %s: %s", tmp_path, e)

    def export_excel(self) -> io.BytesIO:
        return self._exporter.export_excel()

    def export_full_state(self) -> io.BytesIO:
        return self._state_exporter.export_full_state()

    # ------------------------------------------------------------------
    # Private methods — delegate to sub-modules for backward compat.
    # Tests call these methods directly on ExcelService instances, so
    # they must remain as pass-through proxies to the delegate objects.
    # ------------------------------------------------------------------

    def _find_column(self, df, candidates):
        return self._importer._find_column(df, candidates)

    def _validate_excel_data(self, xls):
        return self._importer._validate_excel_data(xls)

    def _validate_workers_sheet(self, df, result):
        return self._importer._validate_workers_sheet(df, result)

    def _validate_shifts_sheet(self, df, result):
        return self._importer._validate_shifts_sheet(df, result)

    def _validate_constraints_sheet(self, df, result):
        return self._importer._validate_constraints_sheet(df, result)

    def _save_constraints(self, parser):
        return self._constraint_mapper.save_constraints(parser)

    def _compute_constraint_signature(self, constraint):
        return self._constraint_mapper._compute_constraint_signature(constraint)

    def _normalize_dynamic_constraint_params(self, constraint):
        return self._constraint_mapper._normalize_dynamic_constraint_params(constraint)

    def _get_default_constraints(self):
        return self._constraint_mapper._get_default_constraints()

    def _constraint_to_excel_row(self, constraint):
        return self._state_exporter._constraint_to_excel_row(constraint)

    def _write_workers_sheet(self, ws, header_fill, header_font, border_thin):
        return self._state_exporter._write_workers_sheet(ws, header_fill, header_font, border_thin)

    def _write_shifts_sheet(self, ws, header_fill, header_font, border_thin):
        return self._state_exporter._write_shifts_sheet(ws, header_fill, header_font, border_thin)

    def _serialize_tasks_to_string(self, tasks):
        return self._state_exporter._serialize_tasks_to_string(tasks)

    def _write_constraints_sheet(self, ws, header_fill, header_font, border_thin):
        return self._state_exporter._write_constraints_sheet(ws, header_fill, header_font, border_thin)
