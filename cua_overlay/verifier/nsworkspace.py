"""NSWorkspaceObserver — frontmost-app-changed via NSNotificationCenter.

NSWorkspace's notification center delivers app-launch / app-quit /
frontmost-app-change notifications. These run on a registered NSOperationQueue;
we use a dedicated queue (NOT the main queue) so we don't fight the asyncio
loop.

Each notification is bridged into asyncio via ``loop.call_soon_threadsafe``
identical to AXEventBridge. Phase 1 wires only the frontmost-app-change
notification; the full set (Did/Will Launch / Terminate / Activate / Hide /
Unhide) lands in Phase 2 if needed.

Per VERIFY-02 — NSWorkspace + DistributedNotificationCenter + CDP DOM mutation
+ kqueue subscriptions. This module owns the NSWorkspace slice.
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

import structlog


class NSWorkspaceObserver:
    """Subscribe to ``NSWorkspaceDidActivateApplicationNotification``.

    Each notification carries a userInfo dict whose ``NSWorkspaceApplicationKey``
    is an NSRunningApplication; we extract bundleIdentifier + processIdentifier
    and hand off to asyncio.

    Lifecycle:
        obs = NSWorkspaceObserver(loop)
        obs.on_frontmost_change(lambda bundle, pid: ...)
        obs.start()
        # ... user clicks Calculator dock icon ...
        obs.stop()
    """

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self._observer: Any = None
        self._callbacks: list[Callable[[str, int], None]] = []
        self._log = structlog.get_logger()

    def start(self) -> None:
        """Register the observer on a dedicated NSOperationQueue."""
        if self._observer is not None:
            return
        try:
            from AppKit import (  # type: ignore[import-not-found]
                NSWorkspace,
                NSWorkspaceDidActivateApplicationNotification,
            )
            from Foundation import NSOperationQueue  # type: ignore[import-not-found]
        except ImportError:
            self._log.warning("nsworkspace.pyobjc_unavailable")
            return

        ws = NSWorkspace.sharedWorkspace()
        nc = ws.notificationCenter()
        # Dedicated queue keeps notifications off the main thread (and away
        # from the asyncio loop's thread); the block below uses
        # call_soon_threadsafe to bridge.
        queue = NSOperationQueue.alloc().init()

        loop = self.loop
        callbacks = self._callbacks

        def _handler(notif: Any) -> None:
            user_info = notif.userInfo()
            if user_info is None:
                return
            app = user_info.get("NSWorkspaceApplicationKey")
            if app is None:
                return
            bundle_id = str(app.bundleIdentifier() or "")
            pid = int(app.processIdentifier())
            for cb in list(callbacks):
                loop.call_soon_threadsafe(cb, bundle_id, pid)

        self._observer = nc.addObserverForName_object_queue_usingBlock_(
            NSWorkspaceDidActivateApplicationNotification,
            None,
            queue,
            _handler,
        )

    def stop(self) -> None:
        """Remove the observer registration."""
        if self._observer is None:
            return
        try:
            from AppKit import NSWorkspace  # type: ignore[import-not-found]

            nc = NSWorkspace.sharedWorkspace().notificationCenter()
            nc.removeObserver_(self._observer)
        except (ImportError, Exception):  # pragma: no cover — defensive
            pass
        self._observer = None
        self._callbacks.clear()

    def on_frontmost_change(self, callback: Callable[[str, int], None]) -> None:
        """Register a callback. Signature: ``(bundle_id, pid) -> None``.

        Multiple callbacks are supported and fire in registration order.
        """
        self._callbacks.append(callback)
