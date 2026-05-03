"""L0Push consumer — drains AXObserverManager + NSWorkspace + kqueue futures
into a signal dict.

Latency: 0 ms (events stream while the action is firing). Caller awaits with
a small timeout — typical 50 ms — so the verifier ladder doesn't stall on a
silent action.

CLAUDE.md hard rule (enforced by source-grep test):
    "Always subscribe AXObserver push notifications BEFORE the action fires."
    L0 is the *consumer* side — the caller MUST have called ``axmgr.expect()``
    before firing the action. This module NEVER polls AX — no subtree walks,
    no element-attribute reads, no rate-limited AX getters of any kind.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from basicctrl.state.graph import UIElement
from basicctrl.verifier.axobserver import AXObserverManager
from basicctrl.verifier.kqueue_proc import KqueueProcObserver
from basicctrl.verifier.nsworkspace import NSWorkspaceObserver


# Map AX notification names → signal-dict keys consumed by WeightedVote.
# Adding a new notif here requires adding the matching weight in
# weighted_vote.WEIGHTS for any action class that should react to it.
_AX_NOTIF_TO_SIGNAL: dict[str, str] = {
    "AXValueChanged": "ax.value_changed",
    "AXFocusedUIElementChanged": "ax.focused_changed",
    "AXWindowCreated": "ax.window_created",
    "AXTitleChanged": "ax.title_changed",
    "AXLayoutChanged": "ax.layout_changed",
    "AXSelectedTextChanged": "ax.selected_text_changed",
    "AXSelectedRowsChanged": "ax.selected_rows_changed",
}


class L0Push:
    """Drains push-event futures into a signal dict. NEVER POLLS.

    Per CLAUDE.md hard rule: "Always subscribe AXObserver push notifications
    BEFORE the action fires." L0 is the consumer side — assumes
    ``axmgr.expect()`` was called BEFORE the action fired.

    Public surface:
        l0 = L0Push(axmgr=mgr, ws=ws, kq=kq)
        # caller subscribed via mgr.expect(...) BEFORE firing the action
        # ... fire action ...
        signals = await l0.collect(target, ["AXValueChanged"], action_id, timeout_ms=50)
    """

    def __init__(
        self,
        axmgr: AXObserverManager,
        ws: Optional[NSWorkspaceObserver] = None,
        kq: Optional[KqueueProcObserver] = None,
    ) -> None:
        self._axmgr = axmgr
        self._ws = ws
        self._kq = kq
        self._log = structlog.get_logger()

    async def collect(
        self,
        target: UIElement,
        notifs: list[str],
        action_id: str,
        timeout_ms: int = 50,
        ax_element: Any = None,
        pre_fire_future: Any = None,
    ) -> dict[str, float]:
        """Initialize all signals to 0; await an AXObserver future with budget;
        map AXEvent → signal key.

        Two paths (F9):
          1. **pre_fire_future provided** — caller (RaceOrchestrator) already
             called axmgr.subscribe_pending BEFORE firing the action and is
             handing us the resulting Future. We await it via
             axmgr.await_future. subscription_ts_ns < action_fires_ts_ns <
             event_ts_ns is correctly preserved (Pitfall P28 5ms guard works).
          2. **No future provided** — legacy path. We call axmgr.expect which
             subscribes + awaits in one go. Subscription happens AFTER the
             action has fired, so events emitted *before* this subscribe pass
             would be filtered by the 5ms guard. The orchestrator/F9 path is
             preferred.

        The first matching event sets exactly one signal to 1.0; the others
        remain 0.0.

        Note: NSWorkspace and kqueue observers are wired here as constructor
        deps so Phase 2 can race their events into the signal dict; Phase 1
        only consumes AX events because that's what the Calculator demo needs.
        """
        # Initialize all known AX signals to 0 — every signal weight in
        # WeightedVote.WEIGHTS["click"] etc. has a default at this layer.
        signals: dict[str, float] = {sig: 0.0 for sig in _AX_NOTIF_TO_SIGNAL.values()}
        signals.setdefault("ws.frontmost_change", 0.0)
        signals.setdefault("kqueue.exit", 0.0)

        try:
            if pre_fire_future is not None:
                event = await self._axmgr.await_future(
                    pre_fire_future, timeout_ms=timeout_ms
                )
            else:
                event = await self._axmgr.expect(
                    target=target,
                    notifs=notifs,
                    action_id=action_id,
                    timeout_ms=timeout_ms,
                    ax_element=ax_element,
                )
            sig_key = _AX_NOTIF_TO_SIGNAL.get(event.notif)
            if sig_key:
                signals[sig_key] = 1.0
            self._log.info(
                "l0.push_event_received",
                notif=event.notif,
                sig=sig_key,
                latency_ns=event.event_ts_ns,
            )
        except asyncio.TimeoutError:
            self._log.info(
                "l0.push_event_timeout",
                target=target.composite_key,
                timeout_ms=timeout_ms,
            )

        return signals
