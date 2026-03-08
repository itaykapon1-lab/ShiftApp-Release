"""
Constraint Schema Service.

Generates UI-friendly schema from constraint definitions for the frontend
to render dynamic forms. Uses Pydantic's JSON Schema plus UiFieldMeta overrides.
"""

from pydantic import BaseModel

from solver.constraints.definitions import (
    constraint_definitions,
    ConstraintDefinition,
    UiFieldMeta,
)


class UiFieldSchema(BaseModel):
    """Schema for a single field in the constraint form."""

    name: str
    label: str
    widget: str
    type: str
    required: bool
    default: object | None = None
    description: str | None = None
    minimum: float | None = None
    maximum: float | None = None
    enum: list[object] | None = None
    order: int = 0


class ConstraintTypeSchema(BaseModel):
    """Schema for a single constraint type (used by the frontend)."""

    key: str
    label: str
    description: str | None
    constraint_type: str
    constraint_kind: str
    fields: list[UiFieldSchema]


def _build_field_schema(defn: ConstraintDefinition) -> list[UiFieldSchema]:
    """Build UI field schemas from Pydantic model and UiFieldMeta overrides."""
    model_schema = defn.config_model.model_json_schema()
    props = model_schema.get("properties", {})
    required_set = set(model_schema.get("required", []))

    ui_fields_by_name: dict[str, UiFieldMeta] = {f.name: f for f in defn.ui_fields}

    fields: list[UiFieldSchema] = []
    for name, prop in props.items():
        ui_meta = ui_fields_by_name.get(name)
        field_type = prop.get("type", "string")

        # Handle 'anyOf' for Optional types in Pydantic v2
        if "anyOf" in prop:
            for variant in prop["anyOf"]:
                if variant.get("type") != "null":
                    field_type = variant.get("type", field_type)
                    if "default" not in prop and "default" in variant:
                        prop = {**prop, "default": variant.get("default")}
                    break

        fields.append(
            UiFieldSchema(
                name=name,
                label=ui_meta.label if ui_meta else name.replace("_", " ").title(),
                widget=ui_meta.widget.value if ui_meta else "text",
                type=field_type,
                required=name in required_set,
                default=prop.get("default"),
                description=prop.get("description") or (ui_meta.help_text if ui_meta else None),
                minimum=prop.get("minimum"),
                maximum=prop.get("maximum"),
                enum=prop.get("enum"),
                order=ui_meta.order if ui_meta else 0,
            )
        )

    fields.sort(key=lambda f: f.order)
    return fields


def get_constraints_schema() -> list[ConstraintTypeSchema]:
    """Return UI-friendly schema for all registered constraint types."""
    schemas: list[ConstraintTypeSchema] = []
    for defn in constraint_definitions.all():
        schemas.append(
            ConstraintTypeSchema(
                key=defn.key,
                label=defn.label,
                description=defn.description,
                constraint_type=defn.constraint_type.value,
                constraint_kind=defn.constraint_kind.value,
                fields=_build_field_schema(defn),
            )
        )
    return schemas
