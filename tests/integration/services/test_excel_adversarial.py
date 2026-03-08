"""
ADVERSARIAL EXCEL IMPORT TESTS — Explicit Business Logic Contract
==================================================================

These tests assert the INTENDED behaviour after the P0 vulnerability fixes.
Each scenario is labelled with the severity level and the source of truth.

Severity levels (post-fix):
  FATAL   — ImportValidationException raised → HTTP 400, full DB rollback,
             no data persisted.  User must fix the file and re-upload.
  WARNING — Import succeeds (HTTP 200), valid data committed, invalid data
             skipped.  result["warnings"] contains one entry per skipped item
             so the user knows exactly what to fix.

Zero mocks on business logic: every test drives the real ExcelService facade,
ExcelParser (ex_parser.py), and ConstraintMapper (constraint_mapper.py)
against an isolated in-memory SQLite database.
"""

from datetime import datetime
from io import BytesIO

import pandas as pd
import pytest

from data.models import SessionConfigModel, ShiftModel, WorkerModel
from services.excel_service import ExcelService, ImportValidationException


pytestmark = [pytest.mark.integration]


# ============================================================================
# IN-MEMORY EXCEL BUILDERS — adversarial fixtures
# ============================================================================


def _build_excel(
    workers_df: pd.DataFrame,
    shifts_df: pd.DataFrame,
    constraints_df: pd.DataFrame | None = None,
) -> bytes:
    """Write a 2- or 3-sheet workbook to an in-memory bytes buffer.

    Args:
        workers_df: DataFrame written to the 'Workers' sheet.
        shifts_df: DataFrame written to the 'Shifts' sheet.
        constraints_df: Optional DataFrame written to 'Constraints'.

    Returns:
        Raw .xlsx bytes ready to pass to ExcelService.import_excel().
    """
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        workers_df.to_excel(writer, sheet_name="Workers", index=False)
        shifts_df.to_excel(writer, sheet_name="Shifts", index=False)
        if constraints_df is not None:
            constraints_df.to_excel(writer, sheet_name="Constraints", index=False)
    out.seek(0)
    return out.read()


def _worker_row(
    worker_id: str = "W001",
    name: str = "Alice",
    wage: float = 20.0,
    min_hours: int = 0,
    max_hours: int = 40,
    skills: str = "Chef:5",
    monday: str = "08:00-16:00",
) -> dict:
    """Return a single valid worker row dict."""
    return {
        "Worker ID": worker_id,
        "Name": name,
        "Wage": wage,
        "Min Hours": min_hours,
        "Max Hours": max_hours,
        "Skills": skills,
        "Monday": monday,
    }


def _shift_row(
    day: str = "Monday",
    name: str = "Morning",
    start: str = "08:00",
    end: str = "16:00",
    tasks: str = "[Chef:3] x 1",
) -> dict:
    """Return a single valid shift row dict."""
    return {
        "Day": day,
        "Shift Name": name,
        "Start Time": start,
        "End Time": end,
        "Tasks": tasks,
    }


# ============================================================================
# SCENARIO 1 — End-Before-Start is FATAL (blocks entire import, DB rollback)
# ============================================================================


