"""Unit tests for Aggregator — top-level verifier entry that wires
L0 push + L1 cheap → WeightedVote → HoarePost.

The Aggregator is the public surface Plan 06 (L2/L3 escalation), Plan 08
(MCP proxy), and Plan 09 (Calculator demo) consume. The contract:

* L0 + L1 run IN PARALLEL via ``anyio.create_task_group``.
* Confidence ≥ 0.50 → ``HoarePost.verified == True``.
* Confidence < 0.30 → caller (Plan 06) escalates to L3.
* ``HoarePost.target_key`` mirrors ``target.composite_key``.
* ``action.action_type`` drives weight selection in WeightedVote.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

import pytest

from cua_overlay.state.causal_dag import ActionCanonical, HoarePost
from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.verifier.aggregator import Aggregator
from cua_overlay.verifier.ensemble.l1_cheap import L1Snapshot
from cua_overlay.verifier.ensemble.weighted_vote import (
    L3_ESCALATE_THRESHOLD,
    VERIFIED_THRESHOLD,
    WeightedVote,
)


# ----------------------------------------------------------------- helpers


def _make_target(pid: int = 999) -> UIElement:
    now = datetime.now(timezone.utc)
    return UIElement(
        role="AXButton",
        role_path="AXApplication/AXWindow/AXButton[5]",
        label="5",
        bbox=Bbox(x=100.0, y=200.0, w=40.0, h=40.0),
        source=[Source.AX],
        discovered_at=now,
        last_seen_at=now,
        pid=pid,
        bundle_id="com.apple.Calculator",
        window_id=1,
    )


def _make_action(action_type: str = "click") -> ActionCanonical:
    return ActionCanonical(
        id="act-123",
        step_idx=0,
        kind="MUTATE",
        target_key="bbox:com.apple.Calculator:AXButton:120:220",
        action_type=action_type,
        payload={},
        timestamp_ns=time.monotonic_ns(),
        session_id="sess-1",
    )


def _make_l1_snapshot() -> L1Snapshot:
    return L1Snapshot(
        window_list={},
        pasteboard_change_count=0,
        roi_dhash=None,
        captured_at=time.monotonic(),
    )


class _MockL0:
    """Stand-in for L0Push. Returns a controllable signal dict."""

    def __init__(
        self,
        signals: Optional[dict[str, float]] = None,
        *,
        sleep_s: float = 0.0,
    ) -> None:
        self._signals = signals or {}
        self._sleep_s = sleep_s

    async def collect(
        self,
        target: UIElement,
        notifs: list[str],
        action_id: str,
        timeout_ms: int = 50,
        ax_element: Any = None,
    ) -> dict[str, float]:
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return dict(self._signals)


class _MockL1:
    """Stand-in for L1Cheap.run. Returns a controllable signal dict."""

    def __init__(
        self,
        signals: Optional[dict[str, float]] = None,
        *,
        sleep_s: float = 0.0,
    ) -> None:
        self._signals = signals or {}
        self._sleep_s = sleep_s

    async def run(self, target: UIElement, before: L1Snapshot) -> dict[str, float]:
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return dict(self._signals)


class _SpyVote:
    """WeightedVote stand-in that records the action_class it was called with."""

    def __init__(self, return_value: float = 0.0) -> None:
        self._return_value = return_value
        self.calls: list[tuple[str, dict[str, float]]] = []

    def aggregate(self, action_class: str, signals: Mapping[str, float]) -> float:
        self.calls.append((action_class, dict(signals)))
        return self._return_value


# ----------------------------------------------------------------- Test 1


@pytest.mark.asyncio
async def test_returns_hoare_post_with_signals() -> None:
    """HoarePost.tier_signals records per-tier max signal values."""
    target = _make_target()
    action = _make_action("click")
    l0 = _MockL0({"ax.value_changed": 1.0})
    l1 = _MockL1({"l1.window_diff": 0.5})
    agg = Aggregator(l0=l0, l1=l1, vote=WeightedVote())  # type: ignore[arg-type]

    result = await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
    )

    assert isinstance(result, HoarePost)
    assert "L0" in result.tier_signals
    assert "L1" in result.tier_signals
    # Non-None for layers that actually ran
    assert result.tier_signals["L0"] is not None
    assert result.tier_signals["L1"] is not None


# ----------------------------------------------------------------- Test 2


@pytest.mark.asyncio
async def test_l0_l1_run_in_parallel() -> None:
    """L0 and L1 run in parallel via anyio task group; total time ~30ms."""
    target = _make_target()
    action = _make_action("click")
    l0 = _MockL0({"ax.value_changed": 1.0}, sleep_s=0.030)
    l1 = _MockL1({"l1.window_diff": 0.5}, sleep_s=0.030)
    agg = Aggregator(l0=l0, l1=l1, vote=WeightedVote())  # type: ignore[arg-type]

    t0 = time.monotonic()
    await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
    )
    elapsed = time.monotonic() - t0

    # Sequential would be 60ms+; parallel should be ~30ms. 50ms gives slack.
    assert elapsed < 0.050, f"verify() took {elapsed:.3f}s; expected <0.050s parallel"


# ----------------------------------------------------------------- Test 3


@pytest.mark.asyncio
async def test_verified_when_confidence_above_05() -> None:
    target = _make_target()
    action = _make_action("click")
    # ax.value_changed=1.0 alone → confidence 1.0 (single-signal renorm)
    l0 = _MockL0({"ax.value_changed": 1.0})
    l1 = _MockL1({})
    agg = Aggregator(l0=l0, l1=l1, vote=WeightedVote())  # type: ignore[arg-type]

    result = await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
    )

    assert result.verified is True
    assert result.confidence >= VERIFIED_THRESHOLD


# ----------------------------------------------------------------- Test 4


@pytest.mark.asyncio
async def test_not_verified_when_confidence_below_05() -> None:
    target = _make_target()
    action = _make_action("click")
    # All signals zero → confidence 0.0
    l0 = _MockL0({})
    l1 = _MockL1({})
    agg = Aggregator(l0=l0, l1=l1, vote=WeightedVote())  # type: ignore[arg-type]

    result = await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
    )

    assert result.verified is False
    assert result.confidence < VERIFIED_THRESHOLD


# ----------------------------------------------------------------- Test 5


@pytest.mark.asyncio
async def test_hoare_post_consistency_with_threshold() -> None:
    """For confidence ∈ [0.0, 0.49, 0.50, 0.99]: verified is F, F, T, T."""
    target = _make_target()
    action = _make_action("click")

    cases = [(0.0, False), (0.49, False), (0.50, True), (0.99, True)]
    for confidence, expected_verified in cases:
        spy = _SpyVote(return_value=confidence)
        agg = Aggregator(l0=_MockL0({}), l1=_MockL1({}), vote=spy)  # type: ignore[arg-type]
        result = await agg.verify(
            action=action,
            target=target,
            notifs=["AXValueChanged"],
            before_l1=_make_l1_snapshot(),
        )
        assert result.verified is expected_verified, (
            f"confidence={confidence} -> verified={result.verified}, expected {expected_verified}"
        )


# ----------------------------------------------------------------- Test 6


@pytest.mark.asyncio
async def test_target_key_propagated() -> None:
    target = _make_target()
    action = _make_action("click")
    l0 = _MockL0({"ax.value_changed": 1.0})
    l1 = _MockL1({})
    agg = Aggregator(l0=l0, l1=l1, vote=WeightedVote())  # type: ignore[arg-type]

    result = await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
    )

    assert result.target_key == target.composite_key


# ----------------------------------------------------------------- Test 7


@pytest.mark.asyncio
async def test_action_class_routing() -> None:
    """action.action_type must be passed verbatim into WeightedVote.aggregate."""
    target = _make_target()
    spy = _SpyVote(return_value=1.0)
    agg = Aggregator(
        l0=_MockL0({"ax.value_changed": 1.0}),  # type: ignore[arg-type]
        l1=_MockL1({}),  # type: ignore[arg-type]
        vote=spy,  # type: ignore[arg-type]
    )

    for action_type in ("click", "type", "scroll", "set_value"):
        action = _make_action(action_type)
        await agg.verify(
            action=action,
            target=target,
            notifs=["AXValueChanged"],
            before_l1=_make_l1_snapshot(),
        )

    called_classes = [c[0] for c in spy.calls]
    assert called_classes == ["click", "type", "scroll", "set_value"]
