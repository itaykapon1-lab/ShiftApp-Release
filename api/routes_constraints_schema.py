"""
Constraint Schema API Routes.

Exposes the constraint schema endpoint for the frontend to bootstrap dynamic forms.
"""

from fastapi import APIRouter

from app.services.constraint_schema_service import (
    get_constraints_schema,
    ConstraintTypeSchema,
)

router = APIRouter(prefix="/constraints", tags=["constraints-schema"])


@router.get("/schema", response_model=list[ConstraintTypeSchema])
async def read_constraints_schema():
    """Return UI-friendly schema for all registered constraint types.

    The frontend uses this to render dynamic constraint forms without
    hard-coding field definitions.
    """
    return get_constraints_schema()