class TestFatalShiftEndBeforeStart:
    """
    SEVERITY: FATAL — ImportValidationException → HTTP 400 — full rollback.

    BUSINESS RULE: A shift whose end time is <= its start time represents
    unambiguous user error (e.g., swapped columns).  We cannot guess intent
    and silently "fix" it by jumping to the next day.

    FIX LOCATION: services/excel/importer.py — _validate_shifts_sheet():
        cross-field end <= start check added as add_error (not add_warning).

    USER CONTRACT: The import is rejected entirely.  No workers, no shifts,
    no partial state is persisted.  The error message names the exact shift
    and its row so the user can fix the file immediately.
    """

    def test_end_before_start_raises_import_validation_exception(
        self, db_session, test_session_id
    ):
        """
        A shift with end time (09:00) <= start time (17:00) MUST raise
        ImportValidationException containing a descriptive error message.
        """
        content = _build_excel(
            workers_df=pd.DataFrame([_worker_row()]),
            shifts_df=pd.DataFrame([
                _shift_row(
                    name="InvertedShift",
                    start="17:00",
                    end="09:00",  # end BEFORE start — FATAL
                )
            ]),
        )

        service = ExcelService(db_session, test_session_id)

        with pytest.raises(ImportValidationException) as exc_info:
            service.import_excel(content)

        # ── Error targets the Shifts sheet ────────────────────────────────────
        errors = exc_info.value.validation_result.errors
        assert len(errors) >= 1, (
            "Expected at least 1 validation error for end-before-start shift."
        )

        sheets = {e.sheet for e in errors}
        assert "Shifts" in sheets, (
            f"Expected error on 'Shifts' sheet, got sheets: {sheets}"
        )

        # ── Error message is descriptive ──────────────────────────────────────
        messages = " ".join(e.message for e in errors)
        assert "InvertedShift" in messages or "17:00" in messages or "09:00" in messages, (
            f"Error message should reference the shift name or times. Got: {messages}"
        )

    def test_end_before_start_leaves_db_clean(self, db_session, test_session_id):
        """
        After a FATAL validation error the database must have zero workers and
        zero shifts — the rollback must be complete.
        """
        content = _build_excel(
            workers_df=pd.DataFrame([_worker_row("W001", "AliceShouldNotExist")]),
            shifts_df=pd.DataFrame([
                _shift_row(name="BadShift", start="18:00", end="06:00")
            ]),
        )

        service = ExcelService(db_session, test_session_id)

        with pytest.raises(ImportValidationException):
            service.import_excel(content)

        db_session.expire_all()

        worker_count = (
            db_session.query(WorkerModel)
            .filter_by(session_id=test_session_id)
            .count()
        )
        shift_count = (
            db_session.query(ShiftModel)
            .filter_by(session_id=test_session_id)
            .count()
        )

        assert worker_count == 0, (
            f"Expected 0 workers after fatal validation error, found {worker_count}. "
            "DB was not fully rolled back."
        )
        assert shift_count == 0, (
            f"Expected 0 shifts after fatal validation error, found {shift_count}. "
            "DB was not fully rolled back."
        )

    def test_valid_shift_same_file_not_blocked(self, db_session, test_session_id):
        """
        A file with one VALID shift and one INVERTED shift must be rejected
        in its entirety — the presence of one error blocks the whole file.
        """
        content = _build_excel(
            workers_df=pd.DataFrame([_worker_row()]),
            shifts_df=pd.DataFrame([
                _shift_row(name="GoodShift", start="08:00", end="16:00"),
                _shift_row(name="BadShift", start="17:00", end="09:00"),
            ]),
        )

        service = ExcelService(db_session, test_session_id)

        with pytest.raises(ImportValidationException) as exc_info:
            service.import_excel(content)

        errors = exc_info.value.validation_result.errors
        bad_shift_errors = [e for e in errors if "BadShift" in e.message or "17:00" in e.message or "09:00" in e.message]
        assert len(bad_shift_errors) >= 1, (
            f"Expected an error specifically for the inverted shift. "
            f"Got errors: {[e.message for e in errors]}"
        )

        db_session.expire_all()
        assert db_session.query(ShiftModel).filter_by(session_id=test_session_id).count() == 0, (
            "GoodShift must NOT be persisted — the entire file is rejected when "
            "any shift has an inverted time window."
        )


# ============================================================================
# SCENARIO 1B — Missing Required Columns is FATAL (multi-fault diagnostics)
# ============================================================================


class TestFatalMissingRequiredColumnsDiagnostics:
    """
    SEVERITY: FATAL — ImportValidationException -> HTTP 400-equivalent.

    BUSINESS RULE: Required structural columns must exist. If multiple required
    columns are missing across sheets, the import must fail and return a full
    diagnostic set so the user can fix everything in one edit cycle.
    """

    def test_fatal_missing_multiple_required_columns_diagnostics(
        self, db_session, test_session_id
    ):
        """
        Simulate simultaneous structural failures:
          - Workers sheet missing 'Worker ID' and 'Name'
          - Shifts sheet missing 'Day'

        Assert that diagnostics explicitly mention EACH missing component.
        """
        content = _build_excel(
            workers_df=pd.DataFrame([{
                "Wage": 20.0,
                "Min Hours": 0,
                "Max Hours": 40,
                "Skills": "Chef:5",
                "Monday": "08:00-16:00",
            }]),
            shifts_df=pd.DataFrame([{
                "Shift Name": "Morning",
                "Start Time": "08:00",
                "End Time": "16:00",
                "Tasks": "[Chef:3] x 1",
            }]),
        )

        service = ExcelService(db_session, test_session_id)
        with pytest.raises(ImportValidationException) as exc_info:
            service.import_excel(content)

        # Service-layer failure contract for import validation (HTTP 400-equivalent).
        payload = exc_info.value.validation_result.to_dict()
        errors = payload["errors"]
        assert errors, "Expected validation errors for missing required columns."

        error_messages = [e["message"] for e in errors]
        assert any("ID" in msg and "Worker ID" in msg for msg in error_messages), (
            f"Expected a missing Worker ID diagnostic. Got: {error_messages}"
        )
        assert any("Name" in msg for msg in error_messages), (
            f"Expected a missing Name diagnostic. Got: {error_messages}"
        )
        assert any("Day" in msg for msg in error_messages), (
            f"Expected a missing Day diagnostic. Got: {error_messages}"
        )


