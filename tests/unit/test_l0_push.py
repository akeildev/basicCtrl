"""Unit tests for L0Push consumer + WeightedVote per-action-class table.

Critical math contract under test (BLOCKER 1 from planning iter 1):
    WeightedVote.aggregate() RENORMALIZES BY SUM OF WEIGHTS OF
    PRESENT-NON-ZERO SIGNALS, not by total weight. Without this, the
    Calculator demo's single-signal click would resolve to confidence
    < 0.50 and the demo would fail. With renormalization,
    ``ax.value_changed=1.0`` alone resolves to 1.0 — well above the
    0.50 VERIFIED threshold.

CLAUDE.md hard rule under test (Test 3):
    L0 must NEVER poll AX. Source-grep enforces no walk_subtree /
    AXUIElementCopyAttributeValue / read_attribute calls.
"""
from __future__ import annotations

import asyncio
import inspect
import time
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from basicctrl.ax.observer import AXEvent
from basicctrl.state.graph import Bbox, Source, UIElement
from basicctrl.verifier.ensemble.l0_push import L0Push
from basicctrl.verifier.ensemble.weighted_vote import (
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


def _make_event(notif: str = "AXValueChanged", action_id: str = "act-123") -> AXEvent:
    return AXEvent(
        pid=999,
        element_key="bbox:com.apple.Calculator:AXButton:120:220",
        notif=notif,
        user_info=None,
        event_ts_ns=time.monotonic_ns(),
        action_id=action_id,
    )


class _MockAXManager:
    """Stand-in for AXObserverManager. Returns a controllable expect() result."""

    def __init__(self, event: Optional[AXEvent] = None, *, never_resolve: bool = False) -> None:
        self._event = event
        self._never_resolve = never_resolve

    async def expect(
        self,
        target: UIElement,
        notifs: list[str],
        action_id: str,
        timeout_ms: int = 500,
        ax_element: Any = None,
    ) -> AXEvent:
        if self._never_resolve:
            await asyncio.sleep(timeout_ms / 1000.0 + 0.01)
            raise asyncio.TimeoutError()
        if self._event is None:
            raise asyncio.TimeoutError()
        return self._event


# ----------------------------------------------------------------- Test 1


@pytest.mark.asyncio
async def test_collect_returns_axvalue_changed_when_event_fires() -> None:
    target = _make_target()
    mgr = _MockAXManager(_make_event(notif="AXValueChanged"))
    l0 = L0Push(axmgr=mgr)  # type: ignore[arg-type]

    signals = await l0.collect(
        target=target,
        notifs=["AXValueChanged"],
        action_id="act-123",
        timeout_ms=100,
    )

    assert signals["ax.value_changed"] == 1.0
    assert signals["ax.focused_changed"] == 0.0


# ----------------------------------------------------------------- Test 2


@pytest.mark.asyncio
async def test_collect_returns_zeros_on_timeout() -> None:
    target = _make_target()
    mgr = _MockAXManager(never_resolve=True)
    l0 = L0Push(axmgr=mgr)  # type: ignore[arg-type]

    t0 = time.monotonic()
    signals = await l0.collect(
        target=target,
        notifs=["AXValueChanged"],
        action_id="act-123",
        timeout_ms=20,
    )
    elapsed = time.monotonic() - t0

    assert signals["ax.value_changed"] == 0.0
    # 20ms timeout + small slack
    assert elapsed < 0.20


# ----------------------------------------------------------------- Test 3


def test_no_polling_used() -> None:
    """L0 is push-only; no walker, no Copy*, no read_attribute."""
    src = inspect.getsource(L0Push)
    forbidden = ["walk_subtree", "AXUIElementCopyAttributeValue", "read_attribute"]
    for needle in forbidden:
        assert needle not in src, f"L0Push source contains polling call: {needle}"


# ----------------------------------------------------------------- Test 4


def test_weighted_vote_click_full_signal() -> None:
    """All listed click signals fire at full strength → confidence == 1.0."""
    vote = WeightedVote()
    confidence = vote.aggregate(
        "click",
        {
            "ax.value_changed": 1.0,
            "ax.focused_changed": 1.0,
            "l1.window_diff": 0.0,
            "l1.dhash_changed": 0.0,
        },
    )
    # Renormalization: only ax.* are present-non-zero. Both fire at 1.0
    # → weighted_sum = 0.6 + 0.4 = 1.0; active_total = 0.6 + 0.4 = 1.0; ratio = 1.0.
    assert confidence == 1.0
    assert confidence >= VERIFIED_THRESHOLD


# ----------------------------------------------------------------- Test 4a (BLOCKER 1 anchor)


def test_weighted_vote_renormalizes_single_signal() -> None:
    """Single-signal click resolves to 1.0 under present-signal renormalization.

    THIS IS THE BLOCKER 1 FIX FROM PLANNING ITER 1: without renormalization,
    a single ``ax.value_changed=1.0`` would resolve to ``0.6 / 1.9 ≈ 0.32``
    and the Calculator demo would fail. With renormalization, the absent
    signals are EXCLUDED (not averaged in as zero), and the ratio is
    ``0.6 / 0.6 = 1.0``.
    """
    vote = WeightedVote()
    confidence = vote.aggregate("click", {"ax.value_changed": 1.0})
    assert confidence == 1.0
    assert confidence >= VERIFIED_THRESHOLD


# ----------------------------------------------------------------- Test 4b (Calculator scenario)


def test_weighted_vote_calculator_scenario() -> None:
    """Realistic Calculator click: AX fires + ROI dHash flips. Result == 1.0."""
    vote = WeightedVote()
    confidence = vote.aggregate(
        "click",
        {"ax.value_changed": 1.0, "l1.dhash_changed": 1.0},
    )
    # Renormalization: active = ax.value_changed (0.6) + l1.dhash_changed (0.3)
    # weighted_sum = 1.0*0.6 + 1.0*0.3 = 0.9
    # active_total = 0.9
    # ratio = 1.0
    assert confidence == 1.0
    assert confidence >= VERIFIED_THRESHOLD


# ----------------------------------------------------------------- Test 4c (absent signals)


def test_weighted_vote_absent_signal_does_not_drag_down() -> None:
    """Absent-and-zero signals are excluded from renormalization."""
    vote = WeightedVote()
    confidence = vote.aggregate(
        "click",
        {
            "ax.value_changed": 1.0,
            "ax.focused_changed": 0.0,  # absent (zero)
            "cdp.dom_modified": 0.0,    # absent (zero)
        },
    )
    # active = {ax.value_changed: 0.6}; ratio = 1.0
    assert confidence == 1.0


# ----------------------------------------------------------------- Test 5


def test_weighted_vote_click_zero_signal() -> None:
    """All listed signals at 0.0 → confidence < 0.30 (escalate-to-L3)."""
    vote = WeightedVote()
    confidence = vote.aggregate(
        "click",
        {"ax.value_changed": 0.0, "ax.focused_changed": 0.0},
    )
    assert confidence < L3_ESCALATE_THRESHOLD
    assert confidence == 0.0


# ----------------------------------------------------------------- Test 6


def test_weighted_vote_unknown_action_returns_zero() -> None:
    """Unknown action class falls open at 0 (Plan 06 escalates to L3)."""
    vote = WeightedVote()
    confidence = vote.aggregate("rocket_launch", {"ax.value_changed": 1.0})
    assert confidence == 0.0


# ----------------------------------------------------------------- Test 7


def test_weighted_vote_normalizes_to_unit_interval() -> None:
    """Output always in [0.0, 1.0] inclusive — even with malformed signal values."""
    vote = WeightedVote()
    # Even with a signal value > 1.0, output is clamped at 1.0.
    confidence = vote.aggregate("click", {"ax.value_changed": 5.0})
    assert 0.0 <= confidence <= 1.0
    # And with all zeros.
    confidence = vote.aggregate("click", {"ax.value_changed": 0.0})
    assert 0.0 <= confidence <= 1.0


# ----------------------------------------------------------------- Test 8


def test_weights_table_has_required_action_classes() -> None:
    """WEIGHTS contains the four action classes the verifier ensemble supports."""
    required = {"click", "type", "scroll", "set_value"}
    assert required.issubset(set(WeightedVote.WEIGHTS.keys()))
