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
        """Probe localhost:9222..9225 for /json/version → ws URL.

        Returns the ``webSocketDebuggerUrl`` from the first 200-OK response,
        or None if all probes fail. The 0.5s per-port timeout keeps total
        worst-case latency under 2s when nothing is listening (P8 path).
        """
        for port in CDP_PROBE_PORTS:
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
        """Attach via cdp-use, query DOM, return TranslatorTarget with cdp handles.

        Returns None on any of:
            * No CDP port reachable (P8 — user hasn't relaunched yet)
            * No workspace target matches the bundle filter (Pitfall D)
            * cdp-use unavailable (import failure)
            * No css selector in target_spec
            * DOM.querySelector returns nodeId=0 (selector miss)
            * DOM.getBoxModel returns invalid quad
            * Any CDP-level exception (translator must never raise — orchestrator
              treats None as "this translator can't address this target")
        """
        # NOTE: D-03 — cdp-use is the direct dep (no sibling-tool import).
        try:
            from cdp_use.client import CDPClient  # type: ignore[import-not-found]
        except ImportError:
            _log.error("t2.cdp_use_unavailable", hint="install cdp-use==1.4.5")
            return None

        ws_url = await self._discover_ws_url(pid)
        if ws_url is None:
            return None

        try:
            async with CDPClient(ws_url) as cdp:
                # 1. Target list filter for workspace renderer (Pitfall D / D-24).
                targets = await cdp.send.Target.getTargets()
                target_infos = targets.get("targetInfos", [])
                workspace = self._pick_workspace_target(target_infos, bundle_id)
                if workspace is None:
                    _log.info(
                        "t2.no_workspace_target",
                        bundle_id=bundle_id,
                        target_count=len(target_infos),
                    )
                    return None

                # 2. Attach with flatten=True (Pitfall B — flatten is mandatory).
                # Without flatten, DOM calls hang silently waiting for a separate
                # session-event pump that we never registered.
                attach = await cdp.send.Target.attachToTarget(
                    params={"targetId": workspace["targetId"], "flatten": True}
                )
                session_id = attach.get("sessionId")
                if session_id is None:
                    _log.warning("t2.attach_no_session", target=workspace.get("targetId"))
                    return None

                # 3. Resolve element by CSS selector. T2 requires target_spec.css;
                # if the caller only passed AX hints, this translator can't help.
                if not target_spec.css:
                    _log.debug("t2.no_css_selector", bundle_id=bundle_id)
                    return None
                doc = await cdp.send.DOM.getDocument(sessionId=session_id)
                root_node_id = doc.get("root", {}).get("nodeId")
                if root_node_id is None:
                    return None
                node_search = await cdp.send.DOM.querySelector(
                    params={"nodeId": root_node_id, "selector": target_spec.css},
                    sessionId=session_id,
                )
                node_id = node_search.get("nodeId", 0)
                if node_id == 0:
                    _log.debug(
                        "t2.querySelector_miss",
                        bundle_id=bundle_id,
                        selector=target_spec.css,
                    )
                    return None

                # 4. Get box model → content quad center.
                # CDP returns content quad as [x1,y1, x2,y2, x3,y3, x4,y4]
                # with vertices in clockwise order; the diagonal averages
                # ((x1+x3)/2, (y1+y3)/2) give the center.
                box = await cdp.send.DOM.getBoxModel(
                    params={"nodeId": node_id}, sessionId=session_id
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

    async def validate(self, target: TranslatorTarget) -> bool:
        """T2 validity check: cdp_session_id + cdp_node_id must be present.

        A live DOM round-trip is too costly per validate() call (each
        validate would need to re-open a CDPClient = ~10ms socket + handshake);
        the channel will fail fast on dispatch if the session went away,
        and the orchestrator falls through to the next translator-channel pair.
        """
        return target.cdp_session_id is not None and target.cdp_node_id is not None