# ============================================================================
# SCENARIO 2 — Constraint Mapping Failure is a WARNING (partial import OK)
# ============================================================================


class TestConstraintMappingFailureIsWarning:
    """
    SEVERITY: WARNING — HTTP 200, workers/shifts committed, bad constraint skipped.

    BUSINESS RULE: An unrecognized constraint type is a data-quality issue,
    not a structural one.  Workers and shifts are the core scheduling data;
    a bad constraint row should not prevent them from being saved.

    FIX LOCATION: services/excel_service.py — import_excel():
        constraint_errors folded into result["warnings"] (not a separate key).
        db.commit() still runs; warnings appear in the response body.

    USER CONTRACT:
        - HTTP 200 returned
        - result["workers"] and result["shifts"] reflect committed counts
        - result["warnings"] contains a human-readable description of the
          skipped constraint so the user knows what to fix
        - The unrecognized constraint is NOT stored in the database
    """

    def test_unrecognized_constraint_returns_200_with_warning(
        self, db_session, test_session_id
    ):
        """
        An unrecognized constraint type must be skipped with a warning.
        Workers and shifts must still be committed.  No exception raised.
        """
        constraints_df = pd.DataFrame([{
            "Type": "COMPLETELY_INVALID_CONSTRAINT_TYPE",
            "Subject": "W001",
            "Target": "W002",
            "Strictness": "Hard",
            "Value": "",
        }])

        content = _build_excel(
            workers_df=pd.DataFrame([
                _worker_row("W001", "AlicePartial"),
                _worker_row("W002", "BobPartial"),
            ]),
            shifts_df=pd.DataFrame([_shift_row()]),
            constraints_df=constraints_df,
        )

        service = ExcelService(db_session, test_session_id)
        result = service.import_excel(content)  # Must NOT raise

        # ── 1. HTTP 200-equivalent (dict returned, no exception) ──────────────
        assert isinstance(result, dict), (
            "Expected result dict for HTTP 200. No exception should be raised "
            "for an unrecognized constraint type."
        )

        # ── 2. Warnings present in response ───────────────────────────────────
        warnings = result.get("warnings", [])
        assert len(warnings) >= 1, (
            f"Expected at least 1 warning for the unrecognized constraint type. "
            f"Got warnings: {warnings}"
        )
        constraint_warnings = [w for w in warnings if "COMPLETELY_INVALID_CONSTRAINT_TYPE" in w]
        assert len(constraint_warnings) >= 1, (
            f"Expected a warning mentioning the invalid type name. "
            f"Got warnings: {warnings}"
        )

        # ── 3. Workers ARE committed ───────────────────────────────────────────
        db_session.expire_all()
        names_in_db = {
            w.name for w in
            db_session.query(WorkerModel).filter_by(session_id=test_session_id).all()
        }
        assert result["workers"] == 2
        assert "AlicePartial" in names_in_db
        assert "BobPartial" in names_in_db

        # ── 4. No "constraint_errors" legacy key (unified into "warnings") ────
        assert "constraint_errors" not in result, (
            "The old 'constraint_errors' key must not appear in the response. "
            "All warnings should be in result['warnings']."
        )

    def test_constraint_failure_does_not_roll_back_workers(
        self, db_session, test_session_id
    ):
        """
        Workers committed before constraint mapping must survive even if the
        constraint mapper encounters an error.  Verify via direct DB query.
        """
        constraints_df = pd.DataFrame([{
            "Type": "ANOTHER_UNRECOGNIZED_TYPE",
            "Subject": "SoloWorker",
            "Target": "",
            "Strictness": "Soft",
            "Value": "10",
        }])

        content = _build_excel(
            workers_df=pd.DataFrame([_worker_row("W001", "SoloWorker")]),
            shifts_df=pd.DataFrame([_shift_row()]),
            constraints_df=constraints_df,
        )

        service = ExcelService(db_session, test_session_id)
        result = service.import_excel(content)

        db_session.expire_all()
        assert result["workers"] == 1, (
            f"Expected 1 worker in result, got {result['workers']}."
        )
        worker = (
            db_session.query(WorkerModel)
            .filter_by(session_id=test_session_id, name="SoloWorker")
            .first()
        )
        assert worker is not None, (
            "SoloWorker must be in the DB even though constraint mapping failed."
        )


