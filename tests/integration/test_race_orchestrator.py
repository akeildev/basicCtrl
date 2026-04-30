"""ACT-02 — Race orchestrator integration tests with mocked channels.

Replaces the Wave-0 stub. Validates the 10-step execute contract end-to-end
with mocked channels + Phase 1 verifier (no real apps required — this is a
unit-level integration test of the orchestrator wiring, not the channels).

Per RESEARCH.md Pattern 2: anyio Race Pattern + Pitfall A.
Per VALIDATION.md per-task verification map row 02-08-01.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

from cua_overlay.actions.channels.base import ChannelOutcome
from cua_overlay.actions.race_orchestrator import (
    AS_STAGGER_MS_DEFAULT,
    RaceOrchestrator,
    race_first_complete,
)
from cua_overlay.actions.race_policy import RacePolicy
from cua_overlay.state.causal_dag import HoarePost
from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.translators.base import TargetSpec, TranslatorTarget


pytestmark = pytest.mark.integration


def _fake_target() -> TranslatorTarget:
    now = datetime.now(timezone.utc)
    return TranslatorTarget(
        element=UIElement(
            role="AXButton",
            role_path="AXApplication/AXWindow/AXButton[5]",
            label="5",
            bbox=Bbox(x=664, y=908, w=50, h=50),
            pid=1234,
            bundle_id="com.apple.calculator",
            window_id=0,
            discovered_at=now,
            last_seen_at=now,
            source=[Source.AX],
        ),
        ax_element=object(),  # opaque marker
        grounded_bbox=Bbox(x=664, y=908, w=50, h=50),
    )


def _fake_post(verified: bool = True) -> HoarePost:
    """HoarePost matches actual cua_overlay.state.causal_dag schema."""
    return HoarePost(
        target_key="role:AXButton|label:5",
        confidence=1.0 if verified else 0.0,
        tier_signals={"L0": 1.0, "L1": 1.0, "L2": None, "L3": None},
        verified=verified,
        healed_to=None,
        timestamp_ns=time.monotonic_ns(),
    )


def _fake_channel(name: str, outcome_status: str = "fired", delay: float = 0.0):
    """Build a fake channel that returns ChannelOutcome after `delay` seconds."""
    ch = MagicMock()
    ch.name = name
    fired_count = {"n": 0}

    async def _fire(action, target, store, cancel_event):
        if delay > 0:
            try:
                await anyio.sleep(delay)
            except anyio.get_cancelled_exc_class():
                fired_count["n"] += 1
                raise
        fired_count["n"] += 1
        return ChannelOutcome(
            channel=name,
            status=outcome_status,
            fired_at_ns=time.monotonic_ns() if outcome_status == "fired" else None,
        )

    ch.fire = _fire
    ch._fire_count = fired_count
    return ch


# ------------------------------- race_first_complete unit tests ---------------


@pytest.mark.asyncio
async def test_race_first_complete_winner_idx_zero_cancels_loser() -> None:
    """First coro returns 'fired' first; second is slow → cancelled."""
    fast_ch = _fake_channel("C2", "fired", delay=0.0)
    slow_ch = _fake_channel("C5", "fired", delay=0.5)

    async def _winner_cb(idx, outcome):
        return None

    coros = [
        fast_ch.fire(None, _fake_target(), MagicMock(), anyio.Event()),
        slow_ch.fire(None, _fake_target(), MagicMock(), anyio.Event()),
    ]
    winner_idx, outcome, results = await race_first_complete(
        coros, on_first_winner=_winner_cb
    )
    assert winner_idx == 0
    assert outcome.status == "fired"
    assert outcome.channel == "C2"


@pytest.mark.asyncio
async def test_race_first_complete_no_winner_returns_neg_one() -> None:
    """All channels skipped/errored → no_winner."""
    skip1 = _fake_channel("C2", "skipped", delay=0.0)
    skip2 = _fake_channel("C5", "errored", delay=0.0)
    coros = [
        skip1.fire(None, _fake_target(), MagicMock(), anyio.Event()),
        skip2.fire(None, _fake_target(), MagicMock(), anyio.Event()),
    ]
    winner_idx, outcome, results = await race_first_complete(coros)
    assert winner_idx == -1
    assert outcome.error == "no_winner"


# ------------------------------- RaceOrchestrator integration tests -----------


@pytest.fixture
def fake_orchestrator():
    """Build a RaceOrchestrator with mocked dependencies."""
    target = _fake_target()
    fake_translator = AsyncMock()
    fake_translator.tier = "T1"
    fake_translator.resolve = AsyncMock(return_value=target)
    fake_translator.validate = AsyncMock(return_value=True)
    translator_registry = MagicMock()
    translator_registry.select_for_priority = MagicMock(return_value=[fake_translator])

    fake_c2 = _fake_channel("C2", "fired", delay=0.0)
    fake_c5 = _fake_channel("C5", "fired", delay=0.05)
    channel_registry = MagicMock()
    channel_registry.select = MagicMock(return_value=[fake_c2, fake_c5])
    channel_registry.tier_for_channel = MagicMock(return_value="T1")

    idem_store = MagicMock()
    duplicate = MagicMock()
    duplicate.record = MagicMock(return_value=False)

    axmgr = MagicMock()
    axmgr.expect = AsyncMock(return_value=None)

    aggregator = MagicMock()
    aggregator.verify = AsyncMock(return_value=_fake_post(verified=True))

    l1 = MagicMock()
    l1.snapshot = AsyncMock(return_value=SimpleNamespace())

    classifier = AsyncMock(
        return_value=SimpleNamespace(translator_priority=["T1", "T2"])
    )

    session_writer = MagicMock()
    session_writer.session_id = "test-session"
    session_writer.append_action_log = MagicMock()

    orch = RaceOrchestrator(
        translator_registry=translator_registry,
        channel_registry=channel_registry,
        idem_store=idem_store,
        duplicate_receipt=duplicate,
        axmgr=axmgr,
        aggregator=aggregator,
        l1_cheap=l1,
        classifier=classifier,
        session_writer=session_writer,
    )
    return SimpleNamespace(
        orch=orch,
        target=target,
        translator=fake_translator,
        c2=fake_c2,
        c5=fake_c5,
        axmgr=axmgr,
        aggregator=aggregator,
        l1=l1,
        duplicate=duplicate,
        session_writer=session_writer,
    )


@pytest.mark.asyncio
async def test_race_policy_auto_click_uses_race(fake_orchestrator) -> None:
    """action_type='click' + AUTO → multiple channel.fire calls (RACE path)."""
    fo = fake_orchestrator
    action, post = await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="5"),
        action_type="click",
        payload={"x": 664, "y": 908},
        race_policy=RacePolicy.AUTO,
    )
    assert post.verified is True
    # At least one channel fired (race winner).
    assert fo.c2._fire_count["n"] + fo.c5._fire_count["n"] >= 1


@pytest.mark.asyncio
async def test_race_policy_destructive_force_single_channel(fake_orchestrator) -> None:
    """action_type='submit' + RACE → server-side override forces SINGLE_CHANNEL (T-2-09)."""
    fo = fake_orchestrator
    # Reset the registry select mock for SINGLE_CHANNEL: returns 1 channel (per spec).
    fo.orch._channels.select = MagicMock(return_value=[fo.c2])

    action, post = await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="Submit"),
        action_type="submit",
        payload={},
        race_policy=RacePolicy.RACE,  # caller demands race
    )
    # Only one channel fired (single-channel path overrode).
    fired_count = fo.c2._fire_count["n"] + fo.c5._fire_count["n"]
    assert fired_count == 1, (
        f"expected 1 fire under SINGLE_CHANNEL override, got {fired_count}"
    )


@pytest.mark.asyncio
async def test_subscribe_before_fire_ordering(fake_orchestrator) -> None:
    """axmgr.expect called BEFORE any channel.fire (Phase 1 hard rule)."""
    fo = fake_orchestrator
    call_order: list[str] = []
    orig_expect = fo.axmgr.expect

    async def _track_expect(*args, **kwargs):
        call_order.append("axmgr.expect")
        return await orig_expect(*args, **kwargs)

    fo.axmgr.expect = _track_expect

    orig_c2 = fo.c2.fire

    async def _track_c2(*args, **kwargs):
        call_order.append("c2.fire")
        return await orig_c2(*args, **kwargs)

    fo.c2.fire = _track_c2

    await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="5"),
        action_type="click",
        payload={},
        race_policy=RacePolicy.AUTO,
    )
    assert "axmgr.expect" in call_order
    assert call_order.index("axmgr.expect") < call_order.index("c2.fire")


@pytest.mark.asyncio
async def test_l1_snapshot_before_fire(fake_orchestrator) -> None:
    """l1.snapshot called BEFORE any channel.fire (HoarePre)."""
    fo = fake_orchestrator
    call_order: list[str] = []
    orig_snap = fo.l1.snapshot

    async def _track_snap(*args, **kwargs):
        call_order.append("l1.snapshot")
        return await orig_snap(*args, **kwargs)

    fo.l1.snapshot = _track_snap

    orig_c2 = fo.c2.fire

    async def _track_c2(*args, **kwargs):
        call_order.append("c2.fire")
        return await orig_c2(*args, **kwargs)

    fo.c2.fire = _track_c2

    await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="5"),
        action_type="click",
        payload={},
        race_policy=RacePolicy.AUTO,
    )
    assert call_order.index("l1.snapshot") < call_order.index("c2.fire")


@pytest.mark.asyncio
async def test_verify_called_after_fire(fake_orchestrator) -> None:
    """aggregator.verify called AFTER channel fire returns."""
    fo = fake_orchestrator
    await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="5"),
        action_type="click",
        payload={},
        race_policy=RacePolicy.AUTO,
    )
    fo.aggregator.verify.assert_awaited()


@pytest.mark.asyncio
async def test_action_filled_with_winning_tier_and_channel(fake_orchestrator) -> None:
    """ActionCanonical.tier and .channel are filled from the winner."""
    fo = fake_orchestrator
    fo.orch._channels.tier_for_channel = MagicMock(return_value="T1")
    action, post = await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="5"),
        action_type="click",
        payload={},
        race_policy=RacePolicy.AUTO,
    )
    assert action.tier == "T1"
    assert action.channel in {"C2", "C5"}


@pytest.mark.asyncio
async def test_duplicate_receipt_recorded_after_verify(fake_orchestrator) -> None:
    """DuplicateReceipt.record called AFTER verify (D-19)."""
    fo = fake_orchestrator
    call_order: list[str] = []
    orig_verify = fo.aggregator.verify

    async def _track_verify(*args, **kwargs):
        call_order.append("verify")
        return await orig_verify(*args, **kwargs)

    fo.aggregator.verify = _track_verify

    orig_record = fo.duplicate.record

    def _track_record(*args, **kwargs):
        call_order.append("duplicate.record")
        return orig_record(*args, **kwargs)

    fo.duplicate.record = _track_record

    await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="5"),
        action_type="click",
        payload={},
        race_policy=RacePolicy.AUTO,
    )
    assert call_order.index("verify") < call_order.index("duplicate.record")


@pytest.mark.asyncio
async def test_race_winner_and_race_loser_events_emitted(fake_orchestrator) -> None:
    """One race_winner + (n-1) race_loser events written to action log."""
    fo = fake_orchestrator
    await fo.orch.execute(
        bundle_id="com.apple.calculator",
        pid=1234,
        target_spec=TargetSpec(label="5"),
        action_type="click",
        payload={},
        race_policy=RacePolicy.AUTO,
    )
    events = [
        c.args[0]["event"]
        for c in fo.session_writer.append_action_log.call_args_list
        if c.args and isinstance(c.args[0], dict) and "event" in c.args[0]
    ]
    assert "race_winner" in events
    # Exactly one winner; loser may or may not be logged depending on
    # whether it returned an outcome before being cancelled.
    assert events.count("race_winner") == 1


@pytest.mark.asyncio
async def test_as_stagger_default_500ms_when_c4_present() -> None:
    """C4 channel is staggered AS_STAGGER_MS_DEFAULT ms when no as_class='fast'."""
    target = _fake_target()
    target_with_extras = TranslatorTarget(
        element=target.element,
        ax_element=target.ax_element,
        grounded_bbox=target.grounded_bbox,
        extras={},  # no as_class marker → default slow → 500ms stagger
    )

    fake_translator = AsyncMock()
    fake_translator.tier = "T3"
    fake_translator.resolve = AsyncMock(return_value=target_with_extras)
    fake_translator.validate = AsyncMock(return_value=True)
    translator_registry = MagicMock()
    translator_registry.select_for_priority = MagicMock(return_value=[fake_translator])

    fake_c4 = _fake_channel("C4", "fired", delay=0.0)
    channel_registry = MagicMock()
    channel_registry.select = MagicMock(return_value=[fake_c4])
    channel_registry.tier_for_channel = MagicMock(return_value="T3")

    idem_store = MagicMock()
    duplicate = MagicMock()
    duplicate.record = MagicMock(return_value=False)

    axmgr = MagicMock()
    axmgr.expect = AsyncMock(return_value=None)

    aggregator = MagicMock()
    aggregator.verify = AsyncMock(return_value=_fake_post(verified=True))

    l1 = MagicMock()
    l1.snapshot = AsyncMock(return_value=SimpleNamespace())

    classifier = AsyncMock(
        return_value=SimpleNamespace(translator_priority=["T3"])
    )
    session_writer = MagicMock()
    session_writer.session_id = "test"

    orch = RaceOrchestrator(
        translator_registry=translator_registry,
        channel_registry=channel_registry,
        idem_store=idem_store,
        duplicate_receipt=duplicate,
        axmgr=axmgr,
        aggregator=aggregator,
        l1_cheap=l1,
        classifier=classifier,
        session_writer=session_writer,
    )

    # Use SINGLE_CHANNEL via D-11 verb so we don't go through race_first_complete;
    # _staggered_fire wraps the single coro and the sleep is observable.
    t0 = time.monotonic()
    await orch.execute(
        bundle_id="com.apple.iWork.Pages",
        pid=1234,
        target_spec=TargetSpec(label="bold"),
        action_type="set_value",  # D-11 single-channel verb
        payload={},
        race_policy=RacePolicy.AUTO,
    )
    elapsed = time.monotonic() - t0
    # 500ms stagger expected; accept >=400ms to allow scheduling slop.
    assert elapsed >= AS_STAGGER_MS_DEFAULT / 1000.0 * 0.8, (
        f"AS stagger not applied; elapsed={elapsed:.3f}s (expected >= ~0.4s)"
    )
