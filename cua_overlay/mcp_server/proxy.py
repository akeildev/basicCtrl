"""Proxy logic — mirror upstream tools + verifier wrap for action-class tools.

Per Plan 01-08 Task 2:

* ``ACTION_CLASS_TOOLS`` — verbatim mapping from upstream ``cua-driver mcp``
  tool names (per ``ToolRegistry.swift::actionToolNames`` lines 34-45) to a
  small canonical action class (``click`` / ``scroll`` / ``type`` /
  ``set_value``) that ``WeightedVote`` keys on.

* ``register_proxied_tool(proxy, upstream, tool, deps)`` — registers ONE
  upstream tool against the FastMCP proxy server:

    - If the tool is action-class: wrap with PRE-snapshot + DELEGATE +
      POST-aggregate. The verifier ladder runs after the upstream call returns.
      The Hoare triple is appended to ``deps.session.action_log.ndjson`` AND
      checkpointed via ``deps.durable.checkpoint`` (best-effort: a Postgres
      hiccup is logged but does not fail the MCP call).

    - Else: straight passthrough — ``await upstream.call_tool(tool.name, kwargs)``
      and return the result content.

The wrap is deliberately sequential rather than racing: Phase 1 ships the
contract, Phase 3 adds the 5-branch parallel recovery. Phase 1 wrappers do
not retry; they observe + log + return.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP
from mcp.types import Tool

from cua_overlay.mcp_server.main import ProxyDeps
from cua_overlay.state.causal_dag import ActionCanonical, HoarePre
from cua_overlay.state.graph import Bbox, UIElement
from cua_overlay.verifier.ensemble.l1_cheap import L1Cheap


# ACTION_CLASS_TOOLS — verbatim per Plan 01-08 ``<interfaces>`` block. Maps every
# action-class upstream tool name to the canonical action class that
# ``WeightedVote.WEIGHTS`` keys on.
#
# Source: ``libs/cua-driver/Sources/CuaDriverServer/ToolRegistry.swift::actionToolNames``
# (verified at planning time; see RESEARCH.md MCP proxy section).
ACTION_CLASS_TOOLS: dict[str, str] = {
    "click": "click",
    "right_click": "click",
    "drag": "click",
    "scroll": "scroll",
    "page": "scroll",
    "type_text": "type",
    "type_text_chars": "type",
    "press_key": "type",
    "hotkey": "type",
    "set_value": "set_value",
}


# Module-level monotonic step counter. Each action-class tool call increments
# this so the action_log carries an explicit step_idx that round-trips through
# Postgres (Plan 07's DurableExecutor.checkpoint expects step_idx).
_step_counter: dict[str, int] = {"value": 0}


_log = structlog.get_logger()


def _build_minimal_target(kwargs: dict[str, Any], session_id: str) -> UIElement:
    """Build a minimal ``UIElement`` from kwargs for the verifier ladder.

    Phase 1 the upstream tool call carries (x, y, bundle_id, pid, label) — that
    is enough to populate ``UIElement`` for the verifier's purposes (we mainly
    need ``composite_key`` and ``bbox`` so L1Cheap can hash a 100×100 ROI).

    Args:
        kwargs: tool-call arguments (e.g. ``{"x": 100, "y": 200, "bundle_id":
            "com.apple.calculator", "pid": 12345, "label": "5"}``).
        session_id: passed through for trace continuity but not stored on the
            UIElement (UIElement schema doesn't carry session_id).

    Returns:
        UIElement with role="AXButton" and a 20×20 bbox centred on (x, y). The
        actual element identity is unknown at proxy-time — Phase 2 the
        translator layer fills the AX subtree before reaching us.
    """
    now = datetime.now(timezone.utc)
    x = float(kwargs.get("x", 0))
    y = float(kwargs.get("y", 0))
    return UIElement(
        role="AXButton",
        role_path="AXApplication/AXButton[?]",
        label=str(kwargs.get("label", "")),
        bbox=Bbox(x=x, y=y, w=20.0, h=20.0),
        discovered_at=now,
        last_seen_at=now,
        pid=int(kwargs.get("pid", 0)),
        bundle_id=str(kwargs.get("bundle_id", "")),
        window_id=int(kwargs.get("window_id", 0)),
    )


async def register_proxied_tool(
    proxy: FastMCP,
    upstream: ClientSession,
    tool: Tool,
    deps: ProxyDeps,
) -> None:
    """Mirror ONE upstream tool into the proxy server.

    For action-class tools (``tool.name in ACTION_CLASS_TOOLS``), the registered
    function:

    1. Builds a minimal ``UIElement`` target from the call arguments.
    2. Captures ``HoarePre`` and the L1 baseline snapshot BEFORE firing.
    3. Delegates to the upstream tool via ``upstream.call_tool``.
    4. Runs ``deps.aggregator.verify`` to compute the post-state confidence.
    5. Appends a Hoare-triple line to ``deps.session.action_log.ndjson`` AND
       (best-effort) writes a Postgres checkpoint via ``deps.durable``.
    6. Returns the upstream result's ``.content`` (the MCP host expects the
       same shape as the underlying tool would have returned).

    For non-action tools (e.g. ``screenshot``, ``list_tools_meta``), the
    registered function is a straight passthrough — no verifier, no log line,
    no checkpoint.

    Args:
        proxy: the FastMCP server hosting our tool surface.
        upstream: the ClientSession to ``cua-driver mcp`` — we forward calls
            through it.
        tool: the upstream tool definition (name + description + schema).
        deps: shared verifier + persistence dependencies.
    """
    tool_name = tool.name

    if tool_name not in ACTION_CLASS_TOOLS:
        # Non-action tool — straight passthrough. No verifier wrap because there
        # is no UI mutation to verify.
        async def _passthrough(**kwargs: Any) -> Any:
            result = await upstream.call_tool(tool_name, arguments=kwargs)
            return result.content if hasattr(result, "content") else result

        # Preserve the upstream tool's name + description so the proxy looks
        # identical to the original from the host's perspective.
        proxy.add_tool(
            _passthrough,
            name=tool_name,
            description=tool.description or "",
        )
        _log.info("registered.passthrough", tool=tool_name)
        return

    # Action-class wrap: PRE-snapshot, FIRE, POST-aggregate, LOG, CHECKPOINT.
    action_class = ACTION_CLASS_TOOLS[tool_name]

    async def _wrapped(**kwargs: Any) -> Any:
        action_id = uuid.uuid4().hex
        _step_counter["value"] += 1
        step_idx = _step_counter["value"]
        t_start = time.monotonic()

        target = _build_minimal_target(kwargs, deps.session.session_id)

        pre = HoarePre(
            target_key=target.composite_key,
            target_exists=True,
            target_enabled=True,
            target_role=target.role,
            role_compatible=True,
            frontmost_app=str(kwargs.get("bundle_id", "")),
            no_blocking_modal=True,
            timestamp_ns=time.monotonic_ns(),
        )

        # PRE: capture L1 baseline so the post-action diff is apples-to-apples.
        l1_before = await L1Cheap().snapshot(target)

        # FIRE: delegate to upstream.
        result = await upstream.call_tool(tool_name, arguments=kwargs)

        # Build the canonical action record. ``payload`` is the kwargs the
        # caller supplied; ``id`` doubles as the ACT-03 idempotency token;
        # ``kind = "MUTATE"`` because every action-class tool is a mutation.
        action = ActionCanonical(
            id=action_id,
            step_idx=step_idx,
            kind="MUTATE",
            target_key=target.composite_key,
            action_type=action_class,
            payload=dict(kwargs),
            tier=None,
            channel=None,
            timestamp_ns=time.monotonic_ns(),
            session_id=deps.session.session_id,
        )

        # POST: aggregate verifier signals. Phase 1 with no AX element ref the
        # L0 layer drains push events without subscribing to a specific element;
        # L1 fires the cheap-diff. L2/L3 are skipped because before_l2 is None.
        post = await deps.aggregator.verify(
            action=action,
            target=target,
            notifs=["AXValueChanged", "AXFocusedUIElementChanged"],
            before_l1=l1_before,
            ax_element=None,
            timeout_ms=50,
        )

        elapsed_ms = (time.monotonic() - t_start) * 1000.0

        # LOG: append one NDJSON line per Hoare triple. The structlog redactor
        # strips sensitive field names (T-1-03); this writer is a raw sink so
        # callers must not pass pasteboard payload strings — kwargs are the
        # tool arguments which are coordinates / labels, never clipboard.
        deps.session.append_action_log(
            {
                "step_idx": step_idx,
                "action_id": action_id,
                "tool": tool_name,
                "action_type": action_class,
                "pre": pre.model_dump(mode="json"),
                "action": action.model_dump(mode="json"),
                "post": post.model_dump(mode="json"),
                "elapsed_ms": elapsed_ms,
            }
        )

        # CHECKPOINT: best-effort Postgres write via DurableExecutor. A failure
        # here does NOT abort the MCP call — the MCP host expects the upstream
        # result, and missing a checkpoint just means a slower resume on crash.
        try:
            await deps.durable.checkpoint(
                session_id=deps.session.session_id,
                step_idx=step_idx,
                pre=pre,
                action=action,
                post=post,
            )
        except Exception as exc:  # noqa: BLE001 — Postgres flaps must never
            # cascade into MCP call failure.
            _log.warning(
                "durable.checkpoint_failed",
                error=str(exc),
                step_idx=step_idx,
                action_id=action_id,
            )

        return result.content if hasattr(result, "content") else result

    proxy.add_tool(
        _wrapped,
        name=tool_name,
        description=tool.description or "",
    )
    _log.info("registered.action_class", tool=tool_name, action_class=action_class)
