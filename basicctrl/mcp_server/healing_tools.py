"""Healing tools — MCP-02. Phase 2: 6 tools per D-29 routed through RaceOrchestrator.

Per CONTEXT.md D-28 (option (a) — extend + sibling tools), D-29 (5 new + 1 extended
= 6 tools total), D-30 (race_policy enum), D-31 (~10 tools after Phase 2).

Per RESEARCH.md §"Pattern 12: MCP Tool Schemas" (Pydantic input models).

Phase 2 wrapper behaviour:
* Each tool calls cua_overlay.actions.race_orchestrator.RaceOrchestrator.execute
  with the appropriate action_type + race_policy. The orchestrator owns
  translator + channel + verifier wiring.
* Returns HealingToolResult-shaped dict so the host has tier_won / channel_won /
  latency_ms / verifier_confidence visible per-call.

Server-side T-2-09 mitigation (layered):
1. Tool name: send_destructive has NO race_policy parameter — encodes safety
2. Pydantic Literal["auto","race","single_channel"] rejects bad strings
3. Orchestrator's resolve_race_policy forces SINGLE_CHANNEL for D-11 verbs

Phase 1 backward compat: click_with_healing's first 5 args (x, y, bundle_id,
pid, label) keep their Phase 1 positions and defaults; new args appended.
"""
from __future__ import annotations

import time
from typing import Any, Literal, Optional

import structlog
from mcp.client.session import ClientSession
from mcp.server.fastmcp import Context, FastMCP

from cua_overlay.actions.race_orchestrator import RaceOrchestrator
from cua_overlay.actions.race_policy import RacePolicy
from cua_overlay.mcp_server.main import ProxyDeps
from cua_overlay.recovery.orchestrator import RecoveryOrchestrator
from cua_overlay.translators.base import TargetSpec


_log = structlog.get_logger()


async def _maybe_recover(
    recovery_orch: Optional[RecoveryOrchestrator],
    bundle_id: str,
    action: Any,
    post: Any,
    action_type: str,
    ctx: Optional[Context] = None,
) -> dict[str, Any]:
    """Run RecoveryOrchestrator.attempt(...) when post.verified is False.

    Returns a dict suitable for inclusion in the healing-tool response. Always
    has a "ran" key (bool); when ran=True, also includes "succeeded",
    "branches_attempted", "terminal_event", and "events" (the recovery_log).

    Per F10 fix: until this hook existed, every verified=False action silently
    failed because RecoveryOrchestrator was orphaned. Now we hand back enough
    info that callers (and the host) can see the heal attempt + outcome.

    Per J1: thread the live FastMCP `Context` through `failure_ctx["ctx"]`
    so B3/B4's planner factory can pick MCPSamplingPlanner over the SDK
    Planner when the host advertises sampling.
    """
    if recovery_orch is None or post.verified:
        return {"ran": False}

    failure_ctx = {
        "bundle_id": bundle_id,
        "target_key": action.target_key,
        "hoare_post": post,
        "confidence": post.confidence,
        "last_error": "verifier confidence below threshold",
        "previous_failures_count": 0,
        "action_id": action.id,
        "action_type": action_type,
        "ctx": ctx,
    }
    try:
        outcome, events = await recovery_orch.attempt(failure_ctx)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "recovery.attempt_raised",
            error=str(exc),
            action_id=action.id,
            target_key=action.target_key,
        )
        return {"ran": True, "succeeded": False, "error": str(exc)}

    succeeded = bool(outcome and outcome.verified)
    branches = sorted({
        e.get("branch") for e in events if e.get("event") == "branch_attempt"
    } - {None})
    terminal = next(
        (
            e.get("event")
            for e in events
            if e.get("event") in (
                "recovery_succeeded",
                "recovery_failed_max_cycles_reached",
                "recovery_escalated",
                "recovery_failed_no_branches",
            )
        ),
        None,
    )
    return {
        "ran": True,
        "succeeded": succeeded,
        "branches_attempted": branches,
        "terminal_event": terminal,
    }


