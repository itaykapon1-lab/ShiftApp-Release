"""Domain exception hierarchy for ShiftApp.

These exceptions carry safe, user-facing messages. The API layer maps
them to HTTP status codes via FastAPI exception handlers.
"""


class ShiftAppError(Exception):
    """Base exception for all ShiftApp domain errors.

    Args:
        safe_message: User-facing message safe to return in HTTP responses.
        internal_detail: Internal-only detail logged server-side, never exposed.
    """

    def __init__(
        self,
        safe_message: str = "An unexpected error occurred.",
        internal_detail: str | None = None,
    ) -> None:
        self.safe_message = safe_message
        self.internal_detail = internal_detail
        super().__init__(safe_message)


class ResourceNotFoundError(ShiftAppError):
    """HTTP 404 — requested resource does not exist."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        super().__init__(safe_message=f"{resource_type} '{resource_id}' not found")


class ResourceConflictError(ShiftAppError):
    """HTTP 409 — operation conflicts with existing state."""

    def __init__(self, safe_message: str = "Operation conflicts with current state.") -> None:
        super().__init__(safe_message=safe_message)


class ValidationError(ShiftAppError):
    """HTTP 400 — business-rule validation failure (not Pydantic schema)."""

    def __init__(self, safe_message: str = "Validation failed.") -> None:
        super().__init__(safe_message=safe_message)


class ImportValidationError(ShiftAppError):
    """HTTP 400 — Excel import validation failure with structured error report.

    Replaces the standalone ``ImportValidationException`` from ``excel_service.py``
    by integrating it into the ``ShiftAppError`` hierarchy so global exception
    handlers can catch it consistently.

    Args:
        validation_result: An ``ImportValidationResult`` instance carrying
            structured error and warning details from the pre-validation pass.
    """

    def __init__(self, validation_result: object) -> None:
        self.validation_result = validation_result
        summary = (
            validation_result.format_summary()
            if hasattr(validation_result, "format_summary")
            else str(validation_result)
        )
        super().__init__(safe_message=summary)


class SolverError(ShiftAppError):
    """HTTP 500 — solver backend crash (NOT infeasibility).

    Wraps unexpected exceptions from the OR-Tools solver backend
    (e.g., out-of-memory, corrupted model, library segfault).
    Infeasible results are communicated via the result dict, not exceptions.

    Args:
        safe_message: User-facing message.
        internal_detail: Internal-only detail logged server-side.
        job_id: The solver job identifier, if available.
    """

    def __init__(
        self,
        safe_message: str = "The solver encountered an unexpected error.",
        internal_detail: str | None = None,
        job_id: str | None = None,
    ) -> None:
        self.job_id = job_id
        super().__init__(safe_message=safe_message, internal_detail=internal_detail)


class ConstraintHydrationError(SolverError):
    """A required hard constraint failed validation during hydration.

    Raised when a HARD constraint's Pydantic config cannot be validated,
    making it impossible to build a valid constraint registry for the solver.

    Args:
        category: The constraint category key (e.g. ``"max_hours"``).
        detail: Internal-only description of the validation failure.
        safe_message: User-facing message safe to return in HTTP responses.
    """

    def __init__(
        self,
        category: str,
        detail: str,
        safe_message: str = "A required scheduling constraint could not be loaded.",
    ) -> None:
        self.category = category
        super().__init__(safe_message=safe_message, internal_detail=detail)


class InternalError(ShiftAppError):
    """HTTP 500 — unexpected internal failure. safe_message is always generic."""

    def __init__(
        self,
        safe_message: str = "An internal error occurred. Please try again later.",
        internal_detail: str | None = None,
    ) -> None:
        super().__init__(safe_message=safe_message, internal_detail=internal_detail)
