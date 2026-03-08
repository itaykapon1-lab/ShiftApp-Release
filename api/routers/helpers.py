"""
Shared helpers for API route handlers.

Contains model-to-schema mapping functions used across multiple routers.
These helpers take the Raw DB Model and format it for the Frontend.
This prevents data loss that happens when converting Model -> Domain -> Schema.
"""
from datetime import datetime
from data.models import WorkerModel, ShiftModel


def _normalize_skills(skills_raw: object) -> dict:
    """Normalises raw skill names from the DB to Title Case.

    Mirrors the normalisation applied by ``SQLWorkerRepository._to_domain()``
    so that the API response is consistent regardless of how the worker was
    created (via API, Excel import, or direct DB insertion).

    Args:
        skills_raw: The raw value stored in the ``attributes["skills"]`` column.

    Returns:
        dict: ``{Title_Case_skill_name: level_int}`` mapping.
    """
    if not isinstance(skills_raw, dict):
        return {}
    normalized: dict = {}
    for skill_name, level in skills_raw.items():
        try:
            normalized[str(skill_name).title()] = int(level)
        except (ValueError, TypeError):
            normalized[str(skill_name).title()] = 1
    return normalized


def _map_model_to_worker_schema(model: WorkerModel) -> dict:
    """Maps a WorkerModel ORM instance to the dict representation for the API response.

    Applies skill-name normalization (Title Case) and populates a ``warnings``
    list with advisory messages for workers whose configuration may prevent
    them from being assigned to any shifts.

    Args:
        model: The SQLAlchemy WorkerModel instance from the database.

    Returns:
        dict: A fully-populated dict matching the WorkerRead schema.
    """
    attrs = model.attributes or {}

    # Normalise skills to Title Case to mirror domain-layer normalization
    skills = _normalize_skills(attrs.get("skills", {}))

    avail = attrs.get("availability", {})
    warnings_list = []
    if not avail:
        warnings_list.append(
            "No availability windows defined. "
            "This worker will be ineligible for all shifts until availability is added."
        )

    # Build a complete attributes dict with default values for missing keys
    full_attrs = {
        "skills": skills,
        "availability": avail if avail else {},
        "wage": attrs.get("wage", 0.0),
        "min_hours": attrs.get("min_hours", 0),
        "max_hours": attrs.get("max_hours", 40),
    }
    # Preserve any additional keys that may be stored in attributes
    for k, v in attrs.items():
        if k not in full_attrs:
            full_attrs[k] = v

    return {
        "worker_id": model.worker_id,
        "name": model.name,
        "attributes": full_attrs,
        "session_id": model.session_id,
        "warnings": warnings_list,
    }

def _map_model_to_shift_schema(model: ShiftModel) -> dict:
    start_str = model.start_time
    if isinstance(start_str, datetime):
        start_str = start_str.isoformat()

    end_str = model.end_time
    if isinstance(end_str, datetime):
        end_str = end_str.isoformat()

    return {
        "shift_id": model.shift_id,
        "name": model.name,
        "start_time": start_str,
        "end_time": end_str,
        "tasks_data": model.tasks_data or {},
        "session_id": model.session_id
    }
