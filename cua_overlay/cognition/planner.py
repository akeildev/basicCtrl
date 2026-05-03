"""Planner agent (D-03) — Opus 4.x with prompt caching.

Per D-03 (04-CONTEXT.md): Opus planner with bounded max_steps=20.
Per D-20: Query episodic memory BEFORE LLM call.

Returns PlanCandidate{steps, preconds, success_criteria, bounded}.

Prompt caching: enabled on system prompt via cache_control={"type": "ephemeral"}.
Episodic-first: calls episodic.lookup(EpisodicQuery(...)) before constructing prompt.
"""
from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Optional

import structlog
from pydantic import ValidationError

from cua_overlay.cognition.exceptions import CognitionDisabledError
from cua_overlay.cognition.schemas import PlanCandidate

if TYPE_CHECKING:
    from cua_overlay.state.causal_dag import ActionCanonical, HoarePre
    from cua_overlay.state.episodic import EpisodicHit, EpisodicMemory, EpisodicQuery
    from cua_overlay.state.graph import StateGraph


log = structlog.get_logger(__name__)


class Planner:
    """Opus 4.x planner with prompt caching and episodic lookup.

    D-03: Bounded plan generation (max_steps=20).
    D-20: Query episodic memory before any LLM call.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        episodic: Optional[EpisodicMemory] = None,
        max_steps: int = 20,
        client: Optional[Any] = None,
    ):
        """Initialize planner.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            episodic: Optional EpisodicMemory instance for D-20 lookup
            max_steps: Maximum plan steps (default 20, bounded per D-03)
            client: Optional pre-initialized Anthropic client (for testing)
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            log.warning("planner.disabled", reason="no_api_key", env="ANTHROPIC_API_KEY")
            raise CognitionDisabledError(
                module="Planner", reason="ANTHROPIC_API_KEY not set"
            )

        self.episodic = episodic
        self.max_steps = max_steps
        self.client = client
        self._client_initialized = client is not None

    def _get_client(self):
        """Get or create anthropic client."""
        if not self._client_initialized:
            import anthropic

            self.client = anthropic.Anthropic(api_key=self.api_key)
            self._client_initialized = True
        return self.client

    async def plan_action(
        self,
        task_description: str,
        current_state: StateGraph,
        episodic_query: Optional[EpisodicQuery] = None,
    ) -> PlanCandidate:
        """Plan action sequence (D-03, D-20).

        Per D-20: Query episodic memory BEFORE LLM call.
        If episodic returns high-confidence hit (similarity > 0.85),
        adapt the returned recipe instead of re-planning.

        Args:
            task_description: High-level goal (e.g., "search for Python")
            current_state: Current StateGraph snapshot
            episodic_query: Optional pre-built EpisodicQuery for lookup

        Returns:
            PlanCandidate with steps, preconds, success_criteria, bounded=True
        """
        # D-20: Episodic lookup BEFORE LLM call
        episodic_hits: list[EpisodicHit] = []
        if self.episodic and episodic_query:
            log.info("planner.episodic_lookup", task=task_description)
            episodic_hits = await self.episodic.lookup(episodic_query)
            if episodic_hits and episodic_hits[0].similarity > 0.85:
                log.info(
                    "planner.episodic_hit",
                    task=task_description,
                    similarity=episodic_hits[0].similarity,
                )
                # Adapt the recipe from episodic memory (D-20 optimization)
                recipe = episodic_hits[0].recipe
                steps = [
                    step
                    for step in getattr(recipe, "steps", [])
                    if len(steps) <= self.max_steps
                ]
                return PlanCandidate(
                    steps=steps,
                    preconds=getattr(recipe, "preconditions", []),
                    success_criteria=getattr(recipe, "success_criteria", []),
                    bounded=True,
                )

        # No episodic hit (or episodic disabled): call Opus planner
        log.info(
            "planner.llm_call",
            task=task_description,
            episodic_hit=len(episodic_hits) > 0,
        )

        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(task_description, current_state)

        # Call Opus with prompt caching (D-03)
        response = self._get_client().messages.create(
            model="claude-opus-4-1-20250805",
            max_tokens=2000,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},  # D-03 prompt caching
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": user_message,
                }
            ],
        )

        # Parse response into PlanCandidate
        try:
            content = response.content[0].text
            # Extract JSON from response (assume it's wrapped in markdown code block or raw)
            plan_dict = self._extract_json_from_response(content)
            log.info("planner.parsed", plan_dict=plan_dict)

            # Enforce max_steps bound (D-03)
            steps = plan_dict.get("steps", [])
            if len(steps) > self.max_steps:
                log.warning(
                    "planner.truncated",
                    original_steps=len(steps),
                    max_steps=self.max_steps,
                )
                steps = steps[: self.max_steps]

            return PlanCandidate(
                steps=steps,
                preconds=plan_dict.get("preconds", []),
                success_criteria=plan_dict.get("success_criteria", []),
                bounded=True,
            )
        except (ValidationError, KeyError, json.JSONDecodeError) as e:
            log.error("planner.parse_error", error=str(e), response=content)
            # Return minimal fallback plan
            return PlanCandidate(
                steps=[],
                preconds=[],
                success_criteria=[],
                bounded=True,
            )

    def _build_system_prompt(self) -> str:
        """Build system prompt with bounded generation context."""
        return (
            "You are a task planner for a Mac automation system. "
            "Generate step-by-step plans to achieve user goals. "
            "Keep plans SHORT and BOUNDED: maximum 20 steps. "
            "Return a JSON object with keys: steps, preconds, success_criteria. "
            "steps: list of ActionCanonical steps (each is a dict with: kind, target_key, action_type, payload). "
            "preconds: list of HoarePre pre-conditions. "
            "success_criteria: list of assertion strings. "
            "Do NOT exceed 20 steps under any circumstances."
        )

    def _build_user_message(
        self, task_description: str, current_state: StateGraph
    ) -> str:
        """Build user message with task + state + per-app skills context."""
        state_summary = self._serialize_state(current_state)
        skills = self._load_skill_context(getattr(current_state, "app", ""))
        parts = [f"Task: {task_description}"]
        if skills:
            parts.append(skills)
        parts.append(f"Current state:\n{state_summary}")
        parts.append("Generate a plan as JSON.")
        return "\n\n".join(parts)

    def _load_skill_context(self, app_bundle_id: str) -> str:
        """α3: surface per-app skill markdown to the planner prompt.

        Skills live at `cua_overlay/skills/<bundle_id>/*.md`. They were
        previously dead code; this wires them in so the LLM has prior
        knowledge about the target app instead of rediscovering it.
        """
        if not app_bundle_id or app_bundle_id in ("?", "unknown"):
            return ""
        try:
            from cua_overlay.skills.loader import read_all_skills

            blob = read_all_skills(app_bundle_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("planner.skill_load_failed", error=str(exc))
            return ""
        if not blob:
            return ""
        if len(blob) > 3000:
            blob = blob[:3000] + "\n\n[truncated]"
        return f"App skill notes for {app_bundle_id}:\n\n{blob}"

    def _serialize_state(self, state: StateGraph) -> str:
        """Serialize StateGraph to compact string."""
        # Simplified serialization; real implementation would be more detailed
        return f"StateGraph(app={getattr(state, 'app', 'unknown')}, nodes={len(getattr(state, 'nodes', []))})"

    def _extract_json_from_response(self, content: str) -> dict[str, Any]:
        """Extract JSON from response (handles markdown code blocks)."""
        # Try direct JSON parse first
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code block
        if "```json" in content:
            start = content.find("```json") + len("```json")
            end = content.find("```", start)
            if end > start:
                return json.loads(content[start:end].strip())

        # Try to extract from raw ``` block
        if "```" in content:
            start = content.find("```") + 3
            end = content.find("```", start)
            if end > start:
                return json.loads(content[start:end].strip())

        raise json.JSONDecodeError("Could not extract JSON from response", content, 0)


class WorldModelPredictor:
    """CUWM-style world-model predictor (D-07).

    Predicts post-state before action fires. Output: PredictedState with
    ax_delta, screenshot_phash_delta, expected_notifs.

    Used by B3 recovery branch (recovery/branches/b3_world_replan.py).
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize world-model predictor.

        Phase 4 ships only the heuristic path; the api_key is reserved for a
        future small-model upgrade. We accept a missing key so B3 can still
        replan via MCPSamplingPlanner without an Anthropic SDK key.

        Args:
            api_key: Anthropic API key for the future small specialized
                model. Optional — heuristic prediction works without it.
        """
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self._client = None
        if not self.api_key:
            log.info(
                "world_model.heuristic_only",
                reason="no_api_key",
                env="ANTHROPIC_API_KEY",
            )

    @property
    def client(self):
        """Lazy import of anthropic client."""
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    async def predict(
        self,
        action: ActionCanonical,
        current_state: StateGraph,
    ) -> dict[str, Any]:
        """Predict post-state before action fires (D-07).

        Args:
            action: The action about to be executed
            current_state: Current StateGraph

        Returns:
            dict with keys: ax_delta, screenshot_phash_delta, expected_notifs
        """
        log.info("world_model.predict", action_type=action.action_type)

        # For Phase 4, use heuristic rules (deterministic, no LLM call)
        # In Phase 5+, could upgrade to a specialized small model
        prediction = self._heuristic_predict(action, current_state)
        log.info("world_model.predicted", prediction=prediction)
        return prediction

    def _heuristic_predict(
        self, action: ActionCanonical, current_state: StateGraph
    ) -> dict[str, Any]:
        """Heuristic prediction for Phase 4 (deterministic rules).

        Returns dict with ax_delta, screenshot_phash_delta, expected_notifs.
        """
        # Default: most clicks set AXValue + cause a notification
        # Refined prediction would be per-app-specific
        return {
            "ax_delta": {
                "expected_changes": ["AXValue", "AXTitle"],
                "expected_removals": [],
            },
            "screenshot_phash_delta": "",  # Empty for phase 4 heuristic
            "expected_notifs": ["kAXValueChanged", "kAXUIElementCreated"],
        }
