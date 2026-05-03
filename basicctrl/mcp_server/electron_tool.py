"""mcp__basicCtrl__electron — drive Electron apps via CDP.

Third routing bucket alongside browser (Chromium) and AX (native macOS).

Why a separate tool from `browser`:
- Discovery is different. Browser walks profile dirs for
  DevToolsActivePort. Electron needs explicit launch with
  ``--remote-debugging-port=NNNN``.
- Per-app daemon. Each Electron app gets its own CDP daemon
  (CUA_BROWSER_NAME=electron-<slug>) so Slack and Cursor can be
  driven simultaneously without target collision.
- Tab semantics differ. Electron <webview> elements are separate CDP
  targets (type="webview"). The browser tool intentionally hides
  these; the electron tool surfaces them.

Self-heal layers:
- L1: connect retry with backoff (port not yet bound after launch).
- L2: app not running → launch via ``open -a <App> --args
  --remote-debugging-port=<port>``.
- L3: app running but no CDP → clear error + needs_user_action
  (we don't auto-quit user sessions; data loss risk).
- L4: stale WS mid-session → drop cached session, daemon respawns on
  next call, retry the action once.
- L5: port collision → handled in electron.launch (hops to next free
  port in PORT_RANGE_START..END).
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any, Literal, Optional

import structlog
from mcp.server.fastmcp import FastMCP


_log = structlog.get_logger()


# Stale-WS error patterns. Same set as browser_tool but kept local so
# the two tools evolve independently.
_STALE_WS_PATTERNS = (
    "no close frame received or sent",
    "ws handshake failed",
    "connection closed",
    "stale session",
    "websocket connection is closed",
    "session with given id not found",
)


def _is_stale_ws_error(err: str) -> bool:
    lower = err.lower()
    return any(p in lower for p in _STALE_WS_PATTERNS)


async def _run_in_thread(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


class _ElectronSession:
    """Per-bundle_id CDP session. Holds the daemon name + connection
    metadata. The actual CDP transport goes through ipc → daemon.py."""

    def __init__(self, bundle_id: str, daemon_name: str, ws_url: str,
                 port: int, app_name: str) -> None:
        self.bundle_id = bundle_id
        self.daemon_name = daemon_name
        self.ws_url = ws_url
        self.port = port
        self.app_name = app_name

    def send(self, req: dict[str, Any]) -> dict[str, Any]:
        from basicctrl.browser import _ipc as ipc
        c, token = ipc.connect(self.daemon_name, timeout=5.0)
        try:
            r = ipc.request(c, token, req)
        finally:
            c.close()
        if "error" in r:
            raise RuntimeError(r["error"])
        return r

    def cdp(self, method: str, session_id: Optional[str] = None,
            **params: Any) -> dict[str, Any]:
        return self.send({"method": method, "params": params,
                          "session_id": session_id}).get("result", {})


# Global session cache. Keyed by bundle_id. Each entry = one live daemon
# attached to one Electron app. Sessions persist for the lifetime of the
# MCP server process; on stale-WS we drop + recreate.
_sessions: dict[str, _ElectronSession] = {}
_sessions_lock = threading.Lock()


def _connect_blocking(
    bundle_id: str,
    port: Optional[int],
    app_name: Optional[str],
    launch_if_needed: bool,
    quit_first: bool,
) -> _ElectronSession:
    """Blocking connect path (call via _run_in_thread). Self-heals via
    L1 (retry), L2 (auto-launch), L3 (clean error)."""
    from basicctrl.browser import admin, electron

    with _sessions_lock:
        existing = _sessions.get(bundle_id)

    if existing and admin.daemon_alive(existing.daemon_name):
        # Verify the daemon's CDP WS is still alive by pinging the app
        # over its known port. Cheap and catches the "user quit Slack"
        # case before we hand back a dead session.
        if electron.is_cdp_alive(existing.port):
            return existing
        _log.info("electron.session.cdp_dead_dropping",
                 bundle_id=bundle_id, port=existing.port)
        # Daemon alive but CDP dead → drop + reconnect.
        admin.restart_daemon(existing.daemon_name)
        with _sessions_lock:
            _sessions.pop(bundle_id, None)

    # 1. Find already-running CDP (cheapest path).
    found = electron.find_running_cdp(bundle_id)
    if found:
        ws_url = str(found["ws_url"])
        chosen_port = int(found["port"])
        chosen_app = str(found.get("app") or app_name or
                        electron.app_name_for(bundle_id) or bundle_id)
    elif launch_if_needed:
        # 2. L2 self-heal: launch with CDP flag.
        result = electron.launch(bundle_id, port=port, app_name=app_name,
                                quit_first=quit_first)
        if not result.get("ok"):
            err = str(result.get("error") or "launch failed")
            hint = str(result.get("hint") or "")
            full = f"{err}. {hint}" if hint else err
            exc = RuntimeError(full)
            exc.needs_user_action = bool(result.get("needs_user_action"))  # type: ignore[attr-defined]
            raise exc
        ws_url = str(result["ws_url"])
        chosen_port = int(result["port"])
        chosen_app = str(result["app"])
    else:
        raise RuntimeError(
            f"no running CDP for {bundle_id} on its known ports; "
            f"call with launch_if_needed=True to auto-launch"
        )

    # 3. Spawn / reuse the per-app daemon.
    daemon_name = electron.daemon_name_for(bundle_id)
    admin.ensure_daemon(
        name=daemon_name,
        env={"CUA_BROWSER_CDP_WS": ws_url, "CUA_BROWSER_NAME": daemon_name},
    )

    session = _ElectronSession(bundle_id, daemon_name, ws_url,
                              chosen_port, chosen_app)
    with _sessions_lock:
        _sessions[bundle_id] = session
    _log.info("electron.session.connected", bundle_id=bundle_id,
             port=chosen_port, app=chosen_app, daemon=daemon_name)
    return session


def _list_tabs_for_session(session: _ElectronSession,
                          include_webview: bool = True) -> list[dict[str, Any]]:
    """List page + (optionally) webview targets for an Electron app.

    Webviews are surfaced by default for Electron — Slack channels,
    Cursor file panes, VS Code extension hosts often live in webviews.
    """
    targets = session.cdp("Target.getTargets")["targetInfos"]
    allowed = {"page"}
    if include_webview:
        allowed.add("webview")
    out = []
    for t in targets:
        if t.get("type") not in allowed:
            continue
        out.append({
            "targetId": t["targetId"],
            "title": t.get("title", ""),
            "url": t.get("url", ""),
            "type": t.get("type"),
        })
    return out


def _switch_target(session: _ElectronSession, target_id: str) -> str:
    """Attach to a different target in the same app. Returns new
    session_id. Marks the active target on the daemon side."""
    sid = session.cdp("Target.attachToTarget", targetId=target_id,
                     flatten=True)["sessionId"]
    session.send({"meta": "set_session", "session_id": sid,
                  "target_id": target_id})
    return sid


def _disconnect_blocking(bundle_id: str) -> dict[str, Any]:
    """Stop the per-app daemon. Doesn't quit the Electron app itself."""
    from basicctrl.browser import admin, electron
    with _sessions_lock:
        existing = _sessions.pop(bundle_id, None)
    daemon_name = (existing.daemon_name if existing
                  else electron.daemon_name_for(bundle_id))
    try:
        admin.restart_daemon(daemon_name)
        return {"ok": True, "daemon": daemon_name}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "daemon": daemon_name}


