"""Unit tests for Recipe synthesis (D-16, D-17).

Per 04-06-PLAN.md: Test recipe synthesis from ObservedAction list.
- Synthesis produces valid Recipe JSON
- Precondition extraction verified
- on_failure hints per step
- Serialization + round-trip deserialization
"""
from __future__ import annotations

import json

import pytest

from cua_overlay.learning.recipe_synth import RecipeSynthesizer
from cua_overlay.learning.schemas import ObservedAction, RecipeParam, RecipeStep
from cua_overlay.state.causal_dag import ActionCanonical


@pytest.fixture
def synthesizer() -> RecipeSynthesizer:
    """Fixture: initialized RecipeSynthesizer."""
    return RecipeSynthesizer()


def _build_action(
    step_idx: int = 0,
    action_type: str = "click",
    x: int = 100,
    y: int = 100,
) -> ActionCanonical:
    """Helper to build ActionCanonical."""
    payload = {}
    if action_type == "click":
        payload = {"x": x, "y": y}
    elif action_type == "type":
        payload = {"text": "hello"}

    return ActionCanonical(
        id=f"action-{step_idx}",
        step_idx=step_idx,
        kind="READ",
        target_key=f"input://{step_idx}",
        action_type=action_type,
        payload=payload,
        timestamp_ns=0,
        session_id="test-session",
    )


