"""AXEventBridge — CFRunLoop dedicated thread + asyncio Queue handoff.

Pattern A from 01-RESEARCH.md (the well-trodden path used by atomacos, MacPaw
Screen2AX, and ghost-os):

* Spawn a single ``threading.Thread`` whose target is ``CFRunLoopRun()``.
* That thread owns ``CFRunLoopGetCurrent()`` — every ``AXObserverCreate`` call
  registers a CFRunLoop source on it.
* AXObserver callbacks fire on the CFRunLoop thread, NOT the asyncio thread.
* Each callback hands the event off via ``loop.call_soon_threadsafe`` —
  this is the cross-thread bridge into asyncio.Queue.

The asyncio side awaits ``bridge.queue.get()``. Never call PyObjC AX functions
from the asyncio loop thread directly — they require a CFRunLoop and fight the
asyncio loop's scheduler.

This module is the foundation for ``cua_overlay.verifier.axobserver``'s
``AXObserverManager.expect()`` — the subscribe-before-fire pattern that
mitigates Pitfall P28 (stale notification race) via:

1. ``subscription_ts_ns`` recorded at subscribe-time (5 ms guard filter)
2. ``action_id`` passed via the AXObserver refcon (per-action tagging)

Per CLAUDE.md hard rule: "Always subscribe AXObserver push notifications BEFORE
the action fires." The ``Subscription`` returned from ``subscribe()`` carries
the timestamp anchor that the verifier-layer filter uses to discard stale
events.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import structlog

from cua_overlay.ax.errors import axerror_from_code


@dataclass(frozen=True)
class AXEvent:
    """A push notification observed on the CFRunLoop thread.

    ``event_ts_ns`` is captured inside the AX callback the moment we first see
    the event — so ``event_ts_ns >= subscription_ts_ns + 5_000_000`` is the
    Pitfall-P28 stale guard.
    """

    pid: int
    element_key: str
    notif: str
    user_info: Any
    event_ts_ns: int
    action_id: Optional[str]


@dataclass
class Subscription:
    """A registered AX observer + its anchor timestamps.

    ``subscription_ts_ns`` is the ground truth for the 5 ms stale-event guard
    (Pitfall P28). It's set by ``AXEventBridge.subscribe()`` BEFORE
    ``AXObserverAddNotification`` returns control.
    """

    pid: int
    element_key: str
    notifications: list[str]
    action_id: str
    subscription_ts_ns: int  # Pitfall P28 anchor — 5ms guard reference
    _observer: Any = None  # AXObserverRef (PyObjC opaque)
    _runloop_source: Any = None
    _filter: Optional[Callable[[AXEvent], bool]] = None
    _ax_element: Any = None


class AXEventBridge:
    """Dedicated CFRunLoop thread + asyncio Queue bridge for AX push events.

    Lifecycle:
        bridge = AXEventBridge(loop)
        bridge.start()       # spawns CFRunLoop thread, blocks until ready
        sub = bridge.subscribe(pid, ax_element, "calc/AXButton[5]", ["AXValueChanged"], "act-123")
        event = await bridge.queue.get()  # waits for cross-thread handoff
        bridge.stop()        # CFRunLoopStop + thread join

    Threading invariant: every interaction with the AX framework must happen on
    the CFRunLoop thread. ``subscribe()`` synchronously schedules the
    ``AXObserverCreate`` + ``AXObserverAddNotification`` calls — the underlying
    PyObjC C API is thread-safe enough that we can call from outside the
    CFRunLoop thread, but the resulting AX run-loop source is always added to
    the dedicated thread's run loop (so callbacks fire there).
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.queue: asyncio.Queue[AXEvent] = asyncio.Queue()
        self._thread: Optional[threading.Thread] = None
        self._cfrunloop: Any = None
        self._observers: dict[int, Any] = {}  # pid -> AXObserver
        self._subscriptions: list[Subscription] = []
        self._log = structlog.get_logger()

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Spawn the CFRunLoop-owning thread; block until the run loop is live.

        Idempotent — calling start() on an already-started bridge is a no-op.
        """
        if self._thread is not None:
            return
        ready = threading.Event()

        def _runloop_target() -> None:
            try:
                from CoreFoundation import CFRunLoopGetCurrent, CFRunLoopRun
            except ImportError:
                # PyObjC unavailable (CI without macOS). Mark ready so caller
                # doesn't deadlock — bridge will still queue events injected by
                # tests but won't deliver real AX callbacks.
                ready.set()
                return
            self._cfrunloop = CFRunLoopGetCurrent()
            ready.set()
            CFRunLoopRun()  # blocks until CFRunLoopStop

        self._thread = threading.Thread(
            target=_runloop_target, name="cua-cfrunloop", daemon=True
        )
        self._thread.start()
        if not ready.wait(timeout=2.0):
            raise RuntimeError("CFRunLoop thread did not become ready within 2s")

    def stop(self) -> None:
        """Stop the CFRunLoop and join the thread.

        Safe to call multiple times. Safe to call even if start() was never
        called (no-op).
        """
        if self._cfrunloop is not None:
            try:
                from CoreFoundation import CFRunLoopStop

                CFRunLoopStop(self._cfrunloop)
            except ImportError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._cfrunloop = None
        self._observers.clear()
        self._subscriptions.clear()

    # ------------------------------------------------------------------ subscribe

    def subscribe(
        self,
        pid: int,
        element: Any,
        element_key: str,
        notifications: list[str],
        action_id: str,
    ) -> Subscription:
        """Register a push subscription BEFORE the action fires.

        Critical sequence:
        1. Record ``subscription_ts_ns = time.monotonic_ns()`` IMMEDIATELY.
           This is the anchor for the Pitfall-P28 5ms stale guard.
        2. Create or reuse the per-pid AXObserver.
        3. AddNotification(observer, element, notif, action_id_as_refcon)
           for each notif.
        4. Add the observer's run-loop source to the CFRunLoop thread.

        On PyObjC unavailability (CI / non-macOS), returns a record-only
        Subscription with subscription_ts_ns set — tests inject events directly
        into ``self.queue`` and the verifier filter still works.
        """
        # P28 anchor — record BEFORE any AX call so the 5 ms guard can never lag.
        sub = Subscription(
            pid=pid,
            element_key=element_key,
            notifications=list(notifications),
            action_id=action_id,
            subscription_ts_ns=time.monotonic_ns(),
            _ax_element=element,
        )

        try:
            from HIServices import (  # type: ignore[import-not-found]
                AXObserverAddNotification,
                AXObserverCreate,
                AXObserverGetRunLoopSource,
            )
            from CoreFoundation import (  # type: ignore[import-not-found]
                CFRunLoopAddSource,
                kCFRunLoopDefaultMode,
            )
        except ImportError:
            # Fail-open: subscription record exists for the verifier filter to
            # use. Tests + CI without PyObjC still exercise the filter path.
            self._subscriptions.append(sub)
            return sub

        # Bind the bridge's loop into the closure so the C callback can hand
        # off across threads via call_soon_threadsafe.
        loop = self.loop
        queue = self.queue

        def _callback(
            observer: Any,
            axelem: Any,
            notif_name: Any,
            user_info_ref: Any,
            refcon: Any,
        ) -> None:
            # CALLBACK FIRES ON CFRunLoop THREAD — NOT asyncio thread.
            event = AXEvent(
                pid=pid,
                element_key=element_key,
                notif=str(notif_name),
                user_info=user_info_ref,
                event_ts_ns=time.monotonic_ns(),
                action_id=str(refcon) if refcon is not None else None,
            )
            # Cross-thread hand-off: the only way to safely insert into an
            # asyncio.Queue from a non-loop thread.
            loop.call_soon_threadsafe(queue.put_nowait, event)

        if pid not in self._observers:
            err, observer = AXObserverCreate(pid, _callback, None)
            if err != 0:
                raise axerror_from_code(err, f"AXObserverCreate(pid={pid}) failed")
            self._observers[pid] = observer
            source = AXObserverGetRunLoopSource(observer)
            if self._cfrunloop is not None:
                CFRunLoopAddSource(self._cfrunloop, source, kCFRunLoopDefaultMode)
            sub._observer = observer
            sub._runloop_source = source

        observer = self._observers[pid]
        for notif in notifications:
            # action_id passed as refcon -> echoed back to _callback so we can
            # filter for "this specific action's events" (Pitfall P28 part 2).
            err = AXObserverAddNotification(
                observer, element, notif, action_id.encode() if isinstance(action_id, str) else action_id
            )
            if err != 0 and err != -25209:  # kAXErrorNotificationAlreadyRegistered: ok
                self._log.warning(
                    "axobserver.add_notification_failed",
                    code=err,
                    notif=notif,
                    pid=pid,
                )
        self._subscriptions.append(sub)
        return sub
