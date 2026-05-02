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
from mcp.server.fastmcp import FastMCP

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
) -> dict[str, Any]:
    """Run RecoveryOrchestrator.attempt(...) when post.verified is False.

    Returns a dict suitable for inclusion in the healing-tool response. Always
    has a "ran" key (bool); when ran=True, also includes "succeeded",
    "branches_attempted", "terminal_event", and "events" (the recovery_log).

    Per F10 fix: until this hook existed, every verified=False action silently
    failed because RecoveryOrchestrator was orphaned. Now we hand back enough
    info that callers (and the host) can see the heal attempt + outcome.
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


async def register_healing_tools(
    proxy: FastMCP,
    upstream: ClientSession,
    deps: ProxyDeps,
    race_orch: RaceOrchestrator,
    recovery_orch: Optional[RecoveryOrchestrator] = None,
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
            recovery_orch, bundle_id, action, post, "click"
        )
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

    @proxy.tool(
        name="type_with_healing",
        description=(
            "Type text into a focused/labeled element. D-11: type is "
            "single-channel by default (each channel inserts text → race = "
            "duplicate chars)."
        ),
    )
    async def type_with_healing(
        text: str,
        bundle_id: str,
        pid: int,
        target_label: str = "",
        race_policy: Literal["auto", "race", "single_channel"] = "auto",
    ) -> dict[str, Any]:
        """D-11 — type_into_focused is single-channel."""
        t_start = time.monotonic()
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
            recovery_orch, bundle_id, action, post, "type_into_focused"
        )
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
            recovery_orch, bundle_id, action, post, action_type
        )
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
            recovery_orch, bundle_id, action, post, "set_value"
        )
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
    ) -> dict[str, Any]:
        """D-11/D-12 — orchestrator picks via resolve_race_policy.

        Dispatches `action_type="key_combo:<combo>"` so the prefix handler at
        race_policy._classify_intrinsic uses the SAFE_RACE_COMBOS / DESTRUCTIVE_COMBOS
        tables directly. SAFE combos (cmd+c, cmd+v) get RACE; destructive combos
        (cmd+s, cmd+enter, cmd+w, cmd+z) get SINGLE_CHANNEL automatically.
        """
        combo_lower = combo.lower().strip()
        action_type = f"key_combo:{combo_lower}"
        t_start = time.monotonic()
        action, post = await race_orch.execute(
            bundle_id=bundle_id,
            pid=pid,
            target_spec=TargetSpec(),
            action_type=action_type,
            payload={"combo": combo_lower},
            race_policy=_race_policy_from_string(race_policy),
            session_id=deps.session.session_id,
        )
        latency_ms = (time.monotonic() - t_start) * 1000.0
        recovery_info = await _maybe_recover(
            recovery_orch, bundle_id, action, post, action_type
        )
        return {
            "result": None,
            "session_id": deps.session.session_id,
            "phase": 2,
            "verified": post.verified,
            "confidence": post.confidence,
            "race": _build_race_outcome(action, post, latency_ms),
            "recovery": recovery_info,
            "note": f"Phase 2 key_combo_with_healing; combo={combo_lower}; type={action_type}",
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
        ],
        phase=2,
    )
