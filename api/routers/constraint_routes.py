"""
Constraints Configuration Route Handlers.

Extracted from the monolithic api/routes.py.
All logic, variables, and comments are preserved exactly as they were.
"""
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.schemas.session_config import SessionConfigRead, SessionConfigUpdate
from app.db.session import get_db
from data.models import WorkerModel, SessionConfigModel
from solver.constraints.definitions import constraint_definitions, ConstraintConfigBase, ConstraintKind
from api.deps import get_session_id

logger = logging.getLogger(__name__)

router = APIRouter(tags=["constraints"])

# ==========================================
# CONSTRAINTS CONFIGURATION
# ==========================================


def _build_system_defaults() -> List[Dict[str, Any]]:
    """Build default constraint configurations from the registry.

    Returns STATIC constraints with their default parameter values.
    Dynamic constraints (mutual_exclusion, colocation) are instance-based
    and have no meaningful default state.
    """
    defaults = []
    counter = 1

    for defn in constraint_definitions.all():
        # Only include STATIC constraints as defaults
        # Dynamic constraints require user-specified worker pairs
        if defn.constraint_kind != ConstraintKind.STATIC:
            continue

        # Get default params from the Pydantic config model
        default_params = {}
        model_schema = defn.config_model.model_json_schema()
        props = model_schema.get("properties", {})

        for field_name, field_info in props.items():
            if "default" in field_info:
                default_params[field_name] = field_info["default"]

        defaults.append({
            "id": counter,
            "category": defn.key,
            "type": defn.constraint_type.value.upper(),  # Normalize to uppercase
            "enabled": True,
            "name": defn.label,
            "description": defn.description,
            "params": default_params,
        })
        counter += 1

    return defaults


def _merge_constraints_with_defaults(
    stored: List[Dict[str, Any]],
    defaults: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge stored constraints with system defaults.

    Strategy:
    - Stored constraints take precedence (by category key)
    - Missing STATIC defaults are appended
    - Dynamic constraints (no default) are preserved as-is

    Returns a complete list with all defaults + user overrides.
    """
    # Index stored constraints by category for O(1) lookup
    stored_by_category = {c.get("category"): c for c in stored if c.get("category")}

    merged = []
    used_categories = set()

    # First, add all defaults (possibly overridden by stored)
    for default in defaults:
        category = default["category"]
        if category in stored_by_category:
            # User has an override - use their version
            merged.append(stored_by_category[category])
        else:
            # No override - use default
            merged.append(default)
        used_categories.add(category)

    # Add remaining stored constraints (dynamic ones not in defaults)
    for constraint in stored:
        category = constraint.get("category")
        if category and category not in used_categories:
            merged.append(constraint)

    return merged


def _validate_schema_driven_constraints(constraints_data: List[Dict[str, Any]]) -> None:
    """
    Validate schema-driven constraints (those backed by ConstraintDefinitionRegistry).

    For each constraint whose category is registered in `constraint_definitions`,
    we validate its `params` payload against the corresponding Pydantic config model.

    On validation failure, we raise HTTPException(422) with FastAPI/Pydantic-style
    error objects, so the frontend can map them back to dynamic fields.
    """
    errors: List[Dict[str, Any]] = []

    for idx, item in enumerate(constraints_data):
        category = item.get("category")

        try:
            defn = constraint_definitions.get(category)
        except KeyError:
            # Unknown / legacy categories are ignored here to preserve
            # backward compatibility. They can be validated separately.
            continue

        # Prefer explicit params dict, fall back to full item for backward compat
        params = item.get("params") or item

        try:
            defn.config_model.model_validate(params)
        except ValidationError as exc:
            for e in exc.errors():
                errors.append(
                    {
                        "loc": ["constraints", idx, "params", *e.get("loc", [])],
                        "msg": e.get("msg", "Invalid value"),
                        "type": e.get("type", "value_error"),
                    }
                )

    if errors:
        # FastAPI will pass this structure as-is to the client; the frontend
        # uses `loc` and `msg` to highlight specific dynamic fields.
        raise HTTPException(status_code=422, detail=errors)

@router.get("/constraints", response_model=SessionConfigRead)
async def get_constraints(
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    """Fetch constraint configuration for the current session.

    Behavior:
    - Brand-new sessions (no SessionConfig row) receive STATIC defaults.
    - Existing sessions are treated as user-owned state and returned as-is.
      This includes an empty constraints list when the user deleted all constraints.
    """
    config = db.query(SessionConfigModel).filter_by(session_id=session_id).first()

    if not config:
        # Brand-new session bootstrap with system defaults.
        defaults = _build_system_defaults()
        return SessionConfigRead(
            session_id=session_id,
            constraints=defaults
        )

    # Existing session: respect persisted state exactly (including []).
    return SessionConfigRead(
        session_id=session_id,
        constraints=config.constraints or []
    )

@router.put("/constraints", response_model=SessionConfigRead)
async def update_constraints(
    config_update: SessionConfigUpdate,
    session_id: str = Depends(get_session_id),
    db: Session = Depends(get_db)
):
    """Update constraint configuration for the current session."""
    try:
        # Convert Pydantic models to dicts for JSON storage
        constraints_data = [c.model_dump() for c in config_update.constraints]

        # First, validate schema-driven constraints against canonical definitions.
        # This produces structured 422 errors that the frontend can map to fields.
        _validate_schema_driven_constraints(constraints_data)
        
        # Validation: Check if worker_ids exist for dynamic constraints
        for constraint_dict in constraints_data:
            category = constraint_dict.get('category')

            # Validate worker IDs for constraints that reference workers
            if category in ['mutual_exclusion', 'colocation']:
                # FIX: Worker IDs are in 'params' dict, not at root level
                params = constraint_dict.get('params', {})
                worker_a_id = params.get('worker_a_id') or constraint_dict.get('worker_a_id')
                worker_b_id = params.get('worker_b_id') or constraint_dict.get('worker_b_id')

                # Check if workers exist
                if worker_a_id:
                    worker_a = db.query(WorkerModel).filter_by(
                        worker_id=worker_a_id,
                        session_id=session_id
                    ).first()
                    if not worker_a:
                        raise HTTPException(
                            400,
                            detail=f"Worker '{worker_a_id}' not found in session '{session_id}'"
                        )

                if worker_b_id:
                    worker_b = db.query(WorkerModel).filter_by(
                        worker_id=worker_b_id,
                        session_id=session_id
                    ).first()
                    if not worker_b:
                        raise HTTPException(
                            400,
                            detail=f"Worker '{worker_b_id}' not found in session '{session_id}'"
                        )
        
        # Update or create config
        config = db.query(SessionConfigModel).filter_by(session_id=session_id).first()
        
        if config:
            config.constraints = constraints_data
        else:
            config = SessionConfigModel(
                session_id=session_id,
                constraints=constraints_data
            )
            db.add(config)
        
        db.commit()
        db.refresh(config)
        
        return SessionConfigRead(
            session_id=config.session_id,
            constraints=config.constraints or []
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error("Failed to update constraints: %s", e, exc_info=True)
        raise HTTPException(500, detail="Failed to update constraints. Please try again or contact support.")
