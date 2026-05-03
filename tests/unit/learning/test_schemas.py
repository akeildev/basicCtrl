"""Phase 4 learning schemas — unit tests for Recipe and ObservedAction contracts.

Per Wave 0 pattern: pytest.importorskip skips cleanly until impl ships.
Tests lock the system-wide learning contract for CGEvent recording + recipe synthesis.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

pytest.importorskip("basicctrl.learning")

from basicctrl.learning import (
    ObservedAction,
    Recipe,
    RecipeParam,
    RecipePrecondition,
    RecipeStep,
)
from basicctrl.state.causal_dag import ActionCanonical


def _build_action(
    step_idx: int = 0,
    action_type: str = "click",
) -> ActionCanonical:
    """Helper to build a minimal ActionCanonical."""
    return ActionCanonical(
        id=f"action-{step_idx}",
        step_idx=step_idx,
        kind="READ",
        target_key="button://app/target",
        action_type=action_type,
        payload={"x": 100, "y": 100},
        timestamp_ns=0,
        session_id="test-session",
    )


@pytest.mark.unit
def test_observed_action_creation() -> None:
    """ObservedAction stores step_idx, action, gesture type, timestamp, success."""
    action = _build_action(step_idx=0)
    observed = ObservedAction(
        step_idx=0,
        action=action,
        user_gesture_type="click",
        timestamp=1234567890.0,
        success=True,
    )
    assert observed.step_idx == 0
    assert observed.user_gesture_type == "click"
    assert observed.success is True
    assert observed.ax_delta is None


@pytest.mark.unit
def test_observed_action_with_ax_delta() -> None:
    """ObservedAction.ax_delta captures tree changes (optional)."""
    action = _build_action(step_idx=1)
    observed = ObservedAction(
        step_idx=1,
        action=action,
        user_gesture_type="keystroke",
        timestamp=1234567891.0,
        success=True,
        ax_delta={"new_elements": ["elem-1", "elem-2"]},
    )
    assert observed.ax_delta == {"new_elements": ["elem-1", "elem-2"]}


@pytest.mark.unit
def test_observed_action_frozen() -> None:
    """ObservedAction is frozen."""
    action = _build_action(step_idx=0)
    observed = ObservedAction(
        step_idx=0,
        action=action,
        user_gesture_type="click",
        timestamp=1234567890.0,
        success=True,
    )
    with pytest.raises(ValidationError, match="frozen"):
        observed.success = False  # type: ignore[misc]


@pytest.mark.unit
def test_recipe_creation_with_steps() -> None:
    """Recipe bundles params, preconditions, steps, success_criteria."""
    param = RecipeParam(
        name="search_term",
        description="what to search",
        type="str",
    )
    precond = RecipePrecondition(
        expression="search_box.visible",
        expected_value=True,
        confidence=0.99,
    )
    action = _build_action(step_idx=0, action_type="click")
    step = RecipeStep(
        idx=0,
        action=action,
        preconditions=[precond],
        on_failure=["retry_with_wait"],
    )
    recipe = Recipe(
        name="google_search",
        app_bundle_id="com.google.Chrome",
        params=[param],
        preconditions=[precond],
        steps=[step],
        success_criteria=["search_results_displayed"],
        created_ts=1234567890.0,
    )

    assert recipe.name == "google_search"
    assert recipe.app_bundle_id == "com.google.Chrome"
    assert len(recipe.params) == 1
    assert len(recipe.steps) == 1
    assert recipe.steps[0].idx == 0
    assert recipe.steps[0].on_failure == ["retry_with_wait"]


@pytest.mark.unit
def test_recipe_frozen() -> None:
    """Recipe is frozen."""
    recipe = Recipe(
        name="test",
        app_bundle_id="com.test.app",
        params=[],
        preconditions=[],
        steps=[],
        success_criteria=[],
        created_ts=1234567890.0,
    )
    with pytest.raises(ValidationError, match="frozen"):
        recipe.name = "modified"  # type: ignore[misc]


@pytest.mark.unit
def test_recipe_step_on_failure_recovery_hints() -> None:
    """RecipeStep.on_failure carries per-step recovery strategies."""
    action = _build_action(step_idx=0)
    step = RecipeStep(
        idx=0,
        action=action,
        preconditions=[],
        on_failure=["retry_with_longer_wait", "fall_back_to_applescript"],
    )
    assert len(step.on_failure) == 2
    assert "retry_with_longer_wait" in step.on_failure


@pytest.mark.unit
def test_recipe_param_types() -> None:
    """RecipeParam.type is restricted to str | int | bbox | element."""
    for type_val in ["str", "int", "bbox", "element"]:
        param = RecipeParam(
            name="test",
            description="test",
            type=type_val,  # type: ignore[arg-type]
        )
        assert param.type == type_val

    with pytest.raises(ValidationError, match="Input should be"):
        RecipeParam(
            name="test",
            description="test",
            type="invalid",  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_recipe_precondition_confidence_bounds() -> None:
    """RecipePrecondition.confidence is in [0.0, 1.0]."""
    precond = RecipePrecondition(
        expression="check",
        expected_value=True,
        confidence=0.95,
    )
    assert precond.confidence == 0.95

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        RecipePrecondition(
            expression="check",
            expected_value=True,
            confidence=1.5,  # type: ignore[arg-type]
        )
