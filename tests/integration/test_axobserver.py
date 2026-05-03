"""End-to-end AXObserver integration tests against Calculator.app.

These tests demonstrate Phase 1 success criterion 1: a real Calculator click
fires kAXValueChanged within 50 ms via the L0 push-event subscription. They
require:

* macOS desktop session (PyObjC + AppKit)
* Calculator.app launchable
* Accessibility TCC granted to the test runner

Run with: ``uv run pytest -x -v -m integration tests/integration/test_axobserver.py``

The 50 ms latency check (Test 3) is the empirical anchor for ROADMAP success
criterion 1. Test 4 (stale-event drop) verifies the Pitfall P28 filter
end-to-end via the real bridge dispatcher (not just the standalone filter
function exercised in tests/unit/test_axobserver_filter.py).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import pytest

from basicctrl.ax.observer import AXEvent, AXEventBridge
from basicctrl.state.graph import Bbox, Source, UIElement
from basicctrl.verifier.axobserver import AXObserverManager


def _make_target(pid: int, bbox: Bbox, label: str = "Five") -> UIElement:
    now = datetime.now(timezone.utc)
    return UIElement(
        role="AXButton",
        role_path=f"AXApplication/AXWindow/AXButton[{label}]",
        label=label,
        bbox=bbox,
        source=[Source.AX],
        discovered_at=now,
        last_seen_at=now,
        pid=pid,
        bundle_id="com.apple.Calculator",
        window_id=0,
    )


def _resolve_button_5(pid: int) -> tuple[object, Bbox]:
    """Walk Calculator's AX tree to locate the '5' button.

    Returns (raw_AXUIElement, Bbox). We do a depth-limited manual walk here
    rather than going through Plan 01-03's walker (whose real impl lives in a
    sibling worktree and isn't available during Wave 2).

    NOTE: callers that subscribe to AXValueChanged should subscribe on the
    APPLICATION ROOT (use `_resolve_app(pid)`), not on the button. macOS 26
    Calculator fires AXValueChanged on its display element; the button itself
    never emits that notification. AXObserver propagates from descendants
    only when the subscription is on an ancestor, so the application root
    catches what the button cannot. Verified empirically — see
    .planning/INTEGRATION-DEBUG.md F1.
    """
    from HIServices import (  # type: ignore[import-not-found]
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
    )

    app = AXUIElementCreateApplication(pid)

    def _attr(elem: object, name: str) -> object:
        err, value = AXUIElementCopyAttributeValue(elem, name, None)
        return value if err == 0 else None

    # BFS to depth 8 — macOS 26 Calculator nests the keypad as
    # AXApplication/AXWindow/AXWindow/AXGroup/AXSplitGroup/AXGroup/AXGroup/AXButton
    # (depth 7 from the app root). Older Calculator builds were depth-4 but
    # the modern keypad needs more headroom.
    queue: list[tuple[object, int]] = [(app, 0)]
    seen = 0
    while queue and seen < 500:
        elem, depth = queue.pop(0)
        seen += 1

        role = _attr(elem, "AXRole")
        title = _attr(elem, "AXTitle") or _attr(elem, "AXDescription")
        if role == "AXButton" and title in ("5", "Five"):
            position = _attr(elem, "AXPosition")
            size = _attr(elem, "AXSize")
            try:
                x, y = float(position[0]), float(position[1])
                w, h = float(size[0]), float(size[1])
            except (TypeError, IndexError):
                x, y, w, h = 0.0, 0.0, 0.0, 0.0
            return elem, Bbox(x=x, y=y, w=w, h=h)

        if depth >= 8:
            continue
        children = _attr(elem, "AXChildren") or []
        for child in children[:50]:
            queue.append((child, depth + 1))

    raise RuntimeError("could not find Calculator '5' button in AX tree")


def _resolve_app(pid: int) -> object:
    """Return the AXApplication root for the given pid.

    Used as the subscription target for AXValueChanged etc. — see
    `_resolve_button_5` docstring for why we subscribe on the root rather
    than on the click target.
    """
    from HIServices import AXUIElementCreateApplication  # type: ignore[import-not-found]
    return AXUIElementCreateApplication(pid)


def _fire_cgevent_click(x: int, y: int) -> None:
    """Synthesise a CGEvent left-mouse click at (x, y).

    Note: this fires through the HID event tap; cursor warps. Phase 2's racing
    translator uses ``SLEventPostToPid`` (no cursor warp) but Plan 01-04 is
    just demonstrating the AXObserver path so plain CGEvent is fine.
    """
    from Quartz import (  # type: ignore[import-not-found]
        CGEventCreateMouseEvent,
        CGEventPost,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGHIDEventTap,
        kCGMouseButtonLeft,
    )

    down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, (x, y), kCGMouseButtonLeft)
    up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, (x, y), kCGMouseButtonLeft)
    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


# ------------------------------------------------------------------- tests


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pre_subscribe_records_subscription_ts(calculator_pid: int) -> None:
    """expect() registers a waiter whose subscription_ts_ns is fresh (<100ms old)."""
    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop)
    bridge.start()
    manager = AXObserverManager(bridge)
    manager.start()

    try:
        elem, bbox = _resolve_button_5(calculator_pid)
        # Subscribe on the application root, not the button — Calculator
        # fires AXValueChanged on its display element, not the button itself.
        # The root captures descendant events. See _resolve_button_5 docstring.
        app_root = _resolve_app(calculator_pid)
        target = _make_target(calculator_pid, bbox)

        t_before = time.monotonic_ns()
        # Fire-and-forget — we just want the subscription registered. We let
        # the wait_for time out shortly after.
        task = asyncio.create_task(
            manager.expect(
                target,
                ["AXValueChanged"],
                action_id="test-presub-1",
                timeout_ms=50,
                ax_element=app_root,
            )
        )
        await asyncio.sleep(0.005)
        t_after = time.monotonic_ns()

        # Inspect the dispatcher waiter table — exactly one entry tied to our
        # action_id, with a freshly-set subscription_ts_ns.
        assert len(manager._waiters) == 1
        sub, _fut, _notifs = manager._waiters[0]
        assert sub.action_id == "test-presub-1"
        assert t_before <= sub.subscription_ts_ns <= t_after, (
            f"subscription_ts_ns={sub.subscription_ts_ns} not in "
            f"[t_before={t_before}, t_after={t_after}]; "
            f"window={(t_after - t_before) / 1e6:.3f}ms"
        )

        with pytest.raises(asyncio.TimeoutError):
            await task
    finally:
        await manager.stop()
        bridge.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_axvalue_changed_fires_for_calculator_click(calculator_pid: int) -> None:
    """Real CGEvent click on '5' triggers a matching AXObserver event within 1s.

    Calculator may emit either AXValueChanged (display value updated) or
    AXFocusedUIElementChanged (focus moved to button) depending on macOS
    version — accept either.
    """
    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop)
    bridge.start()
    manager = AXObserverManager(bridge)
    manager.start()

    try:
        elem, bbox = _resolve_button_5(calculator_pid)
        # Subscribe on the application root, not the button — Calculator
        # fires AXValueChanged on its display element, not the button itself.
        # The root captures descendant events. See _resolve_button_5 docstring.
        app_root = _resolve_app(calculator_pid)
        target = _make_target(calculator_pid, bbox)

        # Subscribe BEFORE we fire the click — the contract.
        expect_task = asyncio.create_task(
            manager.expect(
                target,
                ["AXValueChanged", "AXFocusedUIElementChanged"],
                action_id="test-fire-2",
                timeout_ms=1000,
                ax_element=app_root,
            )
        )
        await asyncio.sleep(0.05)  # let subscription register on CFRunLoop

        # Fire the click at the bbox centroid
        cx = int(bbox.x + bbox.w / 2)
        cy = int(bbox.y + bbox.h / 2)
        _fire_cgevent_click(cx, cy)

        event: AXEvent = await expect_task
        assert event.notif in ("AXValueChanged", "AXFocusedUIElementChanged"), (
            f"unexpected notif: {event.notif}"
        )
        assert event.action_id == "test-fire-2"
        assert event.pid == calculator_pid
    finally:
        await manager.stop()
        bridge.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_event_within_50ms(calculator_pid: int) -> None:
    """SUCCESS CRITERION 1: event arrives within 50ms of the click.

    This is the strict latency bound — ROADMAP § Phase 1 requires <50ms via
    L0 push subscription. We measure ``event.event_ts_ns - start_ns``.
    """
    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop)
    bridge.start()
    manager = AXObserverManager(bridge)
    manager.start()

    try:
        elem, bbox = _resolve_button_5(calculator_pid)
        # Subscribe on the application root, not the button — Calculator
        # fires AXValueChanged on its display element, not the button itself.
        # The root captures descendant events. See _resolve_button_5 docstring.
        app_root = _resolve_app(calculator_pid)
        target = _make_target(calculator_pid, bbox)

        expect_task = asyncio.create_task(
            manager.expect(
                target,
                ["AXValueChanged", "AXFocusedUIElementChanged"],
                action_id="test-50ms",
                timeout_ms=1000,
                ax_element=app_root,
            )
        )
        await asyncio.sleep(0.05)

        cx = int(bbox.x + bbox.w / 2)
        cy = int(bbox.y + bbox.h / 2)
        start_ns = time.monotonic_ns()
        _fire_cgevent_click(cx, cy)

        event: AXEvent = await expect_task
        latency_ns = event.event_ts_ns - start_ns
        latency_ms = latency_ns / 1e6
        print(f"\n  AXValueChanged latency: {latency_ms:.2f}ms")
        assert latency_ns < 50_000_000, (
            f"AXObserver latency {latency_ms:.2f}ms exceeds 50ms budget "
            "(SUCCESS CRITERION 1 violated)"
        )
    finally:
        await manager.stop()
        bridge.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_stale_event_dropped(calculator_pid: int) -> None:
    """Pitfall P28: pre-subscription event injected directly into the queue is dropped.

    No real click here — we surface the dispatcher's filter on a stale event by
    hand-building one whose ``event_ts_ns`` predates ``subscription_ts_ns``.
    """
    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop)
    bridge.start()
    manager = AXObserverManager(bridge)
    manager.start()

    try:
        elem, bbox = _resolve_button_5(calculator_pid)
        # Subscribe on the application root, not the button — Calculator
        # fires AXValueChanged on its display element, not the button itself.
        # The root captures descendant events. See _resolve_button_5 docstring.
        app_root = _resolve_app(calculator_pid)
        target = _make_target(calculator_pid, bbox)

        expect_task = asyncio.create_task(
            manager.expect(
                target,
                ["AXValueChanged"],
                action_id="test-stale",
                timeout_ms=200,
                ax_element=app_root,
            )
        )
        await asyncio.sleep(0.05)

        # Dig the just-registered subscription out of the dispatcher table.
        assert manager._waiters, "no waiter registered"
        sub, _fut, _notifs = manager._waiters[0]

        stale = AXEvent(
            pid=calculator_pid,
            element_key=target.composite_key,
            notif="AXValueChanged",
            user_info=None,
            event_ts_ns=sub.subscription_ts_ns - 1,  # 1ns before subscribe
            action_id=sub.action_id,
        )
        await bridge.queue.put(stale)

        # Filter must drop the stale event; expect() should still time out.
        with pytest.raises(asyncio.TimeoutError):
            await expect_task
    finally:
        await manager.stop()
        bridge.stop()
