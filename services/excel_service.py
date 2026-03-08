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


@dataclass
class ImportError:
    """Represents a single import error."""
    sheet: str
    row: Optional[int]
    field: Optional[str]
    message: str
    severity: str = "error"  # "error" or "warning"


@dataclass
class ImportValidationResult:
    """Aggregates all validation errors from an import operation."""
    errors: List[ImportError] = field(default_factory=list)
    warnings: List[ImportError] = field(default_factory=list)

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
    """Exception raised when Excel import validation fails."""

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
        self.worker_repo = SQLWorkerRepository(db, session_id)
        self.shift_repo = SQLShiftRepository(db, session_id)

        # Instantiate delegates
        self._importer = ExcelImporter(db, session_id, self.worker_repo, self.shift_repo)
        self._exporter = ExcelExporter(db, session_id, self.worker_repo, self.shift_repo)
        self._constraint_mapper = ConstraintMapper(db, session_id)
        self._state_exporter = StateExporter(db, session_id, self.worker_repo, self.shift_repo)

    # ------------------------------------------------------------------
    # Public methods — delegate to sub-modules
    # ------------------------------------------------------------------

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
        import os
        import tempfile
        import pandas as pd
        from data.models import WorkerModel, ShiftModel

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
            logger.debug("Initializing ExcelParser")
            parser = ExcelParser(
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
            constraint_errors = self._save_constraints(parser)

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

            # 9. Collect all non-fatal warnings from every pipeline stage into
            #    a single unified list.  Callers (API route + frontend) consume
            #    only result["warnings"] — no stage-specific keys.
            all_warnings: list[str] = []

            # Stage A: pre-validation format warnings (non-blocking)
            for w in validation_result.warnings:
                loc = f"[{w.sheet}"
                if w.row:
                    loc += f", row {w.row}"
                if w.field:
                    loc += f", field '{w.field}'"
                loc += "]"
                all_warnings.append(f"{loc}: {w.message}")

            # Stage B: parser-collected warnings (availability failures, empty sheet)
            all_warnings.extend(getattr(parser, '_warnings', []))

            # Stage C: constraint mapper errors (silently-skipped constraints)
            for ce in constraint_errors:
                all_warnings.append(f"Constraint import: {ce}")

            if all_warnings:
                result["warnings"] = all_warnings

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

    def export_excel(self) -> io.BytesIO:
        return self._exporter.export_excel()

    def export_full_state(self) -> io.BytesIO:
        return self._state_exporter.export_full_state()

    # ------------------------------------------------------------------
    # Private methods — delegate to sub-modules for backward compat
    # (tests call these directly on ExcelService instances)
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

    def _clear_session_data(self):
        return self._importer._clear_session_data()

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
