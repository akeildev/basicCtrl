"""Phase 4 Learning Pydantic v2 schemas — CGEvent recording + Recipe synthesis.

Per D-15..D-17 (04-CONTEXT.md):

* ObservedAction: One step from the CGEvent tap — keystroke, click, or scroll
* RecipeParam: Named parameter that can be bound at recipe replay time
* RecipePrecondition: Boolean assertion that must be true before step
* RecipeStep: One action within a recipe + per-step recovery hints
* Recipe: Complete workflow — name, app, params, preconditions, steps, criteria

Frozen=True per Phase 1-3 pattern for immutability.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from cua_overlay.state.causal_dag import ActionCanonical


class ObservedAction(BaseModel):
    """Per D-15: One action observed via CGEvent tap + Python consumer.

    Recorded by LearningRecorder.swift (CGEvent tap) and consumed by
    recorder.py (JSONL deserialization). These stream into recipe synthesis.

    user_gesture_type: keystroke | click | scroll (basic classification)
    success: whether the action appeared to succeed (L0/L1 verifier confidence)
    ax_delta: post-action AX tree delta (optional, for recipe precondition mining)
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    step_idx: int
    action: ActionCanonical
    user_gesture_type: Literal["keystroke", "click", "scroll"]
    timestamp: float
    success: bool
    ax_delta: Optional[dict[str, Any]] = None


class RecipeParam(BaseModel):
    """Per D-16: Named parameter for recipe replay — bind at execution time.

    Example: RecipeParam(name="search_term", type="str", description="text to search")
    """

    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    type: Literal["str", "int", "bbox", "element"]


class RecipePrecondition(BaseModel):
    """Per D-16: Boolean assertion — must be true before step.

    Example: RecipePrecondition(expression="search_box.visible", expected_value=True)
    """

    model_config = ConfigDict(frozen=True)

    expression: str
    expected_value: Any
    confidence: float = Field(..., ge=0.0, le=1.0)


class RecipeStep(BaseModel):
    """Per D-16: One action within a recipe + per-step recovery strategy.

    on_failure: list of recovery hints (e.g., "retry_with_longer_wait",
    "fall_back_to_applescript", "escalate_to_user")
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    idx: int
    action: ActionCanonical
    preconditions: list[RecipePrecondition]
    on_failure: list[str]


class Recipe(BaseModel):
    """Per D-16: Complete workflow with parameters, preconditions, steps.

    A Recipe is the artifact saved to episodic memory. It bundles:
    - name: human-readable (e.g., "google_search", "calculator_add")
    - app_bundle_id: which app this recipe targets
    - params: named bindings (e.g., search_term="xyz")
    - preconditions: global checks before ANY step
    - steps: ordered sequence with per-step recovery hints
    - success_criteria: assertions that should hold at the end
    - created_ts: when the recipe was recorded (seconds since epoch)
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str
    app_bundle_id: str
    params: list[RecipeParam]
    preconditions: list[RecipePrecondition]
    steps: list[RecipeStep]
    success_criteria: list[str]
    created_ts: float
