"""
API Routers Package.

This package contains domain-specific route slices, each mounted
via FastAPI's APIRouter. The original monolithic routes.py has been
vertically sliced by domain:

- worker_routes.py        -> Worker CRUD
- shift_routes.py         -> Shift CRUD (with date anchoring)
- solver_routes.py        -> Solver trigger, status, diagnostics
- constraint_routes.py    -> Constraint configuration
- import_export_routes.py -> Excel import/export
- session_routes.py       -> Session data management
"""
