"""Unit tests for the Aggregator's L0 → L1 → L2 → L3 escalation ladder.

Per ARCHITECTURE.md L173:
    confidence >= 0.50 -> VERIFIED (no escalation)
    0.30 <= confidence < 0.50 -> escalate to L2 (Vision OCR + walker)
    confidence < 0.30 -> escalate to L3 (LLM, raises in Phase 1)

Per CLAUDE.md hard rule:
    "Always use deterministic ensemble first (L0→L1→L2). LLM (L3) only
    when ensemble confidence < 0.30."

Per Phase 1 invariant:
    L0+L1 strong → no L2 fire (the Calculator demo path).
    Out-of-band confidence (0.30..0.50) → L2 runs but L3 doesn't.
    Below 0.30 → L2 runs first; if still below 0.30, L3 stub raises;
    aggregator catches NotImplementedError, emits 'l3.unavailable_phase1'
    structured event, returns HoarePost(verified=False, confidence=<l2>).
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Optional
from unittest.mock import AsyncMock

import pytest
import structlog

from basicctrl.state.causal_dag import ActionCanonical, HoarePost
from basicctrl.state.graph import Bbox, Source, UIElement
from basicctrl.verifier.aggregator import Aggregator
from basicctrl.verifier.ensemble.l1_cheap import L1Snapshot
from basicctrl.verifier.ensemble.l2_medium import L2Snapshot
from basicctrl.verifier.ensemble.l3_llm import L3Stub
from basicctrl.verifier.ensemble.weighted_vote import (
    L3_ESCALATE_THRESHOLD,
    VERIFIED_THRESHOLD,
    WeightedVote,
)


# ----------------------------------------------------------------- helpers


def _make_target() -> UIElement:
    now = datetime.now(timezone.utc)
    return UIElement(
        role="AXButton",
        role_path="AXApplication/AXWindow/AXButton[5]",
        label="5",
        bbox=Bbox(x=100.0, y=200.0, w=40.0, h=40.0),
        source=[Source.AX],
        discovered_at=now,
        last_seen_at=now,
        pid=999,
        bundle_id="com.apple.Calculator",
        window_id=1,
    )


def _make_action(action_type: str = "click") -> ActionCanonical:
    return ActionCanonical(
        id="act-456",
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


def _make_l2_snapshot() -> L2Snapshot:
    return L2Snapshot(
        ocr_text="0",
        walker_nodes=10,
        walker_truncated=False,
        captured_at=time.monotonic(),
    )


class _MockL0:
    def __init__(
        self, signals: Optional[dict[str, float]] = None, *, sleep_s: float = 0.0
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
    def __init__(
        self, signals: Optional[dict[str, float]] = None, *, sleep_s: float = 0.0
    ) -> None:
        self._signals = signals or {}
        self._sleep_s = sleep_s

    async def run(self, target: UIElement, before: L1Snapshot) -> dict[str, float]:
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return dict(self._signals)


class _MockL2:
    """Stand-in for L2Medium. Records call count + returns scripted signals."""

    def __init__(
        self,
        signals: Optional[dict[str, float]] = None,
        *,
        sleep_s: float = 0.0,
    ) -> None:
        self._signals = signals or {}
        self._sleep_s = sleep_s
        self.run_call_count: int = 0

    async def run(
        self,
        target: UIElement,
        ax_element: Any,
        before: L2Snapshot,
        expected_text: Optional[str] = None,
    ) -> dict[str, float]:
        self.run_call_count += 1
        if self._sleep_s:
            await asyncio.sleep(self._sleep_s)
        return dict(self._signals)


class _SpyVote:
    """Returns a fixed confidence regardless of inputs."""

    def __init__(self, return_value: float = 0.0) -> None:
        self._return_value = return_value
        self.calls: list[tuple[str, dict[str, float]]] = []

    def aggregate(self, action_class: str, signals: Mapping[str, float]) -> float:
        self.calls.append((action_class, dict(signals)))
        return self._return_value


# ----------------------------------------------------------------- Test 1


@pytest.mark.asyncio
async def test_no_escalation_when_l0_l1_strong() -> None:
    """Confidence 0.7 from L0+L1 → no L2/L3 calls.

    HoarePost.tier_signals['L2'] is None (didn't run), 'L3' is None.
    """
    target = _make_target()
    action = _make_action("click")
    spy_vote = _SpyVote(return_value=0.7)
    l2 = _MockL2(signals={"l2.ocr_text_changed": 1.0})
    l3 = AsyncMock()
    agg = Aggregator(
        l0=_MockL0({}),  # type: ignore[arg-type]
        l1=_MockL1({}),  # type: ignore[arg-type]
        l2=l2,  # type: ignore[arg-type]
        l3=l3,
        vote=spy_vote,  # type: ignore[arg-type]
    )

    result = await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
        before_l2=_make_l2_snapshot(),
        ax_element=object(),
    )

    assert result.verified is True
    assert result.confidence == pytest.approx(0.7)
    assert l2.run_call_count == 0, "L2 should NOT run when L0+L1 confidence >= 0.50"
    l3.verify.assert_not_called()
    assert result.tier_signals["L2"] is None
    assert result.tier_signals["L3"] is None


# ----------------------------------------------------------------- Test 2


@pytest.mark.asyncio
async def test_escalate_to_l2_when_in_band() -> None:
    """Confidence 0.40 (in-band 0.30..0.50) → L2 runs; L3 NOT called.

    After L2 boost, confidence may exceed 0.50 → verified. tier_signals['L2']
    is a float (the L2 boost value). tier_signals['L3'] stays None.
    """
    target = _make_target()
    action = _make_action("click")
    spy_vote = _SpyVote(return_value=0.40)
    l2 = _MockL2(signals={"l2.ocr_text_changed": 1.0, "l2.expected_text_present": 1.0})
    l3 = AsyncMock()
    agg = Aggregator(
        l0=_MockL0({}),  # type: ignore[arg-type]
        l1=_MockL1({}),  # type: ignore[arg-type]
        l2=l2,  # type: ignore[arg-type]
        l3=l3,
        vote=spy_vote,  # type: ignore[arg-type]
    )

    result = await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
        before_l2=_make_l2_snapshot(),
        ax_element=object(),
    )

    assert l2.run_call_count == 1, "L2 must run when confidence is in-band"
    l3.verify.assert_not_called()
    assert result.tier_signals["L2"] is not None
    assert isinstance(result.tier_signals["L2"], float)
    assert result.tier_signals["L3"] is None


# ----------------------------------------------------------------- Test 3


@pytest.mark.asyncio
async def test_escalate_to_l3_when_below_threshold() -> None:
    """Confidence 0.20 → L2 runs first; if still <0.30, L3 is invoked.

    Phase 1 L3Stub.verify raises NotImplementedError; aggregator catches
    and emits 'l3.unavailable_phase1' structured event; final HoarePost
    has verified=False, confidence stays low (no L2 boost large enough).
    """
    target = _make_target()
    action = _make_action("click")
    # L0+L1 yields 0.20, L2 returns no boosting signals (all zeros)
    spy_vote = _SpyVote(return_value=0.20)
    l2 = _MockL2(signals={"l2.walker_truncated": 0.0, "l2.ocr_text_changed": 0.0})
    l3 = L3Stub()
    agg = Aggregator(
        l0=_MockL0({}),  # type: ignore[arg-type]
        l1=_MockL1({}),  # type: ignore[arg-type]
        l2=l2,  # type: ignore[arg-type]
        l3=l3,
        vote=spy_vote,  # type: ignore[arg-type]
    )

    # Use structlog.testing.capture_logs context manager — non-destructive
    # capture that doesn't replace the global processor pipeline. This is
    # the supported way to assert structured events fired.
    from structlog.testing import capture_logs

    with capture_logs() as captured:
        result = await agg.verify(
            action=action,
            target=target,
            notifs=["AXValueChanged"],
            before_l1=_make_l1_snapshot(),
            before_l2=_make_l2_snapshot(),
            ax_element=object(),
        )

    assert l2.run_call_count == 1, "L2 must run as first escalation step"
    assert result.verified is False
    assert result.confidence < VERIFIED_THRESHOLD

    # The unavailable_phase1 structured event was emitted.
    assert any(
        evt.get("event") == "l3.unavailable_phase1" for evt in captured
    ), f"expected 'l3.unavailable_phase1' event; captured={captured}"


# ----------------------------------------------------------------- Test 4


@pytest.mark.asyncio
async def test_l2_signals_propagated_to_hoare_post() -> None:
    """L2 signals reach HoarePost.tier_signals['L2'] (float)."""
    target = _make_target()
    action = _make_action("click")
    spy_vote = _SpyVote(return_value=0.40)  # in-band → L2 fires
    l2 = _MockL2(signals={"l2.ocr_text_changed": 1.0, "l2.walker_truncated": 1.0})
    l3 = AsyncMock()
    agg = Aggregator(
        l0=_MockL0({}),  # type: ignore[arg-type]
        l1=_MockL1({}),  # type: ignore[arg-type]
        l2=l2,  # type: ignore[arg-type]
        l3=l3,
        vote=spy_vote,  # type: ignore[arg-type]
    )

    result = await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
        before_l2=_make_l2_snapshot(),
        ax_element=object(),
    )

    # L2 emitted both signals; tier_signals['L2'] is a float (max or boost).
    assert isinstance(result.tier_signals["L2"], float)
    assert result.tier_signals["L2"] > 0.0


# ----------------------------------------------------------------- Test 5


@pytest.mark.asyncio
async def test_total_latency_under_500ms_with_l2() -> None:
    """L0 30ms + L1 30ms parallel (~30ms), then L2 200ms = ~230ms total.

    Sequential L0+L1 alone would be 60ms; with L2 in series ~260ms.
    Asserting <300ms gives slack for scheduler jitter on macOS.
    """
    target = _make_target()
    action = _make_action("click")
    spy_vote = _SpyVote(return_value=0.40)  # in-band → L2 fires
    l0 = _MockL0({}, sleep_s=0.030)
    l1 = _MockL1({}, sleep_s=0.030)
    l2 = _MockL2(signals={"l2.ocr_text_changed": 1.0}, sleep_s=0.200)
    l3 = AsyncMock()
    agg = Aggregator(
        l0=l0,  # type: ignore[arg-type]
        l1=l1,  # type: ignore[arg-type]
        l2=l2,  # type: ignore[arg-type]
        l3=l3,
        vote=spy_vote,  # type: ignore[arg-type]
    )

    t0 = time.monotonic()
    await agg.verify(
        action=action,
        target=target,
        notifs=["AXValueChanged"],
        before_l1=_make_l1_snapshot(),
        before_l2=_make_l2_snapshot(),
        ax_element=object(),
    )
    elapsed = time.monotonic() - t0

    assert elapsed < 0.300, (
        f"verify() with L2 escalation took {elapsed:.3f}s; expected <0.300s"
    )
    assert elapsed >= 0.230, (
        f"verify() too fast ({elapsed:.3f}s) — L2 should have actually run "
        "(parallel L0+L1 ~30ms + L2 200ms = ~230ms minimum)"
    )