# ============================================================================
# SCENARIO 3 — Invalid Availability is a WARNING (worker imported, day empty)
# ============================================================================


class TestAvailabilityParsingFailureIsWarning:
    """
    SEVERITY: WARNING — HTTP 200, worker committed, bad day defaulted to empty.

    BUSINESS RULE: A garbled availability cell (e.g., wrong separator, copy-paste
    artefact) causes data loss for one day but should not prevent the entire
    worker row from being saved.  The warning tells the user which worker and
    which day need correction.

    FIX LOCATION: data/ex_parser.py — _process_workers():
        _parse_availability_cell() now returns bool.  On False, a descriptive
        warning is appended to self._warnings and propagated via the facade.

    USER CONTRACT:
        - HTTP 200 returned
        - Worker IS in the database
        - The bad day has NO availability entry in attributes["availability"]
        - result["warnings"] contains: "Worker 'X' (row N) has an invalid
          {Day} availability format '{value}'. That day's availability was
          defaulted to empty."
    """

    def test_invalid_availability_returns_200_worker_in_db_with_warning(
        self, db_session, test_session_id
    ):
        """
        A garbled Monday availability cell must produce:
          - HTTP 200 (no exception)
          - Worker in DB with empty availability for Monday
          - result["warnings"] containing the worker name and day
        """
        content = _build_excel(
            workers_df=pd.DataFrame([
                _worker_row(
                    worker_id="W_AVAIL",
                    name="GarbledAvailability",
                    monday="GARBAGE_TIME_FORMAT",
                )
            ]),
            shifts_df=pd.DataFrame([_shift_row()]),
        )

        service = ExcelService(db_session, test_session_id)
        result = service.import_excel(content)  # Must NOT raise

        # ── 1. HTTP 200-equivalent ─────────────────────────────────────────────
        assert result["workers"] == 1

        # ── 2. Worker IS in the database ──────────────────────────────────────
        db_session.expire_all()
        worker_model = (
            db_session.query(WorkerModel)
            .filter_by(session_id=test_session_id, name="GarbledAvailability")
            .first()
        )
        assert worker_model is not None, "Worker must be imported despite availability error."

        # ── 3. Monday availability was defaulted to empty ─────────────────────
        availability: dict = worker_model.attributes.get("availability", {})
        assert "MON" not in availability, (
            f"Monday availability must be absent when the cell was unparseable. "
            f"Got: {availability}"
        )

        # ── 4. Warning present in result ──────────────────────────────────────
        warnings = result.get("warnings", [])
        assert len(warnings) >= 1, (
            f"Expected at least 1 warning for the invalid availability. Got: {warnings}"
        )
        avail_warnings = [
            w for w in warnings
            if "GarbledAvailability" in w or "Monday" in w or "GARBAGE_TIME_FORMAT" in w
        ]
        assert len(avail_warnings) >= 1, (
            f"Expected a warning mentioning the worker or day. Got warnings: {warnings}"
        )

    def test_one_garbled_availability_does_not_affect_sibling_worker(
        self, db_session, test_session_id
    ):
        """
        Worker B's garbled availability must not affect Worker A's valid import.
        Worker A must have MON stored; Worker B must have no MON entry.
        Both must appear in result["workers"] == 2.
        """
        content = _build_excel(
            workers_df=pd.DataFrame([
                _worker_row("W001", "ValidAvailability", monday="08:00-16:00"),
                _worker_row("W002", "BrokenAvailability", monday="NOT_A_RANGE"),
            ]),
            shifts_df=pd.DataFrame([_shift_row()]),
        )

        service = ExcelService(db_session, test_session_id)
        result = service.import_excel(content)

        assert result["workers"] == 2

        db_session.expire_all()
        valid_worker = (
            db_session.query(WorkerModel)
            .filter_by(session_id=test_session_id, name="ValidAvailability")
            .first()
        )
        broken_worker = (
            db_session.query(WorkerModel)
            .filter_by(session_id=test_session_id, name="BrokenAvailability")
            .first()
        )

        assert valid_worker is not None
        assert broken_worker is not None

        # Valid worker has MON availability
        assert "MON" in valid_worker.attributes.get("availability", {}), (
            "ValidAvailability must have MON stored."
        )
        # Broken worker has no MON (silently defaulted to empty)
        assert "MON" not in broken_worker.attributes.get("availability", {}), (
            "BrokenAvailability must have no MON entry."
        )

        # Exactly one warning for the worker with invalid availability
        warnings = result.get("warnings", [])
        broken_warnings = [w for w in warnings if "BrokenAvailability" in w or "NOT_A_RANGE" in w]
        assert len(broken_warnings) >= 1, (
            f"Expected a warning for BrokenAvailability. Got: {warnings}"
        )


