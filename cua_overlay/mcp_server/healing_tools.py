"""Healing tools — MCP-02. Phase 1: ``click_with_healing``.

Per Plan 01-08 Task 2 step 2: register healing-wrapper tools alongside the
mirrored upstream tools. Phase 1 ships ``click_with_healing`` only.

Phase 1 wrapper behaviour:

* Calls the upstream ``click`` tool through the same MCP ClientSession that
  ``register_proxied_tool`` uses.
* Returns ``{"result": <upstream content>, "session_id": <writer.session_id>,
  "phase": 1, "note": ...}`` so the host can correlate the call with the
  per-session ``~/.cua/sessions/<id>/action_log.ndjson``.

Phase 3 will swap the body for the 5-branch parallel recovery (race AX click
+ AppleScript click + CGEvent click + CDP click + Vision-grounded click; first
verified channel wins; cache the winner for next time).

This is a deliberately thin wrapper — the heavy lifting lives in the proxied
``click`` tool's verifier wrap (``register_proxied_tool``). The healing tool
exists primarily so MCP hosts can DISCOVER the cua-maximalist surface — when
they see ``click_with_healing`` in ``list_tools``, they know they're talking
to a self-healing proxy and not a vanilla cua-driver.
"""
from __future__ import annotations

from typing import Any

import structlog
from mcp.client.session import ClientSession
from mcp.server.fastmcp import FastMCP

from cua_overlay.mcp_server.main import ProxyDeps
from cua_overlay.mcp_server.proxy import run_action_wrap


_log = structlog.get_logger()


async def register_healing_tools(
    proxy: FastMCP,
    upstream: ClientSession,
    deps: ProxyDeps,
) -> None:
    """Register MCP-02 healing-wrapper tools onto the proxy server.

    Phase 1 registers ``click_with_healing`` only. Future phases extend with
    ``type_text_with_healing``, ``scroll_with_healing``, etc.

    Args:
        proxy: the FastMCP server hosting our tool surface.
        upstream: the ClientSession to ``cua-driver mcp`` — we forward
            individual click calls through it.
        deps: shared verifier + persistence dependencies (session_id is read
            from ``deps.session.session_id``).
    """

    @proxy.tool(
        name="click_with_healing",
        description=(
            "Click on a target element with self-healing recovery. Phase 1: "
            "delegates to the upstream cua-driver `click` tool, runs the "
            "L0+L1 verifier ladder, and writes a Hoare-triple line to the "
            "session action log. Phase 3 will add 5-branch parallel recovery "
            "(race AX + AppleScript + CGEvent + CDP + Vision-grounded clicks; "
            "first verified channel wins; cache the winner)."
        ),
    )
    async def click_with_healing(
        x: int,
        y: int,
        bundle_id: str = "",
        pid: int = 0,
        label: str = "",
    ) -> dict[str, Any]:
        """Click ``(x, y)`` on the target app with verifier wrap.

        Args:
            x: screen-coordinate X (top-left origin).
            y: screen-coordinate Y.
            bundle_id: target app bundle ID (e.g. ``com.apple.calculator``).
            pid: target process ID. If 0, the upstream tool resolves it from
                the bundle_id.
            label: optional human-readable label (e.g. ``"5"`` for the digit-5
                button on Calculator). Used for logging + UI-element
                fingerprinting.

        Returns:
            dict shaped::

                {
                    "result": <upstream click result content>,
                    "session_id": <SessionWriter.session_id>,
                    "phase": 1,
                    "note": "Phase 1 wrapper; Phase 3 adds 5-branch recovery + cache write-back"
                }
        """
        result, post = await run_action_wrap(
            upstream=upstream,
            deps=deps,
            tool_name="click",
            action_class="click",
            kwargs={
                "x": x,
                "y": y,
                "bundle_id": bundle_id,
                "pid": pid,
                "label": label,
            },
        )
        return {
            "result": result.content if hasattr(result, "content") else str(result),
            "session_id": deps.session.session_id,
            "phase": 1,
            "verified": post.verified,
            "confidence": post.confidence,
            "note": (
                "Phase 1 wrapper; Phase 3 will add 5-branch recovery + cache write-back"
            ),
        }

    _log.info("healing_tools.registered", tools=["click_with_healing"])
