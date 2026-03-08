"""
Canonical metadata-driven constraint definitions.

This module introduces a single source of truth for:
- Constraint configuration models (Pydantic)
- Runtime constraint implementations (BaseConstraint subclasses)
- UI metadata used by the frontend to render dynamic forms
"""

from enum import Enum
from typing import Callable, Dict, Type

from pydantic import BaseModel, Field, field_validator

from app.core.constants import (
    MAX_HOURS_PER_WEEK_DEFAULT,
    MAX_HOURS_PER_WEEK_PENALTY,
    CONSECUTIVE_REST_HOURS_DEFAULT,
    CONSECUTIVE_REST_PENALTY,
    WORKER_PREFERENCE_REWARD,
    WORKER_PREFERENCE_PENALTY,
    TASK_PRIORITY_BASE_PENALTY,
    MUTUAL_EXCLUSION_PENALTY,
    CO_LOCATION_PENALTY,
)
from solver.constraints.base import BaseConstraint, ConstraintType, ConstraintKind
from solver.constraints.static_soft import (
    MaxHoursPerWeekConstraint,
    AvoidConsecutiveShiftsConstraint,
    WorkerPreferencesConstraint,
    TaskOptionPriorityConstraint,
)
from solver.constraints.dynamic import (
    MutualExclusionConstraint,
    CoLocationConstraint,
)


class UiFieldWidget(str, Enum):
    """Widget hint for frontend rendering."""

    text = "text"
    number = "number"
    select = "select"
    checkbox = "checkbox"
    worker_select = "worker_select"  # Searchable dropdown populated by workers list


class UiFieldMeta(BaseModel):
    """Additional UI metadata for a single configuration field."""

    name: str
    label: str
    help_text: str | None = None
    widget: UiFieldWidget
    required: bool = True
    order: int = 0


class ConstraintConfigBase(BaseModel):
    """Base class for all constraint configuration models.

    These models:
    - Are the canonical configuration schema for each constraint type.
    - Are used both for runtime construction and for JSON Schema export to the UI.
    """

    class Config:
        # Do not allow unknown fields from the frontend / external sources.
        extra = "forbid"
        # Immutable once created to avoid accidental mutation.
        frozen = True

    @field_validator("strictness", mode="before", check_fields=False)
    @classmethod
    def normalize_strictness_case(cls, v):
        """Allow case-insensitive strictness values for dynamic constraints."""
        if isinstance(v, ConstraintType):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in ("hard", "soft"):
                return normalized
        return v


class MaxHoursPerWeekConfig(ConstraintConfigBase):
    """Configuration for MaxHoursPerWeekConstraint."""

    max_hours: int = Field(
        MAX_HOURS_PER_WEEK_DEFAULT,
        ge=0,
        le=80,
        description="Maximum hours per worker per week",
    )
    strictness: ConstraintType = Field(
        ConstraintType.SOFT,
        description="Whether this limit is HARD (infeasible) or SOFT (penalty)",
    )
    penalty: float = Field(
        MAX_HOURS_PER_WEEK_PENALTY,
        le=0,
        description="Penalty for exceeding max hours (per hour over the limit)",
    )


class AvoidConsecutiveShiftsConfig(ConstraintConfigBase):
    """Configuration for AvoidConsecutiveShiftsConstraint."""

    min_rest_hours: int = Field(
        CONSECUTIVE_REST_HOURS_DEFAULT,
        ge=0,
        le=48,
        description="Minimum required rest period between consecutive shifts (hours)",
    )
    strictness: ConstraintType = Field(
        ConstraintType.SOFT,
        description="Whether this rest requirement is HARD (infeasible) or SOFT (penalty)",
    )
    penalty: float = Field(
        CONSECUTIVE_REST_PENALTY,
        le=0,
        description="Penalty for each insufficient-rest violation",
    )


class WorkerPreferencesConfig(ConstraintConfigBase):
    """Configuration for WorkerPreferencesConstraint."""

    enabled: bool = Field(
        True,
        description="Whether worker preference scoring is applied",
    )
    preference_reward: int = Field(
        WORKER_PREFERENCE_REWARD,
        ge=1,
        description="Points added to objective when a worker is assigned a preferred shift",
    )
    preference_penalty: int = Field(
        WORKER_PREFERENCE_PENALTY,
        le=-1,
        description="Points subtracted from objective when a worker is assigned an unwanted shift",
    )


