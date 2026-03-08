"""Unit tests for constraint definition registry and config validation."""

import pytest

from solver.constraints.definitions import constraint_definitions, register_core_constraints


pytestmark = [pytest.mark.unit]


def test_core_constraint_definitions_registered():
    try:
        register_core_constraints()
    except ValueError:
        # Already registered in this process.
        pass

    keys = {d.key for d in constraint_definitions.all()}
    assert {"max_hours_per_week", "avoid_consecutive_shifts", "worker_preferences", "mutual_exclusion", "colocation"}.issubset(keys)


def test_max_hours_per_week_config_validation():
    defn = constraint_definitions.get("max_hours_per_week")
    cfg = defn.config_model.model_validate({"max_hours": 40, "penalty": -10})
    assert cfg.max_hours == 40
    with pytest.raises(Exception):
        defn.config_model.model_validate({"max_hours": -1, "penalty": -10})
