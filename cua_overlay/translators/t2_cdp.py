"""T2 CDP Translator — cdp-use 1.4.5 (D-02).

Per CONTEXT.md D-02: direct cdp-use dependency, NOT vendored from elsewhere.
Per CONTEXT.md D-03: this module MUST NOT import the sibling tool's modules
(grep-enforced by tests/unit/translators/test_t2_cdp.py — the literal
sibling-tool name does not appear anywhere in this file).
Per CONTEXT.md D-14: T2 default channel binding is C5 (CDP Input.dispatchMouseEvent).
Per CONTEXT.md D-24: Slack/Cursor/Obsidian workspace renderer filter.
Per RESEARCH.md §"Pattern 5: T2 CDP Implementation" + Pitfall B (flatten=True)
+ Pitfall D (workspace filter).

cua-maximalist coexists with the user's other CDP tooling — both call
cdp-use directly; neither owns the other.

Resolution flow:
    1. Probe localhost:9222..9225 GET /json/version (httpx async, 0.5s timeout)
    2. Open CDPClient(ws_url)
    3. Target.getTargets → filter by bundle_id-specific URL pattern (Pitfall D)
    4. Target.attachToTarget(flatten=True)  ← Pitfall B mandatory flag
    5. DOM.getDocument → DOM.querySelector(target_spec.css)
    6. DOM.getBoxModel → compute content-quad center → bbox
    7. Return TranslatorTarget(element, cdp_node_id, cdp_session_id,
       grounded_bbox, extras={"ws_url": ws_url}) so C5 can re-attach

P8 mitigation: if no port reachable, return None — Plan 02-11's healing tool
prompts the user once to relaunch Slack/Cursor/Obsidian with the
``--remote-debugging-port=9222`` flag (never silent restart per D-24).

Concurrency note: validate() does NOT do a live DOM round-trip per call.
The CDPClient context closes when resolve() returns; C5 re-opens its own
client at fire-time (cheap, ~10ms localhost). Phase 3+ may pool CDPClients
per (pid, session_id) — for now correctness over micro-latency.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

import httpx
import structlog

from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.translators.base import TargetSpec, TranslatorTarget


_log = structlog.get_logger()


# Probe ports for Electron --remote-debugging-port. 9222 is the canonical
# Chrome/Electron default; 9223..9225 cover the case where multiple Electron
# apps are simultaneously relaunched with the flag.
CDP_PROBE_PORTS: tuple[int, ...] = (9222, 9223, 9224, 9225)


class T2CDPTranslator:
    """T2 CDP translator using cdp-use 1.4.5.

    Implements ``Translator`` Protocol (cua_overlay.translators.base.Translator).
    Tier='T2'. Default channel binding (D-14): C5 CDPInputChannel.
    """

    tier: Literal["T1", "T2", "T3", "T4", "T5"] = "T2"

    async def _discover_ws_url(self, pid: int) -> Optional[str]:
        """Resolve the live CDP WebSocket URL for the user's browser.

        Discovery order (mirrors cua_overlay.browser.daemon.get_ws_url, which
        was vendored from browser-use/browser-harness 2026-05-03):

        1. ``CUA_T2_CDP_PORT_OVERRIDE`` env var → single probe port (test hook).
        2. Probe localhost:9222..9225 GET /json/version. 200 OK with a
           ``webSocketDebuggerUrl`` wins. This catches Electron apps and
           dedicated automation Chrome launched with ``--remote-debugging-port``.
        3. Walk every Chromium-class user-profile dir for ``DevToolsActivePort``.
           When the user has ticked ``chrome://inspect/#remote-debugging``'s
           "Allow remote debugging for this browser instance" on a normal Chrome
           profile, Chrome writes ``port\\nws_path`` to that file. Chrome 144+
           silently disables ``/json/version`` on the default profile, so step
           2 returns 404 even though CDP works — DevToolsActivePort is the
           only reliable path for the user's everyday Chrome.

        Returns the resolved ws URL (str) or None if nothing was reachable.
        """
        import os
        from pathlib import Path

        override = os.environ.get("CUA_T2_CDP_PORT_OVERRIDE")
        ports: tuple[int, ...]
        if override:
            try:
                ports = (int(override),)
            except ValueError:
                ports = CDP_PROBE_PORTS
        else:
            ports = CDP_PROBE_PORTS

        # Step 2: HTTP /json/version probe
        for port in ports:
            try:
                async with httpx.AsyncClient(timeout=0.5) as client:
                    r = await client.get(f"http://localhost:{port}/json/version")
                    if r.status_code == 200:
                        ws = r.json().get("webSocketDebuggerUrl")
                        if ws:
                            _log.debug("t2.cdp_port_reachable", port=port, ws_url=ws)
                            return ws
            except Exception as exc:  # noqa: BLE001 — every failure is "skip and try next"
                _log.debug("t2.cdp_probe_skip", port=port, error=str(exc))
                continue

        # Step 3: DevToolsActivePort fallback for the user's real Chrome
        # profile (Chrome 144+ workaround).
        profiles = (
            Path.home() / "Library/Application Support/Google/Chrome",
            Path.home() / "Library/Application Support/BraveSoftware/Brave-Browser",
            Path.home() / "Library/Application Support/Microsoft Edge",
            Path.home() / "Library/Application Support/Microsoft Edge Beta",
            Path.home() / "Library/Application Support/Microsoft Edge Dev",
            Path.home() / "Library/Application Support/Microsoft Edge Canary",
            Path.home() / "Library/Application Support/Arc/User Data",
            Path.home() / "Library/Application Support/Comet",
            Path.home() / "Library/Application Support/Dia/User Data",
            Path.home() / ".config/google-chrome",
            Path.home() / ".config/chromium",
            Path.home() / ".config/chromium-browser",
            Path.home() / ".config/microsoft-edge",
        )
        for base in profiles:
            try:
                lines = (base / "DevToolsActivePort").read_text().splitlines()
            except (FileNotFoundError, NotADirectoryError, PermissionError):
                continue
            if not lines or not lines[0].strip().isdigit():
                continue
            port = int(lines[0].strip())
            ws_path = lines[1].strip() if len(lines) > 1 else ""
            # Try /json/version first; on 404 fall back to the path Chrome wrote.
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    r = await client.get(f"http://127.0.0.1:{port}/json/version")
                    if r.status_code == 200:
                        ws = r.json().get("webSocketDebuggerUrl")
                        if ws:
                            _log.debug("t2.cdp_devtoolsactiveport_resolved",
                                       profile=str(base.name), port=port, ws_url=ws)
                            return ws
                    if r.status_code == 404 and ws_path:
                        ws = f"ws://127.0.0.1:{port}{ws_path}"
                        _log.debug("t2.cdp_devtoolsactiveport_path_fallback",
                                   profile=str(base.name), port=port, ws_url=ws)
                        return ws
            except Exception as exc:  # noqa: BLE001
                _log.debug("t2.cdp_devtoolsactiveport_skip",
                           profile=str(base.name), error=str(exc))
                continue

        _log.info("t2.cdp_unavailable", pid=pid, ports=list(CDP_PROBE_PORTS))
        return None

    def _pick_workspace_target(
        self, target_infos: list[dict[str, Any]], bundle_id: str
    ) -> Optional[dict[str, Any]]:
        """D-24 workspace filter (Pitfall D).

        Slack: ``type == "page"`` AND url contains ``.slack.com`` (with leading
        dot — must match the workspace subdomain redirect, not bare slack.com).
        Cursor: ``type == "page"`` AND url starts with ``vscode-`` (vscode-webview
        or vscode-file scheme).
        Obsidian: ``type == "page"`` AND url contains ``obsidian`` (matches
        ``app://obsidian.md/...`` and any future scheme variants).

        Returns None when no workspace target matches — caller's resolve()
        returns None and the orchestrator falls through to the next translator.
        """
        if bundle_id == "com.tinyspeck.slackmacgap":
            for t in target_infos:
                if t.get("type") == "page" and ".slack.com" in t.get("url", ""):
                    return t
            return None
        if bundle_id == "com.todesktop.230313mzl4w4u92":  # Cursor
            for t in target_infos:
                if t.get("type") == "page" and t.get("url", "").startswith("vscode-"):
                    return t
            return None
        if bundle_id == "md.obsidian":
            for t in target_infos:
                if t.get("type") == "page" and "obsidian" in t.get("url", "").lower():
                    return t
            return None
        # Default: pick the first page-type target (e.g. Chrome, generic CDP).
        for t in target_infos:
            if t.get("type") == "page":
                return t
        return None

    async def resolve(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
    ) -> Optional[TranslatorTarget]:
        """Attach via CDPDaemon (long-lived per browser), query DOM, return target.

        Returns None on any of:
            * No CDP port reachable (P8 — user hasn't relaunched yet)
            * No workspace target matches the bundle filter (Pitfall D)
            * cdp-use unavailable (import failure)
            * Neither CSS selector nor label provided in target_spec
            * DOM resolution misses on both selector and text-content fallback
            * DOM.getBoxModel returns invalid quad
            * Any CDP-level exception (translator must never raise — orchestrator
              treats None as "this translator can't address this target")

        browser-harness integration §F2/G2: uses CDPDaemon.get_or_create
        instead of per-fire CDPClient (saves ~10ms per call + enables
        stale-session re-attach + event tap), and falls back to text-
        content search when no CSS selector is provided or it misses.
        """
        ws_url = await self._discover_ws_url(pid)
        if ws_url is None:
            return None

        from cua_overlay.translators.cdp_daemon import get_or_create

        try:
            daemon = await get_or_create(pid=pid, ws_url=ws_url, bundle_id=bundle_id)
        except Exception as exc:  # noqa: BLE001
            _log.warning("t2.daemon_open_failed", bundle_id=bundle_id, error=str(exc))
            return None

        try:
            # 1. D-24 workspace filter. If we know this bundle has a specific
            # workspace renderer (Slack, Cursor, Obsidian), pick that target
            # and re-attach the daemon to it. For generic browsers, the
            # daemon's default attach (first real page) is correct.
            targets_resp = await daemon.call("Target.getTargets")
            target_infos = targets_resp.get("targetInfos", [])
            if bundle_id in (
                "com.tinyspeck.slackmacgap",
                "com.todesktop.230313mzl4w4u92",
                "md.obsidian",
            ):
                workspace = self._pick_workspace_target(target_infos, bundle_id)
                if workspace is None:
                    _log.info(
                        "t2.no_workspace_target",
                        bundle_id=bundle_id,
                        target_count=len(target_infos),
                    )
                    return None
                if workspace["targetId"] != getattr(daemon, "_attached_target_id", None):
                    if not await daemon.reattach_to(workspace["targetId"]):
                        return None
                    daemon._attached_target_id = workspace["targetId"]  # type: ignore[attr-defined]

            session_id = daemon.session_id
            if session_id is None:
                _log.warning("t2.daemon_no_session", bundle_id=bundle_id)
                return None

            # 2. Resolve element. Prefer CSS selector when given; fall back
            # to text-content match (browser-harness §G — fixes the
            # "More information…" / label-only case).
            doc = await daemon.call("DOM.getDocument", session_id=session_id)
            root_node_id = doc.get("root", {}).get("nodeId")
            if root_node_id is None:
                return None

            node_id = 0
            if target_spec.css:
                node_search = await daemon.call(
                    "DOM.querySelector",
                    {"nodeId": root_node_id, "selector": target_spec.css},
                    session_id=session_id,
                )
                node_id = node_search.get("nodeId", 0)
                if node_id == 0:
                    _log.debug(
                        "t2.querySelector_miss",
                        bundle_id=bundle_id,
                        selector=target_spec.css,
                    )
            if node_id == 0 and target_spec.label:
                node_id = await self._find_node_by_text(
                    daemon, session_id, target_spec.label
                )
                if node_id == 0:
                    _log.debug(
                        "t2.text_content_miss",
                        bundle_id=bundle_id,
                        label=target_spec.label,
                    )
            if node_id == 0:
                return None

            # 3. Get box model → content quad center.
            box = await daemon.call(
                "DOM.getBoxModel", {"nodeId": node_id}, session_id=session_id
            )
            quad = box.get("model", {}).get("content", [])
            if len(quad) < 8:
                _log.warning("t2.invalid_box_model", node_id=node_id)
                return None
            cx = (quad[0] + quad[4]) / 2
            cy = (quad[1] + quad[5]) / 2

            now = datetime.now(timezone.utc)
            element = UIElement(
                role="AXUnknown",
                role_path=f"CDPElement[{node_id}]",
                label=target_spec.label or target_spec.css,
                bbox=Bbox(x=cx - 10, y=cy - 10, w=20, h=20),
                pid=pid,
                bundle_id=bundle_id,
                window_id=0,
                discovered_at=now,
                last_seen_at=now,
                source=[Source.CDP],
            )
            return TranslatorTarget(
                element=element,
                cdp_node_id=node_id,
                cdp_session_id=session_id,
                grounded_bbox=Bbox(x=cx - 10, y=cy - 10, w=20, h=20),
                extras={"ws_url": ws_url},
            )
        except Exception as exc:  # noqa: BLE001 — translator must never raise
            _log.warning("t2.resolve_error", bundle_id=bundle_id, error=str(exc))
            return None

    async def _find_node_by_text(
        self, daemon: Any, session_id: str, label: str
    ) -> int:
        """Fallback: locate a clickable element whose visible text or aria-label
        matches `label`. Returns nodeId or 0.

        Borrowed from browser-harness's pattern of pairing coordinate clicks
        with screenshot-driven discovery — the agent says "click 'Send'", we
        find what's actually labeled "Send".
        """
        # Escape backticks/backslashes for safe template-literal embedding.
        safe = label.replace("\\", "\\\\").replace("`", "\\`")
        expr = (
            "(()=>{const L=`" + safe + "`;"
            "const els=Array.from(document.querySelectorAll('a,button,input,[role=button],[role=link]'));"
            "const m=els.find(e=>{const t=(e.innerText||e.textContent||'').trim();"
            "return t===L||t.startsWith(L)||(e.ariaLabel||'').trim()===L||(e.title||'').trim()===L;});"
            "return m?1:0;})()"
        )
        try:
            r = await daemon.call(
                "Runtime.evaluate",
                {"expression": expr, "returnByValue": True},
                session_id=session_id,
            )
            if not r.get("result", {}).get("value"):
                return 0
            # Re-run to fetch the matching element as a remoteObject + nodeId.
            object_query = (
                "(()=>{const L=`" + safe + "`;"
                "const els=Array.from(document.querySelectorAll('a,button,input,[role=button],[role=link]'));"
                "return els.find(e=>{const t=(e.innerText||e.textContent||'').trim();"
                "return t===L||t.startsWith(L)||(e.ariaLabel||'').trim()===L||(e.title||'').trim()===L;});})()"
            )
            r2 = await daemon.call(
                "Runtime.evaluate",
                {"expression": object_query, "returnByValue": False},
                session_id=session_id,
            )
            obj = r2.get("result", {})
            object_id = obj.get("objectId")
            if not object_id:
                return 0
            req = await daemon.call(
                "DOM.requestNode", {"objectId": object_id}, session_id=session_id
            )
            return int(req.get("nodeId", 0))
        except Exception as exc:  # noqa: BLE001
            _log.debug("t2.text_search_error", label=label, error=str(exc))
            return 0

    async def validate(self, target: TranslatorTarget) -> bool:
        """T2 validity check: cdp_session_id + cdp_node_id must be present.

        A live DOM round-trip is too costly per validate() call (each
        validate would need to re-open a CDPClient = ~10ms socket + handshake);
        the channel will fail fast on dispatch if the session went away,
        and the orchestrator falls through to the next translator-channel pair.
        """
        return target.cdp_session_id is not None and target.cdp_node_id is not None
