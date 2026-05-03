"""MCPSamplingPlanner — delegate LLM calls to the host via sampling/createMessage.

Drop-in replacement for `Planner` that doesn't need ANTHROPIC_API_KEY.
The host (Claude Code, MCP Inspector with sampling configured, etc.)
runs the LLM and returns the response. No keys, no separate SDK billing.

Probe `host_supports_sampling(ctx)` at call time; caller chains to
direct-Anthropic Planner, then to stubs, when the host doesn't advertise
the sampling capability.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional

import structlog
from mcp import types as mcp_types

from basicctrl.cognition.exceptions import CognitionDisabledError
from basicctrl.cognition.schemas import PlanCandidate

if TYPE_CHECKING:
    from mcp.server.fastmcp import Context

    from basicctrl.state.episodic import EpisodicMemory, EpisodicQuery
    from basicctrl.state.graph import StateGraph


log = structlog.get_logger(__name__)


class MCPSamplingPlanner:
    """Planner that uses MCP sampling (host-provided LLM).

    Constructed per-tool-call with the live FastMCP `Context` so the
    `create_message` JSON-RPC roundtrip targets the host that issued
    the request.
    """

    def __init__(
        self,
        ctx: "Context",
        episodic: Optional["EpisodicMemory"] = None,
        max_steps: int = 20,
        max_tokens: int = 2000,
    ):
        self.ctx = ctx
        self.episodic = episodic
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        # Parity with `Planner` — main.py's stub-fallback check looks at
        # `enabled` to decide between real path and stubs.
        self.enabled = True

    @classmethod
    def host_supports_sampling(cls, ctx: "Context") -> bool:
        """Probe client capabilities. True iff host advertised sampling."""
        try:
            return ctx.session.check_client_capability(
                mcp_types.ClientCapabilities(
                    sampling=mcp_types.SamplingCapability()
                )
            )
        except Exception:  # noqa: BLE001
            return False

    async def plan_action(
        self,
        task_description: str,
        current_state: "StateGraph",
        episodic_query: Optional["EpisodicQuery"] = None,
    ) -> PlanCandidate:
        """Plan via MCP sampling. Episodic-first per D-20."""
        # D-20: Episodic shortcut — same as Planner.plan_action.
        if self.episodic and episodic_query:
            hits = await self.episodic.lookup(episodic_query)
            if hits and hits[0].similarity > 0.85:
                log.info(
                    "sampling_planner.episodic_hit",
                    task=task_description,
                    similarity=hits[0].similarity,
                )
                recipe = hits[0].recipe
                return PlanCandidate(
                    steps=list(getattr(recipe, "steps", [])),
                    preconds=list(getattr(recipe, "preconditions", [])),
                    success_criteria=list(getattr(recipe, "success_criteria", [])),
                    bounded=True,
                )

        system_prompt = (
            "You are a task planner for a Mac automation system. "
            "Generate step-by-step plans (max 20 steps). Return ONLY a JSON "
            "object with keys: steps (list of action dicts with kind, "
            "target_key, action_type, payload), preconds (list), "
            "success_criteria (list of strings)."
        )
        state_app = getattr(current_state, "app", "?")
        state_node_count = len(getattr(current_state, "nodes", []))

        # α3: surface per-app skill markdown to the planner. Skills capture
        # the durable shape of the target app (URL/window patterns, stable
        # selectors, framework quirks, traps) — concrete prior knowledge the
        # planner would otherwise have to rediscover from scratch.
        skill_block = self._load_skill_context(state_app)

        user_msg_parts = [f"Task: {task_description}"]
        if skill_block:
            user_msg_parts.append(skill_block)
        user_msg_parts.append(
            f"Current state: app={state_app}, nodes={state_node_count}"
        )
        user_msg_parts.append("Generate a plan as JSON.")
        user_msg = "\n\n".join(user_msg_parts)

        try:
            result = await self.ctx.session.create_message(
                messages=[
                    mcp_types.SamplingMessage(
                        role="user",
                        content=mcp_types.TextContent(type="text", text=user_msg),
                    )
                ],
                max_tokens=self.max_tokens,
                system_prompt=system_prompt,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("sampling_planner.host_error", error=str(exc))
            raise CognitionDisabledError(
                module="MCPSamplingPlanner",
                reason=f"host sampling failed: {exc}",
            )

        text = getattr(result.content, "text", "") or ""
        try:
            plan_dict = self._extract_json(text)
        except (ValueError, json.JSONDecodeError) as exc:
            log.warning(
                "sampling_planner.parse_error",
                error=str(exc),
                text=text[:500],
            )
            return PlanCandidate(
                steps=[],
                preconds=[],
                success_criteria=[],
                bounded=True,
            )

        steps = list(plan_dict.get("steps", []))[: self.max_steps]
        return PlanCandidate(
            steps=steps,
            preconds=list(plan_dict.get("preconds", [])),
            success_criteria=list(plan_dict.get("success_criteria", [])),
            bounded=True,
        )

    def _load_skill_context(self, app_bundle_id: str) -> str:
        """Return per-app skill markdown for `app_bundle_id`, capped to a
        reasonable size. Empty string when no skills are filed for the app.

        Skills live at `basicctrl/skills/<bundle_id>/*.md`. Originally
        loader.py was dead code per its README — α3 wires it into planner
        prompts so the planner has concrete prior knowledge about the app
        (URL patterns, stable selectors, framework quirks, traps) instead
        of rediscovering it from scratch.
        """
        if not app_bundle_id or app_bundle_id == "?":
            return ""
        try:
            from basicctrl.skills.loader import read_all_skills

            blob = read_all_skills(app_bundle_id)
        except Exception as exc:  # noqa: BLE001
            log.debug("sampling_planner.skill_load_failed", error=str(exc))
            return ""
        if not blob:
            return ""
        # Cap at ~3K chars so planner prompts stay focused. Skills should be
        # the *map*, not the diary — anything longer is a smell anyway.
        if len(blob) > 3000:
            blob = blob[:3000] + "\n\n[truncated]"
        return f"App skill notes for {app_bundle_id}:\n\n{blob}"

    def _extract_json(self, text: str) -> dict[str, Any]:
        """Pull a JSON object out of a possibly-markdown-wrapped response."""
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        for fence in ("```json", "```"):
            if fence in text:
                start = text.find(fence) + len(fence)
                end = text.find("```", start)
                if end > start:
                    return json.loads(text[start:end].strip())
        raise ValueError(f"no JSON found in: {text[:200]}")
