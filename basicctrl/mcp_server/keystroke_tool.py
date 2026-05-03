"""mcp__basicCtrl__keystroke_with_healing — terminal-app keystroke tool.

For sending text into terminal-class apps (Ghostty, iTerm2, Terminal.app,
Warp, Alacritty, kitty) where AX text-insert lands in the wrong place
because terminal panes draw to a framebuffer, not into AXTextArea cells.

Wraps ``basicctrl.browser.keystroke_heal.keystroke_to_window_with_retry``
with the activate-once + verify-before-send + title-flip-verify pattern.
See that module's docstring for the race this fixes.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog
from mcp.server.fastmcp import FastMCP


_log = structlog.get_logger()


async def _run_in_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


def register_keystroke_tool(proxy: FastMCP) -> None:
    """Register mcp__basicCtrl__keystroke_with_healing on the proxy."""

    @proxy.tool(
        name="keystroke_with_healing",
        description=(
            "Send text into a terminal-class app's currently-focused tab "
            "with self-heal verify. Use for Ghostty, iTerm2, Terminal.app, "
            "Warp, Alacritty, kitty — anywhere AX text-insert lands wrong "
            "because the pane is a framebuffer, not AXTextArea cells.\n\n"
            "Self-heal layers:\n"
            "  L1 pre-verify  — front-window title must contain "
            "target_title_substr; otherwise abort (don't type into wrong tab)\n"
            "  L2 no re-activate — `tell app to activate` is ONLY fired once "
            "at the start; re-firing causes the focus race\n"
            "  L3 post-verify — poll for title-prefix flip "
            "(✳ idle → spinner) as success signal\n\n"
            "Args:\n"
            "  app_name             — macOS app name (\"Ghostty\")\n"
            "  target_title_substr  — substring expected in front-window title\n"
            "  text                 — payload to type\n"
            "  with_return          — append Return after text (default true)\n"
            "  tab_switch_hotkey    — if set (e.g. \"4\"), send cmd+<key> first\n"
            "  max_retries          — re-cycle + verify on L1 mismatch (default 1)\n\n"
            "Returns: {ok, verified, pre_title, post_title, attempts, reason?}.\n"
            "  ok=True       → keystroke was sent (passed L1 pre-verify)\n"
            "  verified=True → observed title-flip (passed L3 post-verify)\n"
            "  reason        → diagnostic when ok or verified is False"
        ),
    )
    async def keystroke_with_healing(
        app_name: str,
        target_title_substr: str,
        text: str,
        with_return: bool = True,
        tab_switch_hotkey: Optional[str] = None,
        max_retries: int = 1,
        settle_seconds: float = 0.6,
        verify_flip_seconds: float = 2.0,
    ) -> dict[str, Any]:
        from basicctrl.browser.keystroke_heal import keystroke_to_window_with_retry

        result = await _run_in_thread(
            keystroke_to_window_with_retry,
            app_name=app_name,
            target_title_substr=target_title_substr,
            text=text,
            with_return=with_return,
            tab_switch_hotkey=tab_switch_hotkey,
            max_retries=max_retries,
            settle_seconds=settle_seconds,
            verify_flip_seconds=verify_flip_seconds,
        )
        _log.info(
            "keystroke_with_healing.result",
            app=app_name,
            target_substr=target_title_substr,
            ok=result.get("ok"),
            verified=result.get("verified"),
            attempts=result.get("attempts"),
            reason=result.get("reason"),
        )
        return result

    _log.info("keystroke_tool.registered", tool="keystroke_with_healing")
