"""AXObserverManager — subscribe-before-fire orchestration on top of AXEventBridge.

Per ARCHITECTURE.md Pattern 1 (the secret weapon):

    Caller MUST `await expect(...)` BEFORE firing the action. This is the
    only way to mitigate Pitfall P28 (stale notifications race the verifier):

    1. ``subscription_ts_ns`` is captured at subscribe-time.
    2. The 5 ms guard discards any event whose ``event_ts_ns`` falls before
       ``subscription_ts_ns + 5_000_000``.
    3. Every action carries an ``action_id`` (UUID) that the AXObserver
       refcon echoes back; events with non-matching ``action_id`` are dropped.
    4. Events whose ``notif`` is NOT in the requested set are dropped.

The dispatcher loop (``_dispatch_loop``) consumes the bridge's asyncio.Queue
and routes each event to its matching waiter futures. The waiter table is
plain Python list to keep registration / removal explicit; we rarely have more
than a handful of pending waiters at once (verifier ladder fans out
fewer than 10 per action).
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import structlog

from cua_overlay.ax.observer import AXEvent, AXEventBridge, Subscription
from cua_overlay.state.graph import UIElement


# 5 ms stale-event guard. Pitfall P28 mitigation. The number comes directly
# from ARCHITECTURE.md L408-426 + 01-RESEARCH.md "Pre-subscribe pattern".
_GUARD_NS = 5_000_000


class AXObserverManager:
    """Subscribe-before-fire orchestration on top of ``AXEventBridge``.

    Lifecycle:
        manager = AXObserverManager(bridge)
        manager.start()                               # spawn dispatcher task
        fut = await manager.expect(target, ["AXValueChanged"], "act-123")
        # ... fire action via Channel C ...
        event = await fut                             # resolves on first match
        await manager.stop()                          # cancel dispatcher

    The waiter list is intentionally small-N — Phase 1 expects 1-2 waiters per
    action. Phase 3 (race orchestrator) may push that to 5-10; still cheap to
    iterate.
    """

    def __init__(self, bridge: AXEventBridge) -> None:
        self._bridge = bridge
        self._dispatcher_task: Optional[asyncio.Task[None]] = None
        # (subscription, future, requested-notif-set)
        self._waiters: list[tuple[Subscription, asyncio.Future[AXEvent], set[str]]] = []
        self._log = structlog.get_logger()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Spawn the dispatcher task that drains bridge.queue → waiters."""
        if self._dispatcher_task is None:
            self._dispatcher_task = asyncio.create_task(
                self._dispatch_loop(), name="ax-observer-dispatch"
            )

    async def stop(self) -> None:
        """Cancel the dispatcher and clear pending waiters."""
        if self._dispatcher_task is not None:
            self._dispatcher_task.cancel()
            try:
                await self._dispatcher_task
            except asyncio.CancelledError:
                pass
            self._dispatcher_task = None
        # Cancel any outstanding waiters so callers don't hang forever.
        for _sub, fut, _notifs in self._waiters:
            if not fut.done():
                fut.cancel()
        self._waiters.clear()

    # ---------------------------------------------------------------- expect

    async def expect(
        self,
        target: UIElement,
        notifs: list[str],
        action_id: str,
        timeout_ms: int = 500,
        ax_element: Any = None,
    ) -> AXEvent:
        """Subscribe-before-fire — returns first matching event or times out.

        Args:
            target: The UIElement we're operating on. ``target.pid`` and
                ``target.composite_key`` flow into the Subscription.
            notifs: e.g. ``["AXValueChanged", "AXFocusedUIElementChanged"]``.
                The first event matching ANY of these resolves the future.
            action_id: A UUID-or-similar string the caller will tag the action
                with. Used as the AXObserver refcon so we can drop events from
                OTHER waiters (Pitfall P28 part 2).
            timeout_ms: 500ms default — covers the slow channel (AppleScript at
                staggered_race tail) plus 100ms verifier slack.
            ax_element: The raw AXUIElement opaque ref. In Phase 1 callers
                supply this directly; Phase 2 the Translator layer fills it.

        Raises:
            asyncio.TimeoutError: if no matching event arrived in time. Caller
                escalates to L1 cheap diff per VERIFY-04..05.
        """
        # CRITICAL ORDER: subscribe FIRST, await fut SECOND. The action only
        # fires AFTER expect() returns the future — never before subscription_ts_ns
        # is recorded.
        sub = self._bridge.subscribe(
            pid=target.pid,
            element=ax_element,
            element_key=target.composite_key,
            notifications=notifs,
            action_id=action_id,
        )
        fut: asyncio.Future[AXEvent] = asyncio.get_running_loop().create_future()
        self._waiters.append((sub, fut, set(notifs)))
        try:
            return await asyncio.wait_for(fut, timeout=timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            # Drop the waiter so the table doesn't leak.
            self._waiters = [w for w in self._waiters if w[1] is not fut]
            raise

    # ---------------------------------------------------------------- dispatch

    async def _dispatch_loop(self) -> None:
        """Drain bridge.queue and resolve matching waiters.

        Each event is offered to every pending waiter in registration order;
        the first matching one wins (its future resolves and the waiter is
        removed). Multiple waiters may resolve from a single event burst if
        more than one matches — that's fine, each waiter has its own filter
        predicate.
        """
        while True:
            event = await self._bridge.queue.get()
            matched: list[asyncio.Future[AXEvent]] = []
            for sub, fut, notif_set in list(self._waiters):
                if fut.done():
                    continue
                if not _passes_filter(event, sub, notif_set):
                    continue
                fut.set_result(event)
                matched.append(fut)
            if matched:
                self._waiters = [w for w in self._waiters if w[1] not in matched]


def _passes_filter(event: AXEvent, sub: Subscription, notifs: set[str]) -> bool:
    """Three-predicate filter for Pitfall P28 + correctness.

    1. ``event_ts_ns >= subscription_ts_ns + 5_000_000ns`` (5 ms stale guard).
       Pitfall P28: in-flight kAXValueChanged events from ~50ms BEFORE our
       action can race the verifier. The 5 ms post-subscription guard
       discards them.
    2. ``event.action_id == sub.action_id``. Two waiters subscribing to the
       same notif on the same element must not poach each other's events.
    3. ``event.notif in notifs``. The bridge may forward AXValueChanged to a
       waiter that's only watching AXFocusedUIElementChanged — drop those.
    4. ``event.pid == sub.pid``. Defence in depth — should never fail unless
       the bridge has a bug, but cheap to check.
    """
    if event.event_ts_ns < sub.subscription_ts_ns + _GUARD_NS:
        return False
    if event.action_id != sub.action_id:
        return False
    if event.notif not in notifs:
        return False
    if event.pid != sub.pid:
        return False
    return True