def _build_observed_action(
    step_idx: int = 0,
    action_type: str = "click",
    timestamp: float = 1000.0,
    success: bool = True,
    ax_delta: dict | None = None,
) -> ObservedAction:
    """Helper to build ObservedAction."""
    action = _build_action(step_idx=step_idx, action_type=action_type)
    return ObservedAction(
        step_idx=step_idx,
        action=action,
        user_gesture_type="click" if action_type == "click" else "keystroke",
        timestamp=timestamp,
        success=success,
        ax_delta=ax_delta,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_5_actions_to_recipe(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 1: 5 ObservedAction (2 clicks, 3 typeText) → Recipe with 5 steps + params.

    Per D-16: Converts actions to steps, infers parameters from typeText.
    """
    # Build 5 actions: click, type, click, type, type
    observed = [
        _build_observed_action(step_idx=0, action_type="click", timestamp=1000.0),
        _build_observed_action(step_idx=1, action_type="type", timestamp=1010.0),
        _build_observed_action(step_idx=2, action_type="click", timestamp=1020.0),
        _build_observed_action(step_idx=3, action_type="type", timestamp=1030.0),
        _build_observed_action(step_idx=4, action_type="type", timestamp=1040.0),
    ]

    recipe = await synthesizer.synthesize(
        observed_actions=observed,
        app_bundle_id="com.google.Chrome",
        task_label="google_search",
    )

    # Verify recipe structure
    assert recipe.name == "google_search"
    assert recipe.app_bundle_id == "com.google.Chrome"
    assert len(recipe.steps) == 5
    assert len(recipe.params) >= 3  # At least 3 type actions → params

    # Verify steps are properly converted
    for i, step in enumerate(recipe.steps):
        assert step.idx == i
        assert isinstance(step.action, ActionCanonical)
        assert isinstance(step.on_failure, list)
        assert len(step.on_failure) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_precondition_extraction(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 2: Precondition extraction — verify recipe.preconditions not empty.

    Per D-16: First action's AX delta → initial state checks.
    """
    ax_delta = {
        "app": "com.google.Chrome",
        "window_title": "Google Search",
    }
    observed = [
        _build_observed_action(
            step_idx=0,
            action_type="click",
            timestamp=1000.0,
            ax_delta=ax_delta,
        ),
        _build_observed_action(step_idx=1, action_type="type", timestamp=1010.0),
    ]

    recipe = await synthesizer.synthesize(
        observed_actions=observed,
        app_bundle_id="com.google.Chrome",
        task_label="test_search",
    )

    # Verify preconditions extracted from AX delta
    assert len(recipe.preconditions) > 0
    for precond in recipe.preconditions:
        assert 0.0 <= precond.confidence <= 1.0
        assert isinstance(precond.expression, str)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_on_failure_hints(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 3: on_failure hints — verify each step has recovery guidance.

    Per D-16: Default hints = [retry_once, alt_translator, abort].
    Customized per action type (type → clear_and_retry, click → retry_once).
    """
    observed = [
        _build_observed_action(step_idx=0, action_type="click"),
        _build_observed_action(step_idx=1, action_type="type"),
        _build_observed_action(step_idx=2, action_type="click"),
    ]

    recipe = await synthesizer.synthesize(
        observed_actions=observed,
        app_bundle_id="com.test.app",
        task_label="mixed_actions",
    )

    # Verify all steps have on_failure hints
    for i, step in enumerate(recipe.steps):
        assert isinstance(step.on_failure, list)
        assert len(step.on_failure) > 0

        # Click steps should prefer retry_once
        if step.action.action_type == "click":
            assert "retry_once" in step.on_failure

        # Type steps should prefer clear_and_retry
        if step.action.action_type == "type":
            assert "clear_and_retry" in step.on_failure or "retry_once" in step.on_failure


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_serialization_roundtrip(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 4: Recipe serialization to JSON + round-trip deserialization.

    Per D-16: Recipe JSON must be serializable and parseable.
    """
    observed = [
        _build_observed_action(step_idx=0, action_type="click"),
        _build_observed_action(step_idx=1, action_type="type"),
    ]

    recipe = await synthesizer.synthesize(
        observed_actions=observed,
        app_bundle_id="com.test.app",
        task_label="serialize_test",
    )

    # Serialize to JSON
    recipe_dict = recipe.model_dump()
    json_str = json.dumps(recipe_dict)

    # Deserialize back
    parsed_dict = json.loads(json_str)

    # Rebuild Recipe from parsed dict
    from cua_overlay.learning.schemas import Recipe

    recipe_restored = Recipe(**parsed_dict)

    # Verify round-trip integrity
    assert recipe_restored.name == recipe.name
    assert recipe_restored.app_bundle_id == recipe.app_bundle_id
    assert len(recipe_restored.steps) == len(recipe.steps)
    assert len(recipe_restored.params) == len(recipe.params)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_empty_actions(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 5: Empty ObservedAction list → minimal Recipe.

    Per D-16: Edge case handling — empty recording yields empty recipe.
    """
    recipe = await synthesizer.synthesize(
        observed_actions=[],
        app_bundle_id="com.test.app",
        task_label="empty_task",
    )

    assert recipe.name == "empty_task"
    assert recipe.app_bundle_id == "com.test.app"
    assert len(recipe.steps) == 0
    assert len(recipe.params) == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_single_click(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 6: Single click action → minimal Recipe with 1 step.

    Per D-16: Minimal valid recipe (single step, no params).
    """
    observed = [
        _build_observed_action(step_idx=0, action_type="click"),
    ]

    recipe = await synthesizer.synthesize(
        observed_actions=observed,
        app_bundle_id="com.test.app",
        task_label="single_click",
    )

    assert len(recipe.steps) == 1
    assert recipe.steps[0].action.action_type == "click"
    assert len(recipe.params) == 0  # No type actions


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_success_criteria(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 7: Success criteria extracted from final action.

    Per D-16: End-of-recipe assertions (text_changed, value_changed, etc).
    """
    final_ax_delta = {
        "text_changed": "search result appeared",
        "value_changed": True,
    }
    observed = [
        _build_observed_action(step_idx=0, action_type="click"),
        _build_observed_action(
            step_idx=1,
            action_type="type",
            success=True,
            ax_delta=final_ax_delta,
        ),
    ]

    recipe = await synthesizer.synthesize(
        observed_actions=observed,
        app_bundle_id="com.test.app",
        task_label="with_criteria",
    )

    # Verify success criteria extracted
    assert len(recipe.success_criteria) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recipe_synth_failed_action_handling(
    synthesizer: RecipeSynthesizer,
) -> None:
    """Test 8: Recipe with failed action still synthesizes.

    Per D-16: success=False on an action is recorded but doesn't block synthesis.
    """
    observed = [
        _build_observed_action(step_idx=0, action_type="click", success=False),
        _build_observed_action(step_idx=1, action_type="type", success=True),
    ]

    recipe = await synthesizer.synthesize(
        observed_actions=observed,
        app_bundle_id="com.test.app",
        task_label="with_failure",
    )

    assert len(recipe.steps) == 2
    # Both steps should be included regardless of success
    assert recipe.steps[0].action.step_idx == 0
    assert recipe.steps[1].action.step_idx == 1
