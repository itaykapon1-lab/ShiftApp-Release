"""
API Route Hub.

This module assembles all domain-specific routers into a single APIRouter
that is included by app/main.py. The actual endpoint logic lives in the
api/routers/ package, vertically sliced by domain:

- api/routers/worker_routes.py        -> Worker CRUD
- api/routers/shift_routes.py         -> Shift CRUD (with date anchoring)
- api/routers/solver_routes.py        -> Solver trigger, status, diagnostics
- api/routers/constraint_routes.py    -> Constraint configuration
- api/routers/import_export_routes.py -> Excel import/export
- api/routers/session_routes.py       -> Session data management
"""
from fastapi import APIRouter

from api.routers import (
    worker_routes,
    shift_routes,
    solver_routes,
    constraint_routes,
    import_export_routes,
    session_routes,
)

# Backward-compatible re-exports for existing tests that import from api.routes
from api.routers.constraint_routes import (  # noqa: F401
    _build_system_defaults,
    _merge_constraints_with_defaults,
    _validate_schema_driven_constraints,
    get_constraints,
)
from api.routers.helpers import (  # noqa: F401
    _map_model_to_worker_schema,
    _map_model_to_shift_schema,
)

# Re-export SolverService so tests that patch "api.routes.SolverService" still work
from services.solver_service import SolverService  # noqa: F401

# Central router that aggregates all sub-routers
router = APIRouter(prefix="/api/v1", tags=["solver"])

router.include_router(worker_routes.router)
router.include_router(shift_routes.router)
router.include_router(solver_routes.router)
router.include_router(constraint_routes.router)
router.include_router(import_export_routes.router)
router.include_router(session_routes.router)