def register_electron_tool(proxy: FastMCP) -> None:
    """Register the basicCtrl electron tool on the FastMCP proxy."""

    @proxy.tool(
        name="electron",
        description=(
            "Drive Electron desktop apps (Slack, Cursor, VS Code, "
            "Discord, Linear, Figma, Notion, Spotify, Obsidian, etc.) "
            "via CDP. Strictly faster than AX for Electron — sees real "
            "DOM through webviews and shadow DOM that AX flattens.\n\n"
            "ROUTING: Use this for any app whose bundle_id is in the "
            "Electron registry (or that you know is Electron). For "
            "browser tabs use `browser`. For native Cocoa apps use the "
            "*_with_healing AX tools.\n\n"
            "How it works: launches the app with "
            "--remote-debugging-port=<port> if it's not already "
            "exposing CDP, attaches via per-app daemon, then runs CDP "
            "ops. Each Electron app gets its own daemon so multiple "
            "apps can be driven concurrently.\n\n"
            "Self-heal: auto-launch if not running (L2), retry stale "
            "WS once (L4), port-collision fallback (L5). For "
            "already-running-without-CDP we DON'T silently quit (data "
            "loss risk) — pass quit_first=true if you've confirmed.\n\n"
            "Actions:\n"
            "  - connect(bundle_id, port?, app_name?, "
            "launch_if_needed=True, quit_first=False): attach to app\n"
            "  - status(bundle_id?): one app or all live electron sessions\n"
            "  - disconnect(bundle_id): stop the per-app daemon\n"
            "  - list_known_apps: dump the bundle_id registry\n"
            "  - list_tabs(bundle_id, include_webview=True): pages + webviews\n"
            "  - switch_tab(bundle_id, target_id): activate a target\n"
            "  - page_info(bundle_id): {url, title}\n"
            "  - navigate(bundle_id, url): goto URL in active target\n"
            "  - js(bundle_id, code): Runtime.evaluate\n"
            "  - query_dom(bundle_id, css, attributes=[]): "
            "querySelectorAll → list\n"
            "  - click_xy(bundle_id, x, y): coordinate click\n"
            "  - type_text(bundle_id, text): type to focused element\n"
            "  - screenshot(bundle_id): full-page PNG base64"
        ),
    )
    async def electron_tool(  # noqa: PLR0911
        action: Literal[
            "connect", "status", "disconnect", "list_known_apps",
            "list_tabs", "switch_tab", "page_info", "navigate",
            "js", "query_dom", "click_xy", "type_text", "screenshot",
        ],
        bundle_id: Optional[str] = None,
        port: Optional[int] = None,
        app_name: Optional[str] = None,
        launch_if_needed: bool = True,
        quit_first: bool = False,
        include_webview: bool = True,
        target_id: Optional[str] = None,
        url: Optional[str] = None,
        code: Optional[str] = None,
        css: Optional[str] = None,
        attributes: Optional[list[str]] = None,
        x: Optional[int] = None,
        y: Optional[int] = None,
        text: Optional[str] = None,
    ) -> dict[str, Any]:
        # Actions that don't need a connected session.
        if action == "list_known_apps":
            from basicctrl.browser import electron
            return {
                "ok": True,
                "apps": [
                    {"bundle_id": bid, **{str(k): v for k, v in entry.items()}}
                    for bid, entry in electron.KNOWN_ELECTRON_APPS.items()
                ],
                "port_range": [electron.PORT_RANGE_START, electron.PORT_RANGE_END],
            }

        if action == "status":
            from basicctrl.browser import admin, electron
            if bundle_id:
                with _sessions_lock:
                    s = _sessions.get(bundle_id)
                if s is None:
                    return {"ok": True, "bundle_id": bundle_id, "connected": False}
                alive = await _run_in_thread(admin.daemon_alive, s.daemon_name)
                cdp_alive = await _run_in_thread(electron.is_cdp_alive, s.port)
                return {
                    "ok": True, "bundle_id": bundle_id, "connected": True,
                    "app": s.app_name, "port": s.port, "daemon": s.daemon_name,
                    "daemon_alive": alive, "cdp_alive": cdp_alive,
                }
            with _sessions_lock:
                snapshot = list(_sessions.items())
            return {
                "ok": True,
                "sessions": [
                    {"bundle_id": bid, "app": s.app_name, "port": s.port,
                     "daemon": s.daemon_name}
                    for bid, s in snapshot
                ],
            }

        if action == "disconnect":
            if not bundle_id:
                return {"ok": False, "error": "disconnect requires bundle_id"}
            return await _run_in_thread(_disconnect_blocking, bundle_id)

        # All remaining actions need a bundle_id + connected session.
        if not bundle_id:
            return {"ok": False, "error": f"{action} requires bundle_id"}

        async def _ensure_session() -> _ElectronSession:
            return await _run_in_thread(
                _connect_blocking, bundle_id, port, app_name,
                launch_if_needed, quit_first,
            )

        async def _dispatch(s: _ElectronSession) -> dict[str, Any]:
            if action == "connect":
                return {
                    "ok": True, "bundle_id": s.bundle_id, "app": s.app_name,
                    "port": s.port, "ws_url": s.ws_url, "daemon": s.daemon_name,
                }

            if action == "list_tabs":
                tabs = await _run_in_thread(_list_tabs_for_session, s,
                                           include_webview)
                return {"ok": True, "tabs": tabs, "count": len(tabs)}

            if action == "switch_tab":
                if not target_id:
                    return {"ok": False, "error": "switch_tab requires target_id"}
                sid = await _run_in_thread(_switch_target, s, target_id)
                info = await _run_in_thread(
                    lambda: s.cdp("Target.getTargetInfo")["targetInfo"]
                )
                return {"ok": True, "session_id": sid,
                        "target": {"targetId": info.get("targetId"),
                                  "url": info.get("url"),
                                  "title": info.get("title")}}

            if action == "page_info":
                def _info():
                    info = s.cdp("Target.getTargetInfo").get("targetInfo", {})
                    return {"url": info.get("url", ""),
                           "title": info.get("title", ""),
                           "targetId": info.get("targetId"),
                           "type": info.get("type")}
                return {"ok": True, **(await _run_in_thread(_info))}

            if action == "navigate":
                if not url:
                    return {"ok": False, "error": "navigate requires url"}
                await _run_in_thread(lambda: s.cdp("Page.navigate", url=url))
                return {"ok": True, "navigated_to": url}

            if action == "js":
                if code is None:
                    return {"ok": False, "error": "js requires code"}

                def _eval():
                    return s.cdp("Runtime.evaluate", expression=code,
                                returnByValue=True, awaitPromise=True)
                result = await _run_in_thread(_eval)
                payload = result.get("result", {})
                details = result.get("exceptionDetails")
                if details:
                    return {"ok": False, "error": details.get("text") or
                           "JS evaluation failed", "details": details}
                return {"ok": True, "value": payload.get("value"),
                        "type": payload.get("type")}

            if action == "query_dom":
                if not css:
                    return {"ok": False, "error": "query_dom requires css"}
                attrs_js = (
                    "[" + ",".join(f"el.getAttribute({a!r})"
                                  for a in (attributes or [])) + "]"
                )
                attr_keys = list(attributes or [])
                code_str = (
                    "(()=>{"
                    f"const els=[...document.querySelectorAll({css!r})];"
                    "return els.map(el=>({"
                    "tag:el.tagName.toLowerCase(),"
                    "text:(el.innerText||'').slice(0,500),"
                    f"attrs:{attrs_js}.reduce((o,v,i)=>{{o[{attr_keys!r}[i]]=v;return o;}},{{}})"
                    "}));})()"
                )

                def _eval():
                    return s.cdp("Runtime.evaluate", expression=code_str,
                                returnByValue=True)
                result = await _run_in_thread(_eval)
                payload = result.get("result", {}).get("value") or []
                return {"ok": True, "count": len(payload), "elements": payload}

            if action == "click_xy":
                if x is None or y is None:
                    return {"ok": False, "error": "click_xy requires x,y"}

                def _click():
                    s.cdp("Input.dispatchMouseEvent", type="mousePressed",
                          x=x, y=y, button="left", clickCount=1)
                    s.cdp("Input.dispatchMouseEvent", type="mouseReleased",
                          x=x, y=y, button="left", clickCount=1)
                await _run_in_thread(_click)
                return {"ok": True, "clicked": [x, y]}

            if action == "type_text":
                if text is None:
                    return {"ok": False, "error": "type_text requires text"}

                def _type():
                    for ch in text:
                        s.cdp("Input.insertText", text=ch)
                await _run_in_thread(_type)
                return {"ok": True, "typed_chars": len(text)}

            if action == "screenshot":
                def _shot():
                    return s.cdp("Page.captureScreenshot",
                                format="png", captureBeyondViewport=False)
                result = await _run_in_thread(_shot)
                return {"ok": True, "format": "png",
                        "base64": result.get("data", "")}

            return {"ok": False, "error": f"unknown action: {action}"}

        # L4 self-heal wrapper: stale WS → drop session → retry once.
        last_err: Optional[str] = None
        for attempt in (0, 1):
            try:
                session = await _ensure_session()
                return await _dispatch(session)
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                needs_action = getattr(exc, "needs_user_action", False)
                if needs_action:
                    return {"ok": False, "error": last_err,
                           "needs_user_action": True,
                           "hint": "User must quit the app, or pass quit_first=True"}
                if attempt == 0 and _is_stale_ws_error(last_err):
                    _log.info("electron.heal.l4_stale_ws_retry",
                             bundle_id=bundle_id, error=last_err[:120])
                    with _sessions_lock:
                        _sessions.pop(bundle_id, None)
                    continue
                break

        return {"ok": False, "error": last_err or "unknown",
               "bundle_id": bundle_id}

    _log.info("electron_tool.registered", tool="electron")
