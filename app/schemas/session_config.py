"""Pydantic schemas for Session Configuration (Constraints)."""

from typing import Any, List, Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class ConstraintItem(BaseModel):
    """Generic constraint item: category + params.

    The `category` key should match a registered ConstraintDefinition key
    (e.g. "max_hours_per_week", "avoid_consecutive_shifts", "worker_preferences",
    "mutual_exclusion", "colocation"), and `params` holds the specific
    configuration fields for that constraint type.

    Top-level `type`, `enabled`, and `id` are kept for backwards-compatible
    consumers (e.g. UI badges, database identity).
    """

    category: str = Field(..., description="Constraint type key from definitions")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Constraint parameters (validated per category by definitions registry)",
    )
    id: Optional[str | int] = Field(
        default=None,
        description="Optional identifier used by the frontend / DB",
    )
    enabled: bool = Field(
        default=True,
        description="Whether this constraint is active",
    )
    type: Optional[Literal["HARD", "SOFT"]] = Field(
        default="SOFT",
        description="Strictness hint mainly for dynamic constraints UI",
    )

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type_case(cls, v: Any) -> Optional[str]:
        """Normalize constraint type to uppercase for case-insensitive matching.

        Handles legacy data that may have lowercase 'hard'/'soft' values.
        """
        if v is None:
            return "SOFT"
        if isinstance(v, str):
            normalized = v.strip().upper()
            if normalized in ("HARD", "SOFT"):
                return normalized
            # Fallback for unexpected values
            return "SOFT"
        return v

    @model_validator(mode="after")
    def normalize_params_strictness(self) -> "ConstraintItem":
        """Normalize strictness in params dict to match top-level type.

        Some constraints store strictness inside params - ensure consistency.
        """
        if self.params and "strictness" in self.params:
            strictness = self.params["strictness"]
            if isinstance(strictness, str):
                normalized = strictness.strip().upper()
                if normalized in ("HARD", "SOFT"):
                    self.params["strictness"] = normalized
        return self


class SessionConfigRead(BaseModel):
    """Response schema for GET /constraints."""

    session_id: str
    constraints: List[ConstraintItem] = []

    class Config:
        from_attributes = True


class SessionConfigUpdate(BaseModel):
    """Request schema for PUT /constraints."""

    constraints: List[ConstraintItem]
