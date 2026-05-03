"""mcp__basicCtrl__browser — CDP-driven browser tool.

Vendored from browser-use/browser-harness (May 2026). Same patterns:
- Per-profile DevToolsActivePort discovery (no need to launch with
  --remote-debugging-port; works against the user's everyday Chrome).
- Daemon holds the CDP WebSocket; subsequent tool calls reuse it.
- Self-healing: detect "needs chrome://inspect tick" errors and walk
  the user through the one-time setup.

Routing: when a Chromium-class app is the target, this tool is the
optimal protocol — strictly better than AX (faster, passes through
iframes/shadow DOM, sees the live DOM not the AX flattened tree).
The framework's preflight should auto-run this rather than fall
through to T1 AX.
"""
from __future__ import annotations

import asyncio
import base64
from typing import Any, Literal, Optional

import structlog
from mcp.server.fastmcp import FastMCP


_log = structlog.get_logger()


# Error patterns that mean "Chrome doesn't have remote debugging enabled
# on the user's profile" — port browser-harness's admin._needs_chrome_
# remote_debugging_prompt.
_NEEDS_SETUP_PATTERNS = (
    "devtoolsactiveport not found",
    "enable chrome://inspect",
    "not live yet",
    "ws handshake failed",
    "no chrome",
    "connection refused",
)


def _needs_remote_debugging_setup(err: str) -> bool:
    lower = err.lower()
    return any(p in lower for p in _NEEDS_SETUP_PATTERNS)