class TaskOptionPriorityConfig(ConstraintConfigBase):
    """Configuration for TaskOptionPriorityConstraint."""

    base_penalty: float = Field(
        TASK_PRIORITY_BASE_PENALTY,
        le=0,
        description="Penalty per priority level above #1",
    )


class MutualExclusionConfig(ConstraintConfigBase):
    """Configuration for MutualExclusionConstraint (dynamic rule)."""

    worker_a_id: str = Field(..., description="ID of the first worker")
    worker_b_id: str = Field(..., description="ID of the second worker")
    strictness: ConstraintType = Field(
        ConstraintType.HARD,
        description="Whether the ban is HARD or SOFT",
    )
    penalty: float = Field(
        MUTUAL_EXCLUSION_PENALTY,
        le=0,
        description="Penalty applied for SOFT violations",
    )


class CoLocationConfig(ConstraintConfigBase):
    """Configuration for CoLocationConstraint (dynamic rule)."""

    worker_a_id: str = Field(..., description="ID of the first worker")
    worker_b_id: str = Field(..., description="ID of the second worker")
    strictness: ConstraintType = Field(
        ConstraintType.SOFT,
        description="Whether pairing is HARD or SOFT",
    )
    penalty: float = Field(
        CO_LOCATION_PENALTY,
        le=0,
        description="Penalty applied for SOFT violations",
    )


class ConstraintDefinition(BaseModel):
    """Canonical definition tying together config, implementation and UI metadata."""

    key: str  # e.g. "max_hours_per_week"
    label: str
    description: str | None = None
    constraint_type: ConstraintType  # HARD / SOFT
    constraint_kind: ConstraintKind  # STATIC / DYNAMIC

    # Strongly typed config model used both for validation and schema export
    config_model: Type[ConstraintConfigBase]

    # Domain-level class applying the constraint
    implementation_cls: Type[BaseConstraint]

    # Factory to go from config -> runtime constraint instance
    factory: Callable[[ConstraintConfigBase], BaseConstraint]

    # UI field metadata (optional, overrides Pydantic defaults if needed)
    ui_fields: list[UiFieldMeta] = []


class ConstraintDefinitionRegistry:
    """In-memory registry of all known constraint definitions."""

    def __init__(self) -> None:
        self._by_key: Dict[str, ConstraintDefinition] = {}

    def register(self, definition: ConstraintDefinition) -> None:
        if definition.key in self._by_key:
            raise ValueError(f"Constraint key already registered: {definition.key}")
        self._by_key[definition.key] = definition

    def get(self, key: str) -> ConstraintDefinition:
        return self._by_key[key]

    def all(self) -> list[ConstraintDefinition]:
        return list(self._by_key.values())


constraint_definitions = ConstraintDefinitionRegistry()