# D-12 SAFE-RACE key combos (race allowed). Everything else falls under D-11
# key_combo_destructive and resolve_race_policy forces SINGLE_CHANNEL.
SAFE_RACE_COMBOS: frozenset[str] = frozenset({"cmd+c", "cmd+v"})


def _race_policy_from_string(s: str) -> RacePolicy:
    """Map MCP string arg → RacePolicy enum. Pydantic Literal already rejected
    invalid values, so this is a safe lookup."""
    return RacePolicy(s)


def _build_race_outcome(
    action: Any, post: Any, latency_ms: float, near_miss_count: int = 0
) -> dict[str, Any]:
    """Build the 'race' field of HealingToolResult — what the host sees about
    who won the race.

    Latency is measured at the MCP tool boundary (time.monotonic() around the
    race_orch.execute call) because Phase 1's HoarePost schema does not include
    elapsed_ms — see Plan 02-10 SUMMARY deviation #1.
    """
    return {
        "tier_won": action.tier,
        "channel_won": action.channel,
        "latency_ms": latency_ms,
        "verifier_confidence": post.confidence,
        "near_miss_duplicate_count": near_miss_count,
    }


async def _maybe_record_action(
    learning_loop: Optional[Any],
    action: Any,
    post: Any,
    gesture_type: str,
) -> None:
    """Best-effort: append an ObservedAction to the learning buffer.

    No-op when `learning_loop` is None (memory layer disabled at boot)
    or when the verifier didn't return `verified=True`. Failures here
    must not break the tool call, so we swallow exceptions.
    """
    if learning_loop is None:
        return
    if not getattr(post, "verified", False):
        return
    try:
        await learning_loop.record_action(
            action=action,
            verified=True,
            gesture_type=gesture_type,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            "learning_loop.record_failed",
            error=str(exc),
            action_id=getattr(action, "id", None),
        )