# ============================================================================
# SCENARIO 4 — Empty Workers Sheet is a WARNING (import continues, 0 workers)
# ============================================================================


class TestEmptyWorkersSheetIsWarning:
    """
    SEVERITY: WARNING — HTTP 200, 0 workers imported, explicit warning returned.

    BUSINESS RULE: An Excel template that was exported for editing but returned
    with an empty Workers sheet is a data-quality issue, not a structural error.
    Shifts may still be valid.  The import proceeds with 0 workers and a clear
    warning so the user knows their roster is missing.

    FIX LOCATION: data/ex_parser.py — _process_workers():
        if df.empty: self._warnings.append("The Workers sheet contains no data rows...")

    USER CONTRACT:
        - HTTP 200 returned
        - result["workers"] == 0
        - result["warnings"] contains a message about the empty Workers sheet
        - Shifts ARE still imported (partial state is intentional here)
    """

    def test_empty_workers_sheet_returns_200_with_zero_workers_and_warning(
        self, db_session, test_session_id
    ):
        """
        A Workers sheet with only column headers (0 data rows) must:
          - Not raise ImportValidationException
          - Return result["workers"] == 0
          - Return result["warnings"] with an entry about the empty sheet
          - Have 0 WorkerModel rows in the database
        """
        workers_headers_only = pd.DataFrame(
            columns=["Worker ID", "Name", "Wage", "Min Hours", "Max Hours", "Skills", "Monday"]
        )

        content = _build_excel(
            workers_df=workers_headers_only,
            shifts_df=pd.DataFrame([_shift_row(name="DummyShift")]),
        )

        service = ExcelService(db_session, test_session_id)
        result = service.import_excel(content)  # Must NOT raise

        # ── 1. HTTP 200-equivalent ─────────────────────────────────────────────
        assert isinstance(result, dict)
        assert result["workers"] == 0, (
            f"Expected workers=0 for empty workers sheet, got {result['workers']}."
        )

        # ── 2. Warning present ────────────────────────────────────────────────
        warnings = result.get("warnings", [])
        assert len(warnings) >= 1, (
            f"Expected at least 1 warning for the empty Workers sheet. Got: {warnings}"
        )
        empty_sheet_warnings = [
            w for w in warnings
            if "workers" in w.lower() and (
                "no data" in w.lower() or "empty" in w.lower() or "0" in w or "no workers" in w.lower()
            )
        ]
        assert len(empty_sheet_warnings) >= 1, (
            f"Expected a warning mentioning empty workers sheet. Got warnings: {warnings}"
        )

        # ── 3. DB has 0 workers ───────────────────────────────────────────────
        db_session.expire_all()
        assert (
            db_session.query(WorkerModel).filter_by(session_id=test_session_id).count() == 0
        ), "Expected 0 workers in DB after importing an empty workers sheet."

    def test_empty_workers_sheet_still_imports_shifts(self, db_session, test_session_id):
        """
        Shifts must still be imported even when the Workers sheet has 0 rows.
        This allows the user to at least have their shift schedule visible while
        they re-upload with corrected worker data.
        """
        workers_headers_only = pd.DataFrame(
            columns=["Worker ID", "Name", "Wage", "Min Hours", "Max Hours", "Skills", "Monday"]
        )

        content = _build_excel(
            workers_df=workers_headers_only,
            shifts_df=pd.DataFrame([_shift_row(name="OrphanShift")]),
        )

        service = ExcelService(db_session, test_session_id)
        result = service.import_excel(content)

        assert result["workers"] == 0
        assert result["shifts"] == 1, (
            f"Expected shifts=1 even with empty workers sheet, got {result['shifts']}."
        )

        db_session.expire_all()
        shift = (
            db_session.query(ShiftModel)
            .filter_by(session_id=test_session_id, name="OrphanShift")
            .first()
        )
        assert shift is not None, "OrphanShift must be in DB despite 0 workers."