async def _run_in_thread(fn, *args, **kwargs):
    """browser-harness helpers are sync; run them in a worker thread so
    the MCP event loop isn't blocked."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# Errors that mean the WS itself died (vs a content-side problem). On these
# we restart the daemon and retry the original call once. Browser-harness's
# daemon prints these from the stale-WS path (see daemon.py:198).
_STALE_WS_PATTERNS = (
    "no close frame received or sent",
    "ws handshake failed",
    "connection closed",
    "stale session",
    "websocket connection is closed",
)


def _is_stale_ws_error(err: str) -> bool:
    lower = err.lower()
    return any(p in lower for p in _STALE_WS_PATTERNS)


async def _heal_and_retry(action_fn, *, action_name: str, max_retries: int = 1):
    """Self-heal wrapper: catch known recoverable errors → recover → retry.

    Recovery branches (mapped to browser-harness conventions):
      B1: setup-needed (devtoolsactiveport / connection refused / ws handshake
          on first attach) → admin.ensure_daemon already does this internally
          (opens chrome://inspect + waits for user). We just bubble the final
          state.
      B2: stale ws mid-session → admin.restart_daemon → retry original action.
      B3: attached to chrome://omnibox-popup or other internal tab →
          helpers.ensure_real_tab (called inline before navigation actions).

    The vendored core (admin.ensure_daemon, daemon.get_ws_url) already does
    most of B1 itself — see admin.py:163 _needs_chrome_remote_debugging_prompt
    branch + daemon.py 30s polling. This wrapper layers retry-on-success on
    top so the MCP caller doesn't have to.
    """
    from basicctrl.browser import admin
    last_err: Optional[str] = None
    for attempt in range(max_retries + 1):
        try:
            return await action_fn()
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            if attempt >= max_retries:
                break
            if _is_stale_ws_error(last_err):
                _log.info("browser_tool.heal.b2_restart_daemon",
                          action=action_name, error=last_err[:120])
                try:
                    await _run_in_thread(admin.restart_daemon)
                    await _run_in_thread(admin.ensure_daemon)
                except Exception as heal_exc:  # noqa: BLE001
                    last_err = f"{last_err} (recover failed: {heal_exc})"
                    break
                continue
            # Not a recoverable class — bubble immediately.
            break
    raise RuntimeError(last_err or "unknown")


def register_browser_tool(proxy: FastMCP) -> None:
    """Register the basicCtrl browser tool on the FastMCP proxy.

    One tool, dispatched by `action` keyword. This keeps the surface
    small (one function in tool listings) while exposing the full CDP
    helper set.
    """
    from basicctrl.browser import helpers, admin

    @proxy.tool(
        name="browser",
        description=(
            "Drive any Chromium browser (Chrome, Brave, Edge, Arc) via "
            "CDP — vendored from browser-use/browser-harness. Connects "
            "to the user's running browser by walking profile dirs for "
            "DevToolsActivePort; no --remote-debugging-port relaunch "
            "needed. Inherits the user's logins, cookies, extensions. "
            "Far faster than AX and works through iframes/shadow DOM. "
            "PREFER THIS OVER click/type AX tools when the target is a "
            "browser tab.\n\n"
            "Actions:\n"
            "  - status: probe daemon + browser; returns {daemon_alive, "
            "    page (url+title) | error}\n"
            "  - navigate(url): goto in current tab (or open new_tab if "
            "    on an internal chrome:// page)\n"
            "  - page_info: {url, title, viewport, scroll}\n"
            "  - js(code): run JS, return value (use for fill, click-by-text, "
            "    scrape, anything DOM)\n"
            "  - query_dom(css, attributes=[]): querySelectorAll → "
            "    [{tag, innerText, attrs}]\n"
            "  - click_xy(x, y): coordinate click via "
            "    Input.dispatchMouseEvent (passes through iframes)\n"
            "  - type_text(text): type into focused element\n"
            "  - screenshot: full-page PNG, base64\n"
            "  - new_tab(url): open a real visible tab\n"
            "  - list_tabs: every page-class CDP target\n"
            "  - switch_tab(target_id): activate that tab\n"
            "  - restart_daemon: kill + respawn (use after Chrome restart)"
        ),
    )
    async def browser(
        action: Literal[
            "status", "navigate", "page_info", "js", "query_dom",
            "click_xy", "type_text", "screenshot", "new_tab",
            "list_tabs", "switch_tab", "restart_daemon",
        ],
        url: Optional[str] = None,
        code: Optional[str] = None,
        css: Optional[str] = None,
        attributes: Optional[list[str]] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        text: Optional[str] = None,
        target_id: Optional[str] = None,
    ) -> dict[str, Any]:
        # Status / restart never need an active daemon yet.
        if action == "status":
            alive = await _run_in_thread(admin.daemon_alive)
            if not alive:
                return {"daemon_alive": False, "page": None,
                        "hint": "Call any other action to auto-start the daemon."}
            try:
                info = await _run_in_thread(helpers.page_info)
                return {"daemon_alive": True, "page": info}
            except Exception as exc:  # noqa: BLE001
                return {"daemon_alive": True, "page": None, "error": str(exc)}

        if action == "restart_daemon":
            try:
                await _run_in_thread(admin.restart_daemon)
                return {"ok": True}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        # Auto-start daemon if needed.
        try:
            if not await _run_in_thread(admin.daemon_alive):
                await _run_in_thread(admin.ensure_daemon)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            if _needs_remote_debugging_setup(err):
                return {
                    "ok": False,
                    "error": err,
                    "needs_setup": True,
                    "setup_steps": [
                        "1. In the user's Chrome, open chrome://inspect/#remote-debugging",
                        "2. Tick 'Allow remote debugging for this browser instance'",
                        "3. Click Allow on the in-browser popup (Chrome 144+)",
                        "4. Retry the browser tool call",
                    ],
                    "auto_setup_command": (
                        "osascript -e 'tell application \"Google Chrome\" to activate' "
                        "-e 'tell application \"Google Chrome\" to open location "
                        "\"chrome://inspect/#remote-debugging\"'"
                    ),
                }
            return {"ok": False, "error": err}

        # B3 self-heal: before any content-side action, switch off
        # internal/stale tabs so we don't drive chrome://omnibox-popup
        # or chrome://inspect by accident. Cheap (one CDP call).
        _CONTENT_ACTIONS = {"navigate", "js", "query_dom", "click_xy",
                            "type_text", "screenshot", "page_info"}
        if action in _CONTENT_ACTIONS:
            try:
                await _run_in_thread(helpers.ensure_real_tab)
            except Exception as exc:  # noqa: BLE001
                _log.debug("browser_tool.heal.b3_skipped", err=str(exc)[:120])

        # Dispatch wrapped in B2 self-heal: stale-WS errors → restart_daemon
        # → retry once. Setup-needed errors (B1) are already handled inside
        # admin.ensure_daemon's retry loop above.
        async def _dispatch():
            if action == "navigate":
                if not url:
                    return {"ok": False, "error": "navigate requires url"}
                await _run_in_thread(helpers.goto_url, url)
                info = await _run_in_thread(helpers.page_info)
                return {"ok": True, "page": info}

            if action == "page_info":
                info = await _run_in_thread(helpers.page_info)
                return {"ok": True, **info}

            if action == "js":
                if code is None:
                    return {"ok": False, "error": "js requires code"}
                result = await _run_in_thread(helpers.js, code)
                return {"ok": True, "result": result}

            if action == "query_dom":
                if not css:
                    return {"ok": False, "error": "query_dom requires css"}
                attrs_js = (
                    "[" + ",".join(f"el.getAttribute('{a}')" for a in (attributes or [])) + "]"
                    if attributes
                    else "[]"
                )
                code_str = f"""
(() => {{
  const els = [...document.querySelectorAll({css!r})];
  return els.map(el => ({{
    tag: el.tagName.toLowerCase(),
    text: (el.innerText || '').slice(0, 500),
    attrs: {attrs_js}.reduce((o, v, i) => {{
      o[{(attributes or [])!r}[i]] = v; return o;
    }}, {{}}),
  }}));
}})()
"""
                result = await _run_in_thread(helpers.js, code_str)
                return {"ok": True, "count": len(result or []), "elements": result}

            if action == "click_xy":
                if x is None or y is None:
                    return {"ok": False, "error": "click_xy requires x,y"}
                await _run_in_thread(helpers.click_at_xy, x, y)
                return {"ok": True, "clicked": [x, y]}

            if action == "type_text":
                if text is None:
                    return {"ok": False, "error": "type_text requires text"}
                await _run_in_thread(helpers.type_text, text)
                return {"ok": True, "typed_chars": len(text)}

            if action == "screenshot":
                png_b64 = await _run_in_thread(helpers.capture_screenshot)
                return {"ok": True, "format": "png", "base64": png_b64}

            if action == "new_tab":
                if not url:
                    return {"ok": False, "error": "new_tab requires url"}
                await _run_in_thread(helpers.new_tab, url)
                info = await _run_in_thread(helpers.page_info)
                return {"ok": True, "page": info}

            if action == "list_tabs":
                tabs = await _run_in_thread(helpers.list_tabs)
                return {"ok": True, "tabs": tabs}

            if action == "switch_tab":
                if not target_id:
                    return {"ok": False, "error": "switch_tab requires target_id"}
                await _run_in_thread(helpers.switch_tab, target_id)
                info = await _run_in_thread(helpers.page_info)
                return {"ok": True, "page": info}

            return {"ok": False, "error": f"unknown action: {action}"}

        # Run dispatch with B2 self-heal: stale-WS triggers daemon restart
        # + retry the original call.
        try:
            return await _heal_and_retry(_dispatch, action_name=action)
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            if _needs_remote_debugging_setup(err):
                return {
                    "ok": False,
                    "error": err,
                    "needs_setup": True,
                    "setup_steps": [
                        "Run chrome://inspect/#remote-debugging setup (see status hint).",
                    ],
                }
            return {"ok": False, "error": err}

    _log.info("browser_tool.registered", tool="browser")
