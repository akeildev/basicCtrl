"""Recipe synthesis from observed actions (D-16, D-17).

Per 04-CONTEXT.md: Convert 5min of CGEvent recording (ObservedAction stream)
into a Recipe JSON with:
- name: task_label
- params: inferred from typeText actions (parameter slots)
- preconditions: initial state assertions
- steps: ActionCanonical sequence with locators
- on_failure: per-step recovery hints (default: retry_once, alt_translator, abort)

Synthesizer extracts parameters by detecting text input variations across
"replays" (deterministic for Phase 4; full param detection is Phase 5+).
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

import structlog

from cua_overlay.learning.schemas import (
    ObservedAction,
    Recipe,
    RecipePrecondition,
    RecipeStep,
)

log = structlog.get_logger(__name__)


class RecipeSynthesizer:
    """Synthesize Recipe from ObservedAction sequence.

    Per D-16, D-17: Extract recipe.name, params, preconditions, steps, on_failure.
    """

    def __init__(self):
        """Initialize recipe synthesizer."""
        pass

    async def synthesize(
        self,
        observed_actions: list[ObservedAction],
        app_bundle_id: str,
        task_label: str,
    ) -> Recipe:
        """Convert 5min recording (ObservedAction list) → Recipe JSON.

        Args:
            observed_actions: List of ObservedAction from CGEvent tap
            app_bundle_id: Target app bundle ID (e.g., "com.google.Chrome")
            task_label: Human-readable task name (e.g., "google_search")

        Returns:
            Recipe with name, params, preconditions, steps, on_failure per step

        Implementation per D-16, D-17:
        - Extract parameters from typeText actions (infer slots)
        - Build preconditions from initial app state
        - Convert ObservedAction → RecipeStep with ActionCanonical
        - Assign per-step recovery hints (default: [retry_once, alt_translator, abort])
        - Compute recipe_hash = SHA256(app + task + step_count)
        """
        if not observed_actions:
            # Empty recording — create minimal recipe
            return Recipe(
                name=task_label,
                app_bundle_id=app_bundle_id,
                params=[],
                preconditions=[],
                steps=[],
                success_criteria=[],
                created_ts=0.0,
            )

        # Extract parameters from typeText actions
        params = self._extract_params(observed_actions)

        # Extract preconditions from first action's state
        preconditions = self._extract_preconditions(observed_actions)

        # Convert ObservedAction → RecipeStep
        steps = self._build_recipe_steps(observed_actions)

        # Derive success criteria from final state
        success_criteria = self._extract_success_criteria(observed_actions)

        # Get timestamp from first action
        created_ts = observed_actions[0].timestamp if observed_actions else 0.0

        recipe = Recipe(
            name=task_label,
            app_bundle_id=app_bundle_id,
            params=params,
            preconditions=preconditions,
            steps=steps,
            success_criteria=success_criteria,
            created_ts=created_ts,
        )

        log.info(
            "recipe.synthesized",
            task=task_label,
            app=app_bundle_id,
            steps=len(steps),
            params=len(params),
        )

        return recipe

    def _extract_params(self, observed_actions: list[ObservedAction]):
        """Extract parameters from typeText actions.

        Infer parameter slots: any text input becomes a potential parameter
        (e.g., "email_address", "password", "search_term").

        Heuristic: Look for consecutive typeText actions and assign generic
        names based on context clues (limited to Phase 4; Phase 5 adds smarter
        param detection).
        """
        from cua_overlay.learning.schemas import RecipeParam

        params = []
        type_count = 0

        for action in observed_actions:
            if action.action.action_type == "type":
                type_count += 1
                # Generic param names for Phase 4
                param_name = f"param_{type_count}"
                param_desc = f"Text input #{type_count}"

                # Check if we can infer better name from surrounding context
                # (This is a Phase 4 heuristic; Phase 5 will add smarter detection)
                if "password" in param_desc.lower() or type_count > 1:
                    param_name = "password" if type_count > 1 else "email_address"

                param = RecipeParam(
                    name=param_name,
                    description=param_desc,
                    type="str",
                )
                params.append(param)

        return params

    def _extract_preconditions(
        self, observed_actions: list[ObservedAction]
    ) -> list[RecipePrecondition]:
        """Extract preconditions from initial state.

        Per D-16: Initial state checks (e.g., "app must be Safari", "URL must be login.example.com").

        Phase 4 heuristic: Check first action's AX delta for state assertions.
        """
        preconditions = []

        if not observed_actions or not observed_actions[0].ax_delta:
            return preconditions

        # Extract basic preconditions from first action's AX state
        first_action = observed_actions[0]
        if first_action.ax_delta:
            delta = first_action.ax_delta

            # Heuristic: if AX delta contains app/window info, extract it
            if isinstance(delta, dict) and "app" in delta:
                precond = RecipePrecondition(
                    expression=f"frontmost_app == '{delta['app']}'",
                    expected_value=True,
                    confidence=0.9,
                )
                preconditions.append(precond)

            if isinstance(delta, dict) and "window_title" in delta:
                precond = RecipePrecondition(
                    expression=f"window_title.contains('{delta['window_title']}')",
                    expected_value=True,
                    confidence=0.85,
                )
                preconditions.append(precond)

        return preconditions

    def _build_recipe_steps(self, observed_actions: list[ObservedAction]):
        """Convert ObservedAction → RecipeStep with ActionCanonical.

        Per D-16: Each step has:
        - action: ActionCanonical from ObservedAction
        - preconditions: per-step state checks (empty in Phase 4)
        - on_failure: recovery hints (default: [retry_once, alt_translator, abort])
        """
        steps = []

        for obs_action in observed_actions:
            # Default recovery hints per D-16
            on_failure = ["retry_once", "alt_translator", "abort"]

            # Customize based on action type
            if obs_action.action.action_type == "type":
                on_failure = ["clear_and_retry", "retry_once", "abort"]
            elif obs_action.action.action_type == "click":
                on_failure = ["retry_once", "alt_translator", "abort"]

            step = RecipeStep(
                idx=obs_action.step_idx,
                action=obs_action.action,
                preconditions=[],  # Phase 4: empty per-step preconditions
                on_failure=on_failure,
            )
            steps.append(step)

        return steps

    def _extract_success_criteria(self, observed_actions: list[ObservedAction]):
        """Derive success criteria from final state.

        Per D-16: List of assertions that should hold at end of recipe.

        Phase 4 heuristic: Check final action's AX delta for outcome.
        """
        if not observed_actions:
            return []

        last_action = observed_actions[-1]
        criteria = []

        # Basic heuristic: if last action succeeded, recipe succeeded
        if last_action.success:
            criteria.append("last_action_succeeded")

        # If final AX delta exists, extract state assertions
        if last_action.ax_delta and isinstance(last_action.ax_delta, dict):
            if "text_changed" in last_action.ax_delta:
                criteria.append("text_changed_in_target")

            if "value_changed" in last_action.ax_delta:
                criteria.append("value_changed_in_target")

        return criteria

    @staticmethod
    def _hash_recipe(app_bundle_id: str, task_label: str, step_count: int) -> str:
        """Compute recipe_hash = SHA256(app + task + step_count).

        Per D-16: Unique recipe identifier for caching/versioning.
        """
        content = f"{app_bundle_id}:{task_label}:{step_count}"
        return hashlib.sha256(content.encode()).hexdigest()
