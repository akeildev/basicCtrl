"""Unit tests for the AXObserver three-predicate filter and AXObserverManager.expect().

Tests run against a MockBridge that exposes the same surface AXEventBridge does
(``.queue`` and ``.subscribe()``) without spawning a CFRunLoop thread or
needing PyObjC.

The filter contract under test (Pitfall P28 mitigation):
  1. ``event_ts_ns < subscription_ts_ns + 5_000_000`` -> drop (5ms stale guard)
  2. ``event.action_id != sub.action_id`` -> drop
  3. ``event.notif not in notifs`` -> drop
  4. otherwise -> resolve future
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import pytest

from cua_overlay.ax.observer import AXEvent, Subscription
from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.verifier.axobserver import AXObserverManager, _passes_filter


# ----------------------------------------------------------------- fixtures


def _make_uielement(pid: int = 999, label: str = "Five") -> UIElement:
    now = datetime.now(timezone.utc)
    return UIElement(
        role="AXButton",
        role_path="AXApplication/AXWindow/AXButton[5]",
        label=label,
        bbox=Bbox(x=100.0, y=200.0, w=40.0, h=40.0),
        source=[Source.AX],
        discovered_at=now,
        last_seen_at=now,
        pid=pid,
        bundle_id="com.apple.Calculator",
        window_id=1,
    )


def _make_sub(
    pid: int = 999,
    action_id: str = "act-123",
    notifs: list[str] | None = None,
    ts_ns: int | None = None,
) -> Subscription:
    return Subscription(
        pid=pid,
        element_key="bbox:com.apple.Calculator:AXButton:120:220",
        notifications=list(notifs or ["AXValueChanged"]),
        action_id=action_id,
        subscription_ts_ns=ts_ns if ts_ns is not None else time.monotonic_ns(),
    )


def _make_event(
    pid: int = 999,
    notif: str = "AXValueChanged",
    action_id: str | None = "act-123",
    ts_ns: int | None = None,
) -> AXEvent:
    return AXEvent(
        pid=pid,
        element_key="bbox:com.apple.Calculator:AXButton:120:220",
        notif=notif,
        user_info=None,
        event_ts_ns=ts_ns if ts_ns is not None else time.monotonic_ns(),
        action_id=action_id,
    )


class MockBridge:
    """Test double that mimics AXEventBridge surface area without CFRunLoop.

    ``subscribe()`` records the Subscription with a controllable
    ``subscription_ts_ns``. Tests inject events via ``await mock.queue.put(event)``.
    """

    def __init__(self, subscription_ts_ns_override: int | None = None) -> None:
        self.queue: asyncio.Queue[AXEvent] = asyncio.Queue()
        self.subscriptions: list[Subscription] = []
        self.ts_override = subscription_ts_ns_override

    def subscribe(
        self,
        pid: int,
        element: Any,
        element_key: str,
        notifications: list[str],
        action_id: str,
    ) -> Subscription:
        sub = Subscription(
            pid=pid,
            element_key=element_key,
            notifications=list(notifications),
            action_id=action_id,
            subscription_ts_ns=(
                self.ts_override
                if self.ts_override is not None
                else time.monotonic_ns()
            ),
            _ax_element=element,
        )
        self.subscriptions.append(sub)
        return sub


# ------------------------------------------------------------- filter tests


def test_filter_drops_pre_subscription_events() -> None:
    """5ms stale-event guard (Pitfall P28 anchor 1).

    With subscription_ts_ns = 1_000_000_000 and event_ts_ns = 1_002_000_000
    (only 2 ms after subscribe), filter returns False. With event_ts_ns =
    1_006_000_000 (6 ms after), filter returns True.
    """
    sub = _make_sub(ts_ns=1_000_000_000)

    # 2ms post-subscribe -> dropped
    early = _make_event(ts_ns=1_002_000_000)
    assert _passes_filter(early, sub, {"AXValueChanged"}) is False

    # 6ms post-subscribe -> kept
    late = _make_event(ts_ns=1_006_000_000)
    assert _passes_filter(late, sub, {"AXValueChanged"}) is True


def test_filter_drops_wrong_action_id() -> None:
    """Pitfall P28 anchor 2: action_id mismatch drops the event."""
    base_ts = 1_000_000_000
    sub = _make_sub(action_id="abc-123", ts_ns=base_ts)

    # Different action_id, but post-subscription -> dropped
    wrong_id = _make_event(action_id="xyz-456", ts_ns=base_ts + 10_000_000)
    assert _passes_filter(wrong_id, sub, {"AXValueChanged"}) is False

    # Same action_id, post-subscription -> kept
    right_id = _make_event(action_id="abc-123", ts_ns=base_ts + 10_000_000)
    assert _passes_filter(right_id, sub, {"AXValueChanged"}) is True


def test_filter_drops_unwanted_notif() -> None:
    """Notif not in requested set is dropped (correctness)."""
    base_ts = 1_000_000_000
    sub = _make_sub(ts_ns=base_ts, notifs=["AXValueChanged"])

    # Title changed, but we only asked for value changed -> dropped
    wrong_notif = _make_event(notif="AXTitleChanged", ts_ns=base_ts + 10_000_000)
    assert _passes_filter(wrong_notif, sub, {"AXValueChanged"}) is False

    # Value changed, in our set -> kept
    right_notif = _make_event(notif="AXValueChanged", ts_ns=base_ts + 10_000_000)
    assert _passes_filter(right_notif, sub, {"AXValueChanged"}) is True


def test_filter_keeps_valid_event() -> None:
    """All three predicates satisfied -> True."""
    base_ts = 1_000_000_000
    sub = _make_sub(action_id="act-99", ts_ns=base_ts)
    event = _make_event(action_id="act-99", ts_ns=base_ts + 10_000_000)
    assert _passes_filter(event, sub, {"AXValueChanged"}) is True


# ----------------------------------------------------- expect() integration


@pytest.mark.asyncio
async def test_expect_resolves_on_event() -> None:
    """expect() returns the future; injecting matching event resolves it."""
    bridge = MockBridge()
    manager = AXObserverManager(bridge)  # type: ignore[arg-type]
    manager.start()

    target = _make_uielement(pid=999)

    # Subscribe BEFORE we inject the event — the contract.
    expect_task = asyncio.create_task(
        manager.expect(target, ["AXValueChanged"], action_id="act-123", timeout_ms=500)
    )

    # Yield control so expect() runs and registers the waiter.
    await asyncio.sleep(0.01)

    # Inject a matching event > 5 ms after subscribe.
    sub = bridge.subscriptions[0]
    matching = _make_event(
        pid=999,
        action_id="act-123",
        ts_ns=sub.subscription_ts_ns + 10_000_000,
    )
    await bridge.queue.put(matching)

    result = await expect_task
    assert result.notif == "AXValueChanged"
    assert result.action_id == "act-123"
    await manager.stop()


@pytest.mark.asyncio
async def test_expect_times_out() -> None:
    """No event injected -> asyncio.TimeoutError raised after timeout_ms."""
    bridge = MockBridge()
    manager = AXObserverManager(bridge)  # type: ignore[arg-type]
    manager.start()

    target = _make_uielement(pid=999)

    with pytest.raises(asyncio.TimeoutError):
        await manager.expect(
            target, ["AXValueChanged"], action_id="act-no-event", timeout_ms=50
        )

    await manager.stop()


@pytest.mark.asyncio
async def test_subscription_ts_ns_recorded_at_expect_time() -> None:
    """subscription_ts_ns must be recorded at expect-time (between t_before and t_after)."""
    bridge = MockBridge()
    manager = AXObserverManager(bridge)  # type: ignore[arg-type]
    manager.start()

    target = _make_uielement(pid=999)

    t_before = time.monotonic_ns()
    # Don't await the timeout; just kick off expect() and let it record the sub.
    task = asyncio.create_task(
        manager.expect(target, ["AXValueChanged"], action_id="act-ts", timeout_ms=50)
    )
    await asyncio.sleep(0.005)  # let expect() run far enough to register
    t_after = time.monotonic_ns()

    assert len(bridge.subscriptions) == 1
    sub = bridge.subscriptions[0]
    assert t_before <= sub.subscription_ts_ns <= t_after, (
        f"subscription_ts_ns={sub.subscription_ts_ns} not in [{t_before}, {t_after}]"
    )

    # Let the timeout fire to clean up.
    with pytest.raises(asyncio.TimeoutError):
        await task
    await manager.stop()


@pytest.mark.asyncio
async def test_dispatcher_routes_event_through_filter() -> None:
    """Dispatcher integration: stale event injected -> waiter does NOT resolve.

    This is the 4th P28 verification: the dispatcher loop applies the filter
    end-to-end (not just the standalone _passes_filter() function).
    """
    bridge = MockBridge()
    manager = AXObserverManager(bridge)  # type: ignore[arg-type]
    manager.start()

    target = _make_uielement(pid=999)
    expect_task = asyncio.create_task(
        manager.expect(target, ["AXValueChanged"], action_id="act-stale", timeout_ms=100)
    )
    await asyncio.sleep(0.01)

    sub = bridge.subscriptions[0]
    # Stale: well before subscription_ts_ns
    stale = _make_event(
        pid=999,
        action_id="act-stale",
        ts_ns=sub.subscription_ts_ns - 1_000_000_000,
    )
    await bridge.queue.put(stale)

    # The filter should drop the stale event; expect() should still time out.
    with pytest.raises(asyncio.TimeoutError):
        await expect_task

    await manager.stop()
