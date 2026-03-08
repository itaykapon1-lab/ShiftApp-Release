"""
Constraint Mapper — Transforms raw Excel constraints into API schema format.

Extracted from services/excel_service.py.
All logic, variables, magic numbers, and comments are preserved exactly.
"""

import hashlib
import json
import logging
from typing import List

import pandas as pd
from pydantic import ValidationError
from sqlalchemy.orm import Session

# Database Models
from data.models import SessionConfigModel

# The Core Logic (External Parser)
from data.ex_parser import ExcelParser
from solver.constraints.definitions import (
    WorkerPreferencesConfig,
    ConstraintKind,
    constraint_definitions,
    register_core_constraints,
)

# Configure logger
logger = logging.getLogger(__name__)


class ConstraintMapper:
    def __init__(self, db: Session, session_id: str):
        self.db = db
        self.session_id = session_id

    def _compute_constraint_signature(self, constraint: dict) -> str:
        """Generate unique signature for constraint deduplication.

        The signature is based on category + params (excluding id and enabled).
        Two constraints with the same category and params are considered duplicates.

        Args:
            constraint: Constraint dict with category and params

        Returns:
            str: MD5 hash signature
        """
        # Build signature data from category and params only
        sig_data = {
            "category": constraint.get("category"),
            "params": constraint.get("params", {})
        }
        return hashlib.md5(json.dumps(sig_data, sort_keys=True).encode()).hexdigest()

    def _normalize_dynamic_constraint_params(self, constraint: dict) -> dict:
        """Normalize dynamic constraints so worker IDs always live under params."""
        if not isinstance(constraint, dict):
            return constraint

        normalized = dict(constraint)
        category = normalized.get("category")

        if category not in ("mutual_exclusion", "colocation"):
            return normalized

        params = dict(normalized.get("params") or {})

        # Migrate legacy/root-level fields into canonical params payload.
        if "worker_a_id" in normalized and "worker_a_id" not in params:
            params["worker_a_id"] = normalized.get("worker_a_id")
        if "worker_b_id" in normalized and "worker_b_id" not in params:
            params["worker_b_id"] = normalized.get("worker_b_id")
        if "strictness" not in params and normalized.get("type"):
            params["strictness"] = normalized.get("type")
        if "penalty" in normalized and "penalty" not in params:
            params["penalty"] = normalized.get("penalty")

        normalized["params"] = params

        # Remove duplicated legacy root fields after migration.
        normalized.pop("worker_a_id", None)
        normalized.pop("worker_b_id", None)
        normalized.pop("penalty", None)

        return normalized

    def _parse_int_cell(
        self,
        raw_value,
        *,
        field_name: str,
        default: int,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> tuple[int, str | None]:
        """Parse integer-like Excel cell values with explicit fallback warnings."""
        if pd.isna(raw_value):
            return default, f"{field_name} is empty; defaulting to {default}."

        text = str(raw_value).strip()
        if text == "" or text.lower() == "nan":
            return default, f"{field_name} is empty; defaulting to {default}."

        try:
            numeric = float(text)
        except (ValueError, TypeError):
            return default, f"{field_name} value '{text}' is invalid; defaulting to {default}."

        if pd.isna(numeric):
            return default, f"{field_name} is empty; defaulting to {default}."

        if not numeric.is_integer():
            return default, f"{field_name} value '{text}' is not an integer; defaulting to {default}."

        parsed = int(numeric)
        if min_value is not None and parsed < min_value:
            return (
                default,
                f"{field_name} value {parsed} is below minimum {min_value}; defaulting to {default}.",
            )
        if max_value is not None and parsed > max_value:
            return (
                default,
                f"{field_name} value {parsed} is above maximum {max_value}; defaulting to {default}.",
            )

        return parsed, None

    def save_constraints(self, parser: ExcelParser) -> List[str]:
        """
        Adapts the raw constraints from the ExcelParser into the strict schema
        required by the new API. Uses MERGE strategy for non-destructive import.

        This ensures the parser (Source of Truth) remains untouched while
        the API receives the specific JSON structure it needs (Target Schema).

        NON-DESTRUCTIVE: New constraints are merged with existing constraints,
        deduplicating by signature (category + params).

        Returns:
            List[str]: List of error messages for constraints that failed to import
        """
        errors: List[str] = []
        try:
            # 1. Get raw constraints from parser
            raw_constraints = getattr(parser, '_raw_constraints', [])

            # 2. Load existing constraints for this session
            config = self.db.query(SessionConfigModel).filter_by(session_id=self.session_id).first()
            existing_constraints = []
            if config and config.constraints:
                existing_constraints = config.constraints if isinstance(config.constraints, list) else []

            # Normalize any legacy dynamic constraints before dedup/signature checks.
            existing_constraints = [
                self._normalize_dynamic_constraint_params(c) for c in existing_constraints
            ]

            # Build signature set for existing constraints
            existing_signatures = {
                self._compute_constraint_signature(c) for c in existing_constraints
            }

            # Determine next available ID
            next_id = max((c.get("id", 0) for c in existing_constraints), default=0) + 1

            # Track how many new constraints we add
            new_count = 0

            # 3. Transform and merge new constraints
            for raw in raw_constraints:
                # Extract raw values safely
                raw_type = str(raw.get('Type', '')).strip()
                subject = str(raw.get('Subject', '')).strip()
                target = str(raw.get('Target', '')).strip()

                # Normalize Strictness (Excel 'Hard' -> API 'HARD')
                raw_strictness = str(raw.get('Strictness', '')).strip().upper()
                strictness_specified = raw_strictness in ['HARD', 'SOFT']
                strictness = raw_strictness if strictness_specified else 'HARD'

                # Default penalty for SOFT constraints
                penalty = -100.0 if strictness == 'SOFT' else 0.0

                transformed_constraint = None

                # Normalize type for case-insensitive matching
                raw_type_lower = raw_type.lower()

                # --- TRANSFORM: Mutual Exclusion ---
                if raw_type_lower in ('mutual exclusion', 'mutualexclusion', 'mutual_exclusion', 'ban'):
                    if subject and target:
                        transformed_constraint = {
                            "id": next_id,
                            "category": "mutual_exclusion",
                            "type": strictness,
                            "enabled": True,
                            "name": f"Ban: {subject} - {target}",
                            "params": {
                                "worker_a_id": subject,
                                "worker_b_id": target,
                                "strictness": strictness,
                                "penalty": penalty,
                            },
                        }

                # --- TRANSFORM: Co-Location ---
                elif raw_type_lower in ('co-location', 'colocation', 'co_location', 'pair'):
                    if subject and target:
                        transformed_constraint = {
                            "id": next_id,
                            "category": "colocation",
                            "type": strictness,
                            "enabled": True,
                            "name": f"Pair: {subject} + {target}",
                            "params": {
                                "worker_a_id": subject,
                                "worker_b_id": target,
                                "strictness": strictness,
                                "penalty": penalty,
                            },
                        }

                # --- TRANSFORM: Preference (worker prefers/avoids a shift) ---
                elif raw_type_lower in ('preference', 'prefer', 'prefers'):
                    if subject and target:
                        # Value column may contain "Prefer" or "Avoid"
                        value = str(raw.get('Value', 'Prefer')).strip().lower()
                        pref_score = 10.0 if value == 'prefer' else -10.0

                        transformed_constraint = {
                            "id": next_id,
                            "category": "worker_preference",
                            "type": "SOFT",  # Preferences are always soft
                            "enabled": True,
                            "name": f"Pref: {subject} -> {target}",
                            "params": {
                                "worker_id": subject,
                                "shift_id": target,
                                "preference_score": pref_score,
                            },
                        }

                # --- TRANSFORM: Max Hours ---
                elif raw_type_lower in ('max hours', 'maxhours', 'max_hours', 'max hours per week'):
                    try:
                        limit = int(raw.get('Value', 40))
                    except (ValueError, TypeError):
                        limit = 40

                    # Static constraints default to SOFT for backward compat
                    effective_strictness = strictness if strictness_specified else 'SOFT'
                    transformed_constraint = {
                        "id": next_id,
                        "category": "max_hours_per_week",
                        "type": effective_strictness,
                        "params": {
                            "max_hours": limit,
                            "strictness": effective_strictness,
                            "penalty": -50.0,
                        },
                        "enabled": True,
                    }

                # --- TRANSFORM: Min Hours ---
                elif raw_type_lower in ('min hours', 'minhours', 'min_hours', 'min hours per week'):
                    try:
                        limit = int(raw.get('Value', 0))
                    except (ValueError, TypeError):
                        limit = 0

                    transformed_constraint = {
                        "id": next_id,
                        "category": "min_hours_per_week",
                        "type": strictness,
                        "params": {
                            "min_hours": limit,
                            "penalty": -50.0,
                        },
                        "enabled": True,
                    }

                # --- TRANSFORM: Avoid Consecutive Shifts ---
                elif raw_type_lower in ('avoid consecutive shifts', 'avoid_consecutive_shifts'):
                    try:
                        min_rest = int(float(raw.get('Value', 12)))
                    except (ValueError, TypeError):
                        min_rest = 12
                    try:
                        pen = float(raw.get('Penalty', -30.0))
                        if pen != pen:  # NaN guard
                            pen = -30.0
                    except (ValueError, TypeError):
                        pen = -30.0

                    # Static constraints default to SOFT for backward compat
                    effective_strictness = strictness if strictness_specified else 'SOFT'
                    transformed_constraint = {
                        "id": next_id,
                        "category": "avoid_consecutive_shifts",
                        "type": effective_strictness,
                        "enabled": True,
                        "params": {
                            "min_rest_hours": min_rest,
                            "strictness": effective_strictness,
                            "penalty": pen,
                        },
                    }

                # --- TRANSFORM: Worker Preferences ---
                elif raw_type_lower in ('worker preferences', 'worker_preferences'):
                    value_raw = str(raw.get('Value', 'True')).strip().lower()
                    enabled_flag = value_raw not in ('false', '0', 'no', '')

                    # Parse configurable weights from legacy Excel columns.
                    preference_reward, reward_warning = self._parse_int_cell(
                        raw.get('Subject'),
                        field_name="Worker Preferences reward (Subject column)",
                        default=10,
                        min_value=1,
                    )
                    if reward_warning:
                        errors.append(reward_warning)

                    preference_penalty, penalty_warning = self._parse_int_cell(
                        raw.get('Penalty'),
                        field_name="Worker Preferences penalty (Penalty column)",
                        default=-100,
                        max_value=-1,
                    )
                    if penalty_warning:
                        errors.append(penalty_warning)

                    raw_params = {
                        "enabled": enabled_flag,
                        "preference_reward": preference_reward,
                        "preference_penalty": preference_penalty,
                    }
                    try:
                        validated_params = WorkerPreferencesConfig.model_validate(raw_params).model_dump()
                    except ValidationError as exc:
                        errors.append(
                            "Worker Preferences parameters failed validation; "
                            f"falling back to defaults. Details: {exc.errors()}"
                        )
                        validated_params = WorkerPreferencesConfig.model_validate(
                            {"enabled": enabled_flag}
                        ).model_dump()

                    transformed_constraint = {
                        "id": next_id,
                        "category": "worker_preferences",
                        "type": strictness,
                        "enabled": True,
                        "params": validated_params,
                    }

                # --- TRANSFORM: Task Option Priority ---
                elif raw_type_lower in (
                    'task option priority', 'task_option_priority', 'option priority',
                ):
                    try:
                        pen = float(raw.get('Penalty', -20.0))
                        if pen != pen:  # NaN guard
                            pen = -20.0
                    except (ValueError, TypeError):
                        pen = -20.0

                    transformed_constraint = {
                        "id": next_id,
                        "category": "task_option_priority",
                        "type": "SOFT",
                        "enabled": True,
                        "params": {
                            "base_penalty": pen,
                        },
                    }

                # Track unrecognized constraint types
                if not transformed_constraint and raw_type:
                    error_msg = f"Unknown constraint type '{raw_type}' (row data: Subject='{subject}', Target='{target}')"
                    logger.warning(error_msg)
                    errors.append(error_msg)

                # DEDUPLICATION: Only add if signature is unique
                if transformed_constraint:
                    sig = self._compute_constraint_signature(transformed_constraint)
                    if sig not in existing_signatures:
                        existing_constraints.append(transformed_constraint)
                        existing_signatures.add(sig)
                        next_id += 1
                        new_count += 1
                        logger.debug(f"Added new constraint: {transformed_constraint.get('category')}")
                    else:
                        logger.debug(f"Skipped duplicate constraint: {transformed_constraint.get('category')}")

            # 4. Use defaults only if no constraints exist at all
            if not existing_constraints:
                logger.debug("No constraints found, loading defaults")
                existing_constraints = self._get_default_constraints()

            # 5. Save merged list to Database
            if config:
                config.constraints = existing_constraints
            else:
                config = SessionConfigModel(session_id=self.session_id, constraints=existing_constraints)
                self.db.add(config)

            logger.info(f"Constraint merge complete: added {new_count} new, total {len(existing_constraints)}")

            return errors

        except Exception as e:
            error_msg = f"Constraint import failed: {str(e)}"
            logger.warning(error_msg)
            errors.append(error_msg)
            return errors

    def _get_default_constraints(self) -> list:
        """Build static default constraints from canonical definitions.

        This keeps Excel-import fallback defaults aligned with the API schema
        registry, preventing drift (for example, dropping worker_preferences
        or task_option_priority from imported sessions).
        """
        try:
            register_core_constraints()
        except ValueError:
            # Definitions already registered in this process.
            pass

        defaults: list[dict] = []
        next_id = 1

        for defn in constraint_definitions.all():
            if defn.constraint_kind != ConstraintKind.STATIC:
                continue

            default_params = {}
            schema_props = defn.config_model.model_json_schema().get("properties", {})
            for field_name, field_info in schema_props.items():
                if "default" in field_info:
                    default_params[field_name] = field_info["default"]

            defaults.append(
                {
                    "id": next_id,
                    "category": defn.key,
                    "type": defn.constraint_type.value.upper(),
                    "enabled": True,
                    "name": defn.label,
                    "description": defn.description,
                    "params": default_params,
                }
            )
            next_id += 1

        return defaults
