"""C5 CDP Input.dispatchMouseEvent channel — D-14 T2 default binding.

Per CONTEXT.md D-14: T2 (CDP) default channel is C5 (CDP Input.dispatchMouseEvent).
Per CONTEXT.md D-17: try_claim BEFORE syscall (atomic write, NDJSON trace).
Per CONTEXT.md D-18: cancel_event.is_set() check immediately before syscall.
Per RESEARCH.md §"Pattern 9 Channel Registry Shape" + cdp-use 1.4.5 API.

The channel reads ``ws_url`` from ``target.extras`` (T2CDPTranslator.resolve()
puts it there) and re-opens a CDPClient at fire-time. Phase 2 trades ~10ms
of localhost socket re-open for clean per-fire CDPClient lifecycle (each
fire owns its own connection — no cross-fire concurrency hazards). Phase 3+
may pool CDPClients per (pid, session_id).

Threats mitigated:
    * T-2-01 (race ordering) — try_claim BEFORE Input.dispatchMouseEvent;
      second fire on same action_id returns ChannelOutcome(status='skipped').
    * T-2-08 (race-cancel correctness) — cancel_event.is_set() check before
      the CDPClient is even constructed. ``async with CDPClient(...)``
      propagates cancellation to socket close on the way out.

A "click" is a mousePressed + mouseReleased PAIR — never a single combined
event. Both events go to the same (x, y) at the bbox center, with
button='left' and clickCount=1.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Literal, Optional

import anyio
import structlog

from cua_overlay.actions.channels.base import ChannelOutcome
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TranslatorTarget


_log = structlog.get_logger()


class C5CDPInputChannel:
    """C5 — CDP Input.dispatchMouseEvent.

    Default channel for T2 (D-14). Re-opens a CDPClient at the ws_url that
    T2 stashed in ``target.extras``, then dispatches mousePressed + mouseReleased
    at the content-quad center carried in ``target.grounded_bbox``.
    """

    name: Literal["C1", "C2", "C3", "C4", "C5"] = "C5"

    def __init__(
        self,
        cdp_client_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """Args:
            cdp_client_factory: callable returning an async-context CDPClient
                given a ws_url. Default: lazy-import ``cdp_use.client.CDPClient``.
                Tests inject a fake factory to avoid real sockets.
        """
        if cdp_client_factory is None:
            try:
                from cdp_use.client import CDPClient  # type: ignore[import-not-found]
                cdp_client_factory = CDPClient
            except ImportError:
                cdp_client_factory = None
        self._cdp_client_factory = cdp_client_factory

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        """Fire mousePressed + mouseReleased via CDP Input.dispatchMouseEvent.

        Order of operations (verified by tests):
            1. ``store.try_claim(action.id, "C5")`` — atomic claim.
               Lose → ``ChannelOutcome(status='skipped',
               skipped_reason='idempotency_lost')``.
            2. ``cancel_event.is_set()`` — pre-syscall kill-switch. Set →
               ``ChannelOutcome(status='cancelled')`` with NO CDPClient
               construction (the claim is held to keep the orchestrator's
               race winner canonical).
            3. Validate ``target.cdp_session_id`` + ``target.grounded_bbox``
               + ``target.extras['ws_url']`` are all populated.
            4. ``async with CDPClient(ws_url)`` → dispatch mousePressed →
               dispatch mouseReleased — both at bbox center (cx, cy),
               ``button='left'``, ``clickCount=1``, on the same sessionId.
            5. Return ``ChannelOutcome(status='fired',
               fired_at_ns=time.monotonic_ns())``.

        Any exception inside the CDPClient block is converted to
        ``ChannelOutcome(status='errored', error=str(exc))`` — the channel
        contract forbids raising across the boundary (Phase 1 Channel Protocol).
        """
        # 1. Atomic claim (D-17). If lost, skip.
        claim = await store.try_claim(action.id, "C5")
        if claim is None:
            return ChannelOutcome(
                channel="C5", status="skipped", skipped_reason="idempotency_lost"
            )

        # 2. Pre-syscall kill-switch (D-18). Check BEFORE constructing the
        # CDPClient — we don't want to open a socket only to throw it away.
        if cancel_event.is_set():
            return ChannelOutcome(channel="C5", status="cancelled")

        # 3. Validate handles. T2.resolve() puts ws_url in extras; if any
        # field is missing (e.g. orchestrator routed a non-T2 target to C5
        # by mistake), error fast.
        if target.cdp_session_id is None:
            return ChannelOutcome(
                channel="C5", status="errored", error="no cdp_session_id"
            )
        if target.grounded_bbox is None:
            return ChannelOutcome(
                channel="C5", status="errored", error="no grounded_bbox"
            )
        if self._cdp_client_factory is None:
            return ChannelOutcome(
                channel="C5", status="errored", error="cdp_use unavailable"
            )
        ws_url = target.extras.get("ws_url")
        if not ws_url:
            return ChannelOutcome(
                channel="C5", status="errored", error="no ws_url in target.extras"
            )

        bbox = target.grounded_bbox
        cx = bbox.x + bbox.w / 2
        cy = bbox.y + bbox.h / 2

        # 4. Dispatch the click pair via the long-lived CDPDaemon (browser-harness
        # integration §F3). The daemon already owns an attached session for this
        # browser; we dispatch on the same session_id T2 used. Saves the ~10ms
        # per-fire socket handshake we used to pay with `async with CDPClient(...)`.
        # Stale-session retry happens inside daemon.call().
        try:
            from cua_overlay.translators.cdp_daemon import get_or_create

            # `bundle_id` is best-effort — the daemon was already created by T2
            # under the real bundle_id, so this lookup hits the cache.
            daemon = await get_or_create(
                pid=target.element.pid,
                ws_url=ws_url,
                bundle_id=target.element.bundle_id or "",
                client_factory=self._cdp_client_factory,
            )
            for evt in ("mousePressed", "mouseReleased"):
                await daemon.call(
                    "Input.dispatchMouseEvent",
                    {
                        "type": evt,
                        "x": cx,
                        "y": cy,
                        "button": "left",
                        "clickCount": 1,
                    },
                    session_id=target.cdp_session_id,
                )
        except Exception as exc:  # noqa: BLE001 — never raise across channel boundary
            _log.warning("c5.fire_error", action_id=action.id, error=str(exc))
            return ChannelOutcome(channel="C5", status="errored", error=str(exc))

        return ChannelOutcome(
            channel="C5", status="fired", fired_at_ns=time.monotonic_ns()
        )