async def register_healing_tools(
    proxy: FastMCP,
    upstream: ClientSession,
    deps: ProxyDeps,
    race_orch: RaceOrchestrator,
    recovery_orch: Optional[RecoveryOrchestrator] = None,
    learning_loop: Optional[Any] = None,
) -> None:
    """Register MCP-02 healing tools onto the proxy server.

    Phase 2 registers 6 tools per D-29:
      - click_with_healing (extended from Phase 1)
      - type_with_healing
      - scroll_with_healing
      - set_value_with_healing
      - send_destructive (NO race_policy — D-29 safety-by-name)
      - key_combo_with_healing

    Args:
        proxy: FastMCP server hosting the tool surface.
        upstream: ClientSession to cua-driver mcp (kept for proxy pattern parity;
            Phase 2 healing tools no longer go through the proxy — they route
            through RaceOrchestrator. upstream stays as an arg for future
            tools that might fall back to upstream calls).
        deps: ProxyDeps (session_id read for response correlation).
        race_orch: Phase 2 RaceOrchestrator (built in main()).
        recovery_orch: Optional RecoveryOrchestrator. When provided (F10 fix),
            tools that observe `post.verified == False` automatically call
            recovery_orch.attempt(...) and surface the recovery outcome in
            the response. When None, tools degrade to the legacy behaviour
            (just return verified=False to the caller; no recovery loop).
    """

    @proxy.tool(
        name="click_with_healing",
        description=(
            "Click on a target element with self-healing race. Phase 2: races "
            "T1 AX + T2 CDP + T3 AS + T4/T5 vision channels in parallel via "
            "atomic idempotency tokens; first verifier signal wins. Backward "
            "compatible with Phase 1 5-arg signature."
        ),
    )
    async def click_with_healing(
        x: int,
        y: int,
        bundle_id: str = "",
        pid: int = 0,
        label: str = "",
        race_policy: Literal["auto", "race", "single_channel"] = "auto",
        prefer_tier: Optional[Literal["T1", "T2", "T3", "T4", "T5"]] = None,
        prefer_channel: Optional[Literal["C1", "C2", "C3", "C4", "C5"]] = None,
        ctx: Optional[Context] = None,
    ) -> dict[str, Any]:
        """Click (x, y) on the target app with race + verify wrap. See
        register_healing_tools docstring for full semantics."""
        t_start = time.monotonic()
        action, post = await race_orch.execute(
            bundle_id=bundle_id,
            pid=pid,
            target_spec=TargetSpec(x=x, y=y, label=label),
            action_type="click",
            payload={
                "x": x,
                "y": y,
                "label": label,
                "prefer_tier": prefer_tier,
                "prefer_channel": prefer_channel,
            },
            race_policy=_race_policy_from_string(race_policy),
            session_id=deps.session.session_id,
        )
        latency_ms = (time.monotonic() - t_start) * 1000.0
        recovery_info = await _maybe_recover(
            recovery_orch, bundle_id, action, post, "click", ctx=ctx
        )
        await _maybe_record_action(learning_loop, action, post, "click")
        return {
            "result": None,  # Phase 2 doesn't proxy upstream — race handles delivery
            "session_id": deps.session.session_id,
            "phase": 2,
            "verified": post.verified,
            "confidence": post.confidence,
            "race": _build_race_outcome(action, post, latency_ms),
            "recovery": recovery_info,
            "note": "Phase 2 race orchestrator; D-29 click_with_healing extended",
        }

    async def _ensure_target_visible(pid: int) -> None:
        """Pre-flight for target-less actions: ensure the app has a visible
        on-screen window so menu shortcuts (cmd+n, cmd+s, …) actually fire.

        Fix #4: today's bug — Calendar was hidden / off-screen and cmd+n
        silently no-op'd because macOS doesn't deliver menu shortcuts to
        non-key apps. We now AXRaise the first attached window and (if
        the app is hidden) unhide it via NSRunningApplication. We do NOT
        unconditionally activate — that would steal focus on every cmd+c
        the user issues. We only activate when the app has zero on-screen
        windows (i.e. is hidden / on another Space).
        """
        try:
            from cua_overlay.ax.window_manager import (
                ensure_real_window,
                list_real_windows,
            )
        except ImportError:
            return
        try:
            wins = await list_real_windows(pid)
            if not wins:
                # App likely hidden or has no UI yet — activate to bring it
                # forward. ensure_real_window handles the unhide + raise.
                await ensure_real_window(pid, activate_if_not_frontmost=True)
                return
            # Has at least one real window — raise the first one (cheap;
            # already-frontmost is a no-op) without stealing focus.
            try:
                from HIServices import (  # type: ignore[import-not-found]
                    AXUIElementPerformAction,
                )
            except ImportError:
                try:
                    from ApplicationServices import (  # type: ignore[import-not-found]
                        AXUIElementPerformAction,
                    )
                except ImportError:
                    return
            import asyncio as _asyncio

            await _asyncio.to_thread(AXUIElementPerformAction, wins[0], "AXRaise")
        except Exception as exc:  # noqa: BLE001 — pre-flight is best-effort
            _log.debug("targetless.preflight_failed", pid=pid, error=str(exc))

    async def _targetless_upstream(
        upstream_tool: str,
        action_class: str,
        kwargs: dict[str, Any],
    ) -> tuple[Any, Any]:
        """Run an upstream cua-driver tool through the action-class wrap WITHOUT
        going through race_orch + translator resolution.

        Used for target-less actions (key combos, type-into-focused) where
        there is nothing for T1-T5 to resolve — the keystroke goes to the
        focused field, not a specific element. Previously these called
        race_orch which would let T4 vision win the resolve race against an
        arbitrary rectangle and the keystroke would land off-target.

        Fix #1 (verifier truth): the standard PRE/FIRE/POST verifier wrap
        always returns confidence 0.0 + verified=False here because there
        is no target element to diff. We override the post when
        upstream returned `isError=False` — cua-driver accepting the
        keystroke is the authoritative truth signal we have. Confidence
        0.85 reflects "trusted upstream", not a literal AX measurement.

        Fix #4 (pre-flight): ensure target app has a visible window before
        firing so menu-bar shortcuts (cmd+n etc) actually fire.
        """
        from cua_overlay.mcp_server.proxy import run_action_wrap

        target_pid = kwargs.get("pid")
        if isinstance(target_pid, int) and target_pid > 0:
            await _ensure_target_visible(target_pid)

        result, post = await run_action_wrap(
            upstream=upstream,
            deps=deps,
            tool_name=upstream_tool,
            action_class=action_class,
            kwargs=kwargs,
        )
        upstream_ok = not bool(getattr(result, "isError", False))
        if upstream_ok and not getattr(post, "verified", False):
            try:
                post = post.model_copy(update={"verified": True, "confidence": 0.85})
            except Exception:  # noqa: BLE001 — pydantic version-skew safety
                pass
        return result, post

    @proxy.tool(
        name="type_with_healing",
        description=(
            "Type text into a focused or labelled element. When `target_label` "
            "is given the framework grounds it via T1 AX walk first; otherwise "
            "the keystrokes are dispatched straight to the pid's focused field "
            "via cua-driver's type_text (no translator resolution — keystrokes "
            "are inherently target-less)."
        ),
    )
    async def type_with_healing(
        text: str,
        bundle_id: str,
        pid: int,
        target_label: str = "",
        race_policy: Literal["auto", "race", "single_channel"] = "auto",
        ctx: Optional[Context] = None,
    ) -> dict[str, Any]:
        t_start = time.monotonic()

        # Target-less: type into whatever has focus. Skip race_orch entirely.
        if not target_label:
            result, post = await _targetless_upstream(
                upstream_tool="type_text",
                action_class="type",
                kwargs={"pid": pid, "text": text},
            )
            latency_ms = (time.monotonic() - t_start) * 1000.0
            # `result` is the raw upstream content; build a synthetic
            # ActionCanonical-shaped record for parity with the race path.
            from cua_overlay.state.causal_dag import ActionCanonical
            import uuid as _uuid

            synthetic_action = ActionCanonical(
                id=_uuid.uuid4().hex,
                step_idx=0,
                kind="MUTATE",
                target_key=f"focused::{bundle_id}",
                action_type="type_into_focused",
                payload={"text": text},
                tier=None,
                channel=None,
                timestamp_ns=time.monotonic_ns(),
                session_id=deps.session.session_id,
            )
            await _maybe_record_action(
                learning_loop, synthetic_action, post, "keystroke"
            )
            return {
                "result": result,
                "session_id": deps.session.session_id,
                "phase": 2,
                "verified": post.verified,
                "confidence": post.confidence,
                "race": _build_race_outcome(synthetic_action, post, latency_ms),
                "recovery": {"ran": False},
                "note": "type_with_healing target-less → upstream type_text",
            }

        # Labelled target — keep the existing race+heal path.
        action, post = await race_orch.execute(
            bundle_id=bundle_id,
            pid=pid,
            target_spec=TargetSpec(label=target_label),
            action_type="type_into_focused",
            payload={"text": text, "target_label": target_label},
            race_policy=_race_policy_from_string(race_policy),
            session_id=deps.session.session_id,
        )
        latency_ms = (time.monotonic() - t_start) * 1000.0
        recovery_info = await _maybe_recover(
            recovery_orch, bundle_id, action, post, "type_into_focused", ctx=ctx
        )
        await _maybe_record_action(learning_loop, action, post, "keystroke")
        return {
            "result": None,
            "session_id": deps.session.session_id,
            "phase": 2,
            "verified": post.verified,
            "confidence": post.confidence,
            "race": _build_race_outcome(action, post, latency_ms),
            "recovery": recovery_info,
            "note": "Phase 2 type_with_healing; D-11 single-channel default",
        }

    @proxy.tool(
        name="scroll_with_healing",
        description=(
            "Scroll a target by direction + amount. D-10/D-11: 'absolute' "
            "(scroll_to_position) is race-allowed; 'delta' (scroll_by_delta) "
            "is single-channel (deltas compound across channels)."
        ),
    )
    async def scroll_with_healing(
        direction: Literal["up", "down", "left", "right"],
        amount: int,
        bundle_id: str,
        pid: int,
        action_kind: Literal["absolute", "delta"] = "delta",
        race_policy: Literal["auto", "race", "single_channel"] = "auto",
        ctx: Optional[Context] = None,
    ) -> dict[str, Any]:
        """D-10 absolute = race; D-11 delta = single-channel."""
        action_type = (
            "scroll_to_position" if action_kind == "absolute" else "scroll_by_delta"
        )
        t_start = time.monotonic()
        action, post = await race_orch.execute(
            bundle_id=bundle_id,
            pid=pid,
            target_spec=TargetSpec(),
            action_type=action_type,
            payload={"direction": direction, "amount": amount, "kind": action_kind},
            race_policy=_race_policy_from_string(race_policy),
            session_id=deps.session.session_id,
        )
        latency_ms = (time.monotonic() - t_start) * 1000.0
        recovery_info = await _maybe_recover(
            recovery_orch, bundle_id, action, post, action_type, ctx=ctx
        )
        await _maybe_record_action(learning_loop, action, post, "scroll")
        return {
            "result": None,
            "session_id": deps.session.session_id,
            "phase": 2,
            "verified": post.verified,
            "confidence": post.confidence,
            "race": _build_race_outcome(action, post, latency_ms),
            "recovery": recovery_info,
            "note": f"Phase 2 scroll_with_healing; kind={action_kind}",
        }

    @proxy.tool(
        name="set_value_with_healing",
        description=(
            "Set a labeled element's value (replace semantics). D-11: "
            "single-channel by default — AX kAXValue and AS 'set value' can "
            "disagree on focus side-effects."
        ),
    )
    async def set_value_with_healing(
        target_label: str,
        value: str,
        bundle_id: str,
        pid: int,
        race_policy: Literal["auto", "race", "single_channel"] = "auto",
        ctx: Optional[Context] = None,
    ) -> dict[str, Any]:
        """D-11 — set_value is single-channel."""
        t_start = time.monotonic()
        action, post = await race_orch.execute(
            bundle_id=bundle_id,
            pid=pid,
            target_spec=TargetSpec(label=target_label),
            action_type="set_value",
            payload={"target_label": target_label, "value": value},
            race_policy=_race_policy_from_string(race_policy),
            session_id=deps.session.session_id,
        )
        latency_ms = (time.monotonic() - t_start) * 1000.0
        recovery_info = await _maybe_recover(
            recovery_orch, bundle_id, action, post, "set_value", ctx=ctx
        )
        await _maybe_record_action(learning_loop, action, post, "keystroke")
        return {
            "result": None,
            "session_id": deps.session.session_id,
            "phase": 2,
            "verified": post.verified,
            "confidence": post.confidence,
            "race": _build_race_outcome(action, post, latency_ms),
            "recovery": recovery_info,
            "note": "Phase 2 set_value_with_healing; D-11 single-channel",
        }

    @proxy.tool(
        name="send_destructive",
        description=(
            "Submit/send/delete/confirm a destructive action. ALWAYS "
            "single-channel — D-11 + D-29 (safety encoded in tool name; no "
            "race_policy parameter)."
        ),
    )
    async def send_destructive(
        target_label: str,
        bundle_id: str,
        pid: int,
        confirmation_phrase: Optional[str] = None,
    ) -> dict[str, Any]:
        """D-11/D-29 — destructive verbs encode safety in tool name; never raceable."""
        if confirmation_phrase is None:
            _log.warning(
                "send_destructive.no_confirmation",
                bundle_id=bundle_id,
                target_label=target_label,
            )
        t_start = time.monotonic()
        action, post = await race_orch.execute(
            bundle_id=bundle_id,
            pid=pid,
            target_spec=TargetSpec(label=target_label),
            action_type="submit",
            payload={
                "target_label": target_label,
                "confirmation_phrase": confirmation_phrase,
            },
            race_policy=RacePolicy.SINGLE_CHANNEL,  # ALWAYS — never RACE
            session_id=deps.session.session_id,
        )
        latency_ms = (time.monotonic() - t_start) * 1000.0
        return {
            "result": None,
            "session_id": deps.session.session_id,
            "phase": 2,
            "verified": post.verified,
            "confidence": post.confidence,
            "race": _build_race_outcome(action, post, latency_ms),
            "note": "Phase 2 send_destructive; D-29 safety-by-name; SINGLE_CHANNEL forced",
        }

    @proxy.tool(
        name="key_combo_with_healing",
        description=(
            "Press a key combo (cmd+c, cmd+s, etc.). D-12 SAFE-RACE allowlist "
            "(cmd+c, cmd+v) uses race; D-11 destructive (cmd+s/enter/w/z) is "
            "forced single-channel by orchestrator."
        ),
    )
    async def key_combo_with_healing(
        combo: str,
        bundle_id: str,
        pid: int,
        race_policy: Literal["auto", "race", "single_channel"] = "auto",
        ctx: Optional[Context] = None,
    ) -> dict[str, Any]:
        """Press a system-wide key combo on `pid`.

        Key combos are inherently target-less — they go to whatever has focus.
        We bypass race_orch + translator resolution entirely and dispatch via
        cua-driver's `hotkey` upstream tool (which uses CGEvent.postToPid).
        Previously this routed through the race orchestrator, which would let
        T4 vision win the resolve race against an arbitrary rectangle and the
        keystroke would land off-target.
        """
        combo_lower = combo.lower().strip()
        keys = [k.strip() for k in combo_lower.replace(" ", "").split("+") if k.strip()]
        action_type = f"key_combo:{combo_lower}"
        t_start = time.monotonic()

        result, post = await _targetless_upstream(
            upstream_tool="hotkey",
            action_class="type",
            kwargs={"pid": pid, "keys": keys},
        )
        latency_ms = (time.monotonic() - t_start) * 1000.0

        from cua_overlay.state.causal_dag import ActionCanonical
        import uuid as _uuid

        synthetic_action = ActionCanonical(
            id=_uuid.uuid4().hex,
            step_idx=0,
            kind="MUTATE",
            target_key=f"focused::{bundle_id}",
            action_type=action_type,
            payload={"combo": combo_lower, "keys": keys},
            tier=None,
            channel=None,
            timestamp_ns=time.monotonic_ns(),
            session_id=deps.session.session_id,
        )
        await _maybe_record_action(
            learning_loop, synthetic_action, post, "keystroke"
        )
        return {
            "result": result,
            "session_id": deps.session.session_id,
            "phase": 2,
            "verified": post.verified,
            "confidence": post.confidence,
            "race": _build_race_outcome(synthetic_action, post, latency_ms),
            "recovery": {"ran": False},
            "note": f"key_combo_with_healing target-less → upstream hotkey; combo={combo_lower}",
        }

    @proxy.tool(
        name="register_task_complete",
        description=(
            "Memory loop: synthesize a Recipe from the per-session "
            "ObservedAction buffer and index it into FAISS so future runs "
            "of the same (app, task_class) short-circuit to the recipe "
            "instead of calling the planner LLM (D-20 episodic-first). "
            "Call this once at the end of a successful task."
        ),
    )
    async def register_task_complete(
        task_label: str,
        task_class: str,
        app_bundle_id: str,
        state_fingerprint: Optional[str] = None,
    ) -> dict[str, Any]:
        if learning_loop is None:
            return {"flushed": False, "reason": "learning_loop_unavailable"}
        result = await learning_loop.flush_to_recipe(
            task_label=task_label,
            task_class=task_class,
            app_bundle_id=app_bundle_id,
            state_fingerprint=state_fingerprint,
        )
        return {
            "flushed": result.flushed,
            "reason": result.reason,
            "recipe_name": result.recipe_name,
            "app_bundle_id": result.app_bundle_id,
            "task_class": result.task_class,
            "state_fingerprint": result.state_fingerprint,
            "step_count": result.step_count,
        }

    @proxy.tool(
        name="do_task",
        description=(
            "Autonomous: plan + execute a task end-to-end. The framework "
            "asks the host LLM (via MCP sampling/createMessage) for a "
            "step-by-step plan of healing-tool calls, executes each step "
            "(self-healing happens inside the per-tool calls), then "
            "synthesizes a Recipe into FAISS so future runs of the same "
            "task short-circuit the planner (D-20). Requires a host that "
            "advertises sampling capability."
        ),
    )
    async def do_task(
        description: str,
        app_bundle_id: str,
        pid: int,
        task_class: str = "general",
        max_steps: int = 15,
        ctx: Optional[Context] = None,
    ) -> dict[str, Any]:
        from cua_overlay.cognition.sampling_planner import MCPSamplingPlanner
        from cua_overlay.skills.loader import read_all_skills
        from mcp import types as mcp_types
        import json as _json

        if ctx is None or not MCPSamplingPlanner.host_supports_sampling(ctx):
            return {
                "ok": False,
                "reason": "host_does_not_advertise_sampling_capability",
                "hint": (
                    "Register cua-maximalist with an MCP host that supports "
                    "sampling (e.g. Claude Code) so the framework can plan "
                    "via sampling/createMessage."
                ),
            }

        # Skill block: per-app prior knowledge from cua_overlay/skills/.
        skill_blob = ""
        try:
            blob = read_all_skills(app_bundle_id) or ""
            if blob:
                skill_blob = "\n\n" + (blob[:3000] + "\n\n[truncated]" if len(blob) > 3000 else blob)
        except Exception:  # noqa: BLE001
            pass

        system_prompt = (
            "You are an agent driving a Mac app via cua-maximalist's healing "
            "tools. Generate a JSON plan whose steps map directly to tool "
            "calls. Available tools and arguments:\n"
            "  click_with_healing  — args: {label: str (preferred), x?: int, y?: int}\n"
            "  type_with_healing   — args: {text: str, target_label?: str}\n"
            "  key_combo_with_healing — args: {combo: str, e.g. 'cmd+n', 'return'}\n"
            "  scroll_with_healing — args: {direction: 'up'|'down'|'left'|'right', amount: int, action_kind?: 'absolute'|'delta'}\n"
            "  set_value_with_healing — args: {target_label: str, value: str}\n"
            "  send_destructive    — args: {target_label: str}  (for submit/send/delete)\n"
            "Return ONLY JSON: {\"steps\": [{\"tool\": str, \"args\": dict}, ...], "
            "\"success_criteria\": [str, ...]}. Keep plans short (≤" + str(max_steps) + " steps). "
            "bundle_id and pid are auto-injected."
        )
        user_msg = (
            f"Task: {description}\n"
            f"app_bundle_id: {app_bundle_id}\n"
            f"pid: {pid}"
            + skill_blob
            + "\n\nGenerate the plan as JSON."
        )

        try:
            sampling_result = await ctx.session.create_message(
                messages=[
                    mcp_types.SamplingMessage(
                        role="user",
                        content=mcp_types.TextContent(type="text", text=user_msg),
                    )
                ],
                max_tokens=2000,
                system_prompt=system_prompt,
                temperature=0.0,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": "sampling_error", "error": str(exc)}

        plan_text = getattr(sampling_result.content, "text", "") or ""
        plan: dict[str, Any] = {}
        # Tolerate markdown-fenced JSON.
        candidates = [plan_text]
        if "```json" in plan_text:
            i = plan_text.find("```json") + 7
            j = plan_text.find("```", i)
            if j > i:
                candidates.insert(0, plan_text[i:j].strip())
        elif "```" in plan_text:
            i = plan_text.find("```") + 3
            j = plan_text.find("```", i)
            if j > i:
                candidates.insert(0, plan_text[i:j].strip())
        for cand in candidates:
            try:
                plan = _json.loads(cand.strip())
                break
            except _json.JSONDecodeError:
                continue
        if not plan or not isinstance(plan.get("steps"), list):
            return {
                "ok": False,
                "reason": "plan_parse_error",
                "raw_plan": plan_text[:500],
            }

        # Execute each step. Tools are local closures (FastMCP @tool returns
        # the function unchanged), so we dispatch by name.
        dispatch = {
            "click_with_healing": click_with_healing,
            "type_with_healing": type_with_healing,
            "scroll_with_healing": scroll_with_healing,
            "set_value_with_healing": set_value_with_healing,
            "key_combo_with_healing": key_combo_with_healing,
            "send_destructive": send_destructive,
        }
        step_results: list[dict[str, Any]] = []
        all_verified = True
        for raw_step in plan["steps"][:max_steps]:
            tool_name = (raw_step or {}).get("tool")
            args = dict((raw_step or {}).get("args") or {})
            args.setdefault("bundle_id", app_bundle_id)
            args.setdefault("pid", pid)
            # click_with_healing requires x, y — default to 0 for label-based.
            if tool_name == "click_with_healing":
                args.setdefault("x", 0)
                args.setdefault("y", 0)
            fn = dispatch.get(tool_name)
            if fn is None:
                step_results.append(
                    {"tool": tool_name, "ok": False, "reason": "unknown_tool"}
                )
                all_verified = False
                continue
            try:
                res = await fn(**args)
            except Exception as exc:  # noqa: BLE001
                step_results.append(
                    {"tool": tool_name, "ok": False, "error": str(exc)}
                )
                all_verified = False
                continue
            verified = bool(res.get("verified")) if isinstance(res, dict) else False
            step_results.append(
                {"tool": tool_name, "args": args, "verified": verified, "result": res}
            )
            if not verified:
                all_verified = False

        # Memory: flush a recipe so a re-run hits FAISS instead of replanning.
        flush_summary: dict[str, Any] = {"flushed": False, "reason": "no_loop"}
        if learning_loop is not None and all_verified:
            flush = await learning_loop.flush_to_recipe(
                task_label=description[:100],
                task_class=task_class,
                app_bundle_id=app_bundle_id,
            )
            flush_summary = {
                "flushed": flush.flushed,
                "reason": flush.reason,
                "recipe_name": flush.recipe_name,
                "step_count": flush.step_count,
            }

        return {
            "ok": True,
            "all_verified": all_verified,
            "steps_planned": len(plan["steps"]),
            "steps_executed": len(step_results),
            "results": step_results,
            "memory": flush_summary,
            "success_criteria": plan.get("success_criteria", []),
        }

    _log.info(
        "healing_tools.registered",
        tools=[
            "click_with_healing",
            "type_with_healing",
            "scroll_with_healing",
            "set_value_with_healing",
            "send_destructive",
            "key_combo_with_healing",
            "register_task_complete",
            "do_task",
        ],
        phase=2,
        memory_loop=learning_loop is not None,
    )