def register_core_constraints() -> None:
    """Register a first subset of core constraints in the canonical registry.

    This function is idempotent at the level of constraint *keys*; calling it
    multiple times will raise if duplicate keys are registered, so it should be
    invoked once during application startup.
    """

    # Max hours per week (static soft)
    constraint_definitions.register(
        ConstraintDefinition(
            key="max_hours_per_week",
            label="Max hours per week",
            description="Limit total weekly hours per worker.",
            constraint_type=ConstraintType.SOFT,
            constraint_kind=ConstraintKind.STATIC,
            config_model=MaxHoursPerWeekConfig,
            implementation_cls=MaxHoursPerWeekConstraint,
            factory=lambda cfg: MaxHoursPerWeekConstraint(
                max_hours=cfg.max_hours,  # type: ignore[attr-defined]
                penalty_per_hour=cfg.penalty,  # type: ignore[attr-defined]
                strictness=cfg.strictness,  # type: ignore[attr-defined]
            ),
            ui_fields=[
                UiFieldMeta(
                    name="max_hours",
                    label="Max hours per week",
                    widget=UiFieldWidget.number,
                    order=10,
                    help_text="Weekly hours threshold before overtime penalties apply.",
                ),
                UiFieldMeta(
                    name="strictness",
                    label="Strictness",
                    widget=UiFieldWidget.select,
                    order=20,
                    help_text="HARD = must satisfy, SOFT = preferred.",
                ),
                UiFieldMeta(
                    name="penalty",
                    label="Penalty per hour over limit",
                    widget=UiFieldWidget.number,
                    order=30,
                    help_text="Negative value; larger magnitude means stronger preference.",
                ),
            ],
        )
    )

    # Avoid consecutive shifts (static soft)
    constraint_definitions.register(
        ConstraintDefinition(
            key="avoid_consecutive_shifts",
            label="Avoid consecutive shifts",
            description="Discourage back-to-back shifts with insufficient rest.",
            constraint_type=ConstraintType.SOFT,
            constraint_kind=ConstraintKind.STATIC,
            config_model=AvoidConsecutiveShiftsConfig,
            implementation_cls=AvoidConsecutiveShiftsConstraint,
            factory=lambda cfg: AvoidConsecutiveShiftsConstraint(
                min_rest_hours=cfg.min_rest_hours,  # type: ignore[attr-defined]
                penalty=cfg.penalty,  # type: ignore[attr-defined]
                strictness=cfg.strictness,  # type: ignore[attr-defined]
            ),
            ui_fields=[
                UiFieldMeta(
                    name="min_rest_hours",
                    label="Minimum rest hours",
                    widget=UiFieldWidget.number,
                    order=10,
                    help_text="Minimum required rest between consecutive shifts.",
                ),
                UiFieldMeta(
                    name="strictness",
                    label="Strictness",
                    widget=UiFieldWidget.select,
                    order=20,
                    help_text="HARD = must satisfy, SOFT = preferred.",
                ),
                UiFieldMeta(
                    name="penalty",
                    label="Penalty per violation",
                    widget=UiFieldWidget.number,
                    order=30,
                    help_text="Negative value applied when rest is below the minimum.",
                ),
            ],
        )
    )

    # Worker preferences (static soft, toggleable via config)
    constraint_definitions.register(
        ConstraintDefinition(
            key="worker_preferences",
            label="Worker preferences",
            description="Adjust objective based on worker shift preferences.",
            constraint_type=ConstraintType.SOFT,
            constraint_kind=ConstraintKind.STATIC,
            config_model=WorkerPreferencesConfig,
            implementation_cls=WorkerPreferencesConstraint,
            factory=lambda cfg: _build_worker_preferences_constraint(cfg),
            ui_fields=[
                UiFieldMeta(
                    name="enabled",
                    label="Enable worker preferences",
                    widget=UiFieldWidget.checkbox,
                    order=10,
                    help_text="Toggle whether worker preference scores affect the schedule.",
                ),
                UiFieldMeta(
                    name="preference_reward",
                    label="Reward points (preferred shifts)",
                    widget=UiFieldWidget.number,
                    order=20,
                    help_text="Points added when a worker is scheduled for a shift they prefer.",
                ),
                UiFieldMeta(
                    name="preference_penalty",
                    label="Penalty points (unwanted shifts)",
                    widget=UiFieldWidget.number,
                    order=30,
                    help_text="Points subtracted when a worker is scheduled for a shift they want to avoid (negative value).",
                ),
            ],
        )
    )

    # Task option priority (static soft)
    constraint_definitions.register(
        ConstraintDefinition(
            key="task_option_priority",
            label="Task option priority",
            description="Penalizes selection of lower-priority task options.",
            constraint_type=ConstraintType.SOFT,
            constraint_kind=ConstraintKind.STATIC,
            config_model=TaskOptionPriorityConfig,
            implementation_cls=TaskOptionPriorityConstraint,
            factory=lambda cfg: TaskOptionPriorityConstraint(
                base_penalty=cfg.base_penalty,  # type: ignore[attr-defined]
            ),
            ui_fields=[
                UiFieldMeta(
                    name="base_penalty",
                    label="Penalty per priority level",
                    widget=UiFieldWidget.number,
                    order=10,
                    help_text="Negative value. #3 option incurs 2x this penalty.",
                ),
            ],
        )
    )

    # Mutual exclusion (dynamic)
    constraint_definitions.register(
        ConstraintDefinition(
            key="mutual_exclusion",
            label="Mutual exclusion",
            description="Ban two workers from working together in the same shift.",
            # The actual runtime instance type comes from strictness; this is a default hint.
            constraint_type=ConstraintType.HARD,
            constraint_kind=ConstraintKind.DYNAMIC,
            config_model=MutualExclusionConfig,
            implementation_cls=MutualExclusionConstraint,
            factory=lambda cfg: MutualExclusionConstraint(
                worker_a_id=cfg.worker_a_id,  # type: ignore[attr-defined]
                worker_b_id=cfg.worker_b_id,  # type: ignore[attr-defined]
                strictness=cfg.strictness,  # type: ignore[attr-defined]
                penalty=cfg.penalty,  # type: ignore[attr-defined]
            ),
            ui_fields=[
                UiFieldMeta(
                    name="worker_a_id",
                    label="Worker A",
                    widget=UiFieldWidget.worker_select,
                    order=10,
                    help_text="First worker in the exclusion pair.",
                ),
                UiFieldMeta(
                    name="worker_b_id",
                    label="Worker B",
                    widget=UiFieldWidget.worker_select,
                    order=20,
                    help_text="Second worker in the exclusion pair.",
                ),
                UiFieldMeta(
                    name="strictness",
                    label="Strictness",
                    widget=UiFieldWidget.select,
                    order=30,
                    help_text="HARD = must satisfy, SOFT = preferred.",
                ),
                UiFieldMeta(
                    name="penalty",
                    label="Penalty",
                    widget=UiFieldWidget.number,
                    order=40,
                    help_text="Penalty applied for SOFT violations (negative value).",
                ),
            ],
        )
    )

    # Co-location (dynamic)
    constraint_definitions.register(
        ConstraintDefinition(
            key="colocation",
            label="Co-location",
            description="Ensure two workers are paired together when working.",
            constraint_type=ConstraintType.SOFT,
            constraint_kind=ConstraintKind.DYNAMIC,
            config_model=CoLocationConfig,
            implementation_cls=CoLocationConstraint,
            factory=lambda cfg: CoLocationConstraint(
                worker_a_id=cfg.worker_a_id,  # type: ignore[attr-defined]
                worker_b_id=cfg.worker_b_id,  # type: ignore[attr-defined]
                strictness=cfg.strictness,  # type: ignore[attr-defined]
                penalty=cfg.penalty,  # type: ignore[attr-defined]
            ),
            ui_fields=[
                UiFieldMeta(
                    name="worker_a_id",
                    label="Worker A",
                    widget=UiFieldWidget.worker_select,
                    order=10,
                    help_text="First worker in the pairing.",
                ),
                UiFieldMeta(
                    name="worker_b_id",
                    label="Worker B",
                    widget=UiFieldWidget.worker_select,
                    order=20,
                    help_text="Second worker in the pairing.",
                ),
                UiFieldMeta(
                    name="strictness",
                    label="Strictness",
                    widget=UiFieldWidget.select,
                    order=30,
                    help_text="HARD = must satisfy, SOFT = preferred.",
                ),
                UiFieldMeta(
                    name="penalty",
                    label="Penalty",
                    widget=UiFieldWidget.number,
                    order=40,
                    help_text="Penalty applied for SOFT violations (negative value).",
                ),
            ],
        )
    )


def _build_worker_preferences_constraint(cfg: ConstraintConfigBase) -> WorkerPreferencesConstraint:
    """Factory helper that respects the enabled flag and configurable scoring."""
    # Narrow the type at runtime; config schema ensures the shape.
    assert isinstance(cfg, WorkerPreferencesConfig)
    constraint = WorkerPreferencesConstraint(
        preference_reward=cfg.preference_reward,
        preference_penalty=cfg.preference_penalty,
    )
    constraint.enabled = cfg.enabled
    return constraint

