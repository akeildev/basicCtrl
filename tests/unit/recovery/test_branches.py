"""Comprehensive unit tests for recovery branches B1-B5.

Per CONTEXT.md D-03: Each branch implements RecoveryBranch Protocol.
Tests cover success/failure paths, event emission, idempotency claiming,
and verifier integration.

Branches tested:
  - B1_Rescroll: scroll target into view, retry via T1/C2 (D-04)
  - B2_OCRRegrounding: re-run T4 uitag, fire C3 CGEvent (D-05)
  - B3_WorldReplan: stub emitting phase_3_stub event (D-06)
  - B4_PlannerRequery: stub emitting phase_3_stub event (D-07)
  - B5_AppleScriptFallback: fire T3/C4 with 500ms stagger (D-08)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from datetime import datetime, timezone

from cua_overlay.actions.channels.base import ChannelOutcome
from cua_overlay.recovery.branches import (
    B1_Rescroll,
    B2_OCRRegrounding,
    B3_WorldReplan,
    B4_PlannerRequery,
    B5_AppleScriptFallback,
    RecoveryBranch,
)
from cua_overlay.recovery.classifier import FailureCtx
from cua_overlay.state.graph import Bbox, UIElement


def _ui_element(label: str = "button") -> UIElement:
    """Construct a minimal valid UIElement for tests that fire channels."""
    now = datetime.now(timezone.utc)
    return UIElement(
        role="AXButton",
        role_path="AXApplication/AXWindow/AXButton",
        label=label,
        bbox=Bbox(x=0, y=0, w=10, h=10),
        discovered_at=now,
        last_seen_at=now,
        pid=1234,
        bundle_id="com.test.app",
        window_id=1,
    )


# ===== B1_RESCROLL TESTS =====


@pytest.mark.asyncio
async def test_b1_name() -> None:
    """B1 has correct name."""
    b1 = B1_Rescroll(None, None, None, None, None, None)
    assert b1.name == "B1_RESCROLL"


@pytest.mark.asyncio
async def test_b1_scrolls_target_into_view(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B1 scrolls target into view, retries via T1/C2, returns ChannelOutcome."""
    # Setup
    b1 = B1_Rescroll(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        walk_subtree_fn=AsyncMock(return_value=[_ui_element("button")]),
        aggregator=None,
    )

    # Mock registry returns
    t1_mock = MagicMock()
    c2_mock = MagicMock()
    c2_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C2", status="fired")
    )
    translator_registry_mock.get.side_effect = lambda tier: t1_mock if tier == "T1" else None
    channel_registry_mock.get.side_effect = lambda ch: c2_mock if ch == "C2" else None
    idempotency_store_mock.try_claim.return_value = MagicMock(claimed_by_channel="C2")

    # Prepare failure context
    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    # Attempt
    outcome = await b1.attempt(ctx)

    # Assert
    assert outcome is not None
    assert outcome.status == "fired"
    assert outcome.channel == "C2"


@pytest.mark.asyncio
async def test_b1_target_not_found(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
) -> None:
    """B1 returns None when walk_subtree finds no element."""
    b1 = B1_Rescroll(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        walk_subtree_fn=AsyncMock(return_value=[]),  # Empty subtree
        aggregator=None,
    )

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
    }

    outcome = await b1.attempt(ctx)

    assert outcome is None
    session_writer_mock.append_action_log.assert_called()


@pytest.mark.asyncio
async def test_b1_claim_already_owned(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
) -> None:
    """B1 returns None if idempotency claim already owned."""
    b1 = B1_Rescroll(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        walk_subtree_fn=AsyncMock(return_value=[MagicMock(label="button")]),
        aggregator=None,
    )

    # Mock: claim is lost
    idempotency_store_mock.try_claim.return_value = None

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
    }

    outcome = await b1.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b1_t1_unavailable(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
) -> None:
    """B1 returns None if T1 translator not in registry."""
    b1 = B1_Rescroll(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        walk_subtree_fn=AsyncMock(return_value=[MagicMock(label="button")]),
        aggregator=None,
    )

    # Mock: T1 not available
    translator_registry_mock.get.return_value = None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C2")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
    }

    outcome = await b1.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b1_channel_fire_fails(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B1 returns None if C2.fire fails."""
    b1 = B1_Rescroll(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        walk_subtree_fn=AsyncMock(return_value=[MagicMock(label="button")]),
        aggregator=None,
    )

    # Mock: channel fires but with error
    t1_mock = AsyncMock()
    c2_mock = AsyncMock()
    c2_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C2", status="errored", error="AX error")
    )
    translator_registry_mock.get.side_effect = lambda tier: t1_mock if tier == "T1" else None
    channel_registry_mock.get.side_effect = lambda ch: c2_mock if ch == "C2" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C2")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    outcome = await b1.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b1_emits_events(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B1 emits attempt/success/failure events."""
    b1 = B1_Rescroll(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        walk_subtree_fn=AsyncMock(return_value=[MagicMock(label="button")]),
        aggregator=None,
    )

    # Mock success path
    t1_mock = AsyncMock()
    c2_mock = AsyncMock()
    c2_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C2", status="fired")
    )
    translator_registry_mock.get.side_effect = lambda tier: t1_mock if tier == "T1" else None
    channel_registry_mock.get.side_effect = lambda ch: c2_mock if ch == "C2" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C2")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    await b1.attempt(ctx)

    # Assert events were emitted
    calls = session_writer_mock.append_action_log.call_args_list
    assert len(calls) >= 1
    first_event = calls[0][0][0]
    assert first_event["event"] == "branch_attempt"
    assert first_event["branch"] == "B1_RESCROLL"


# ===== B2_OCR_REGROUND TESTS =====


@pytest.mark.asyncio
async def test_b2_name() -> None:
    """B2 has correct name."""
    b2 = B2_OCRRegrounding(None, None, None, None, None)
    assert b2.name == "B2_OCR_REGROUND"


@pytest.mark.asyncio
async def test_b2_uitag_relocates_target(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B2 re-grounds target via T4, fires C3, returns ChannelOutcome."""
    b2 = B2_OCRRegrounding(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
    )

    # Mock T4 regrounding
    t4_mock = AsyncMock()
    regrounded_target = MagicMock()
    regrounded_target.grounded_bbox = MagicMock(model_dump=MagicMock(return_value={}))
    t4_mock.resolve = AsyncMock(return_value=regrounded_target)

    # Mock C3 channel
    c3_mock = AsyncMock()
    c3_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C3", status="fired")
    )

    translator_registry_mock.get.side_effect = lambda tier: t4_mock if tier == "T4" else None
    channel_registry_mock.get.side_effect = lambda ch: c3_mock if ch == "C3" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C3")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    outcome = await b2.attempt(ctx)

    assert outcome is not None
    assert outcome.status == "fired"
    assert outcome.channel == "C3"


@pytest.mark.asyncio
async def test_b2_uitag_fails(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
) -> None:
    """B2 returns None if T4 regrounding fails."""
    b2 = B2_OCRRegrounding(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
    )

    # Mock T4 failure
    t4_mock = AsyncMock()
    t4_mock.resolve = AsyncMock(return_value=None)

    translator_registry_mock.get.return_value = t4_mock
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C3")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
    }

    outcome = await b2.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b2_claim_already_owned(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
) -> None:
    """B2 returns None if claim already owned."""
    b2 = B2_OCRRegrounding(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
    )

    # Mock: T4 succeeds but claim is lost
    t4_mock = AsyncMock()
    regrounded_target = MagicMock()
    regrounded_target.grounded_bbox = MagicMock(model_dump=MagicMock(return_value={}))
    t4_mock.resolve = AsyncMock(return_value=regrounded_target)

    translator_registry_mock.get.return_value = t4_mock
    idempotency_store_mock.try_claim.return_value = None

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
    }

    outcome = await b2.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b2_channel_fire_fails(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B2 returns None if C3.fire fails."""
    b2 = B2_OCRRegrounding(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
    )

    # Mock: T4 succeeds, C3 fails
    t4_mock = AsyncMock()
    regrounded_target = MagicMock()
    regrounded_target.grounded_bbox = MagicMock(model_dump=MagicMock(return_value={}))
    t4_mock.resolve = AsyncMock(return_value=regrounded_target)

    c3_mock = AsyncMock()
    c3_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C3", status="errored", error="CGEvent failed")
    )

    translator_registry_mock.get.side_effect = lambda tier: t4_mock if tier == "T4" else None
    channel_registry_mock.get.side_effect = lambda ch: c3_mock if ch == "C3" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C3")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    outcome = await b2.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b2_emits_events(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B2 emits attempt/success events."""
    b2 = B2_OCRRegrounding(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
    )

    # Mock success path
    t4_mock = AsyncMock()
    regrounded_target = MagicMock()
    regrounded_target.grounded_bbox = MagicMock(model_dump=MagicMock(return_value={}))
    t4_mock.resolve = AsyncMock(return_value=regrounded_target)

    c3_mock = AsyncMock()
    c3_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C3", status="fired")
    )

    translator_registry_mock.get.side_effect = lambda tier: t4_mock if tier == "T4" else None
    channel_registry_mock.get.side_effect = lambda ch: c3_mock if ch == "C3" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C3")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    await b2.attempt(ctx)

    # Assert events were emitted
    calls = session_writer_mock.append_action_log.call_args_list
    assert len(calls) >= 1


# ===== B3_WORLD_REPLAN STUB TESTS =====


@pytest.mark.asyncio
async def test_b3_name() -> None:
    """B3 has correct name."""
    b3 = B3_WorldReplan()
    assert b3.name == "B3_WORLD_REPLAN"


@pytest.mark.asyncio
async def test_b3_emits_phase_4_stub_event(session_writer_mock) -> None:
    """B3 emits branch_skipped event and returns None."""
    b3 = B3_WorldReplan(session_writer=session_writer_mock)

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
    }

    outcome = await b3.attempt(ctx)

    assert outcome is None
    # Check that event was emitted
    session_writer_mock.append_action_log.assert_called()
    event = session_writer_mock.append_action_log.call_args[0][0]
    assert event["event"] == "branch_skipped"
    assert event["branch"] == "B3_WORLD_REPLAN"
    assert "Phase 4" in event["reason"]


# ===== B4_PLANNER_REQUERY STUB TESTS =====


@pytest.mark.asyncio
async def test_b4_name() -> None:
    """B4 has correct name."""
    b4 = B4_PlannerRequery()
    assert b4.name == "B4_PLANNER_REQUERY"


@pytest.mark.asyncio
async def test_b4_emits_phase_4_stub_event(session_writer_mock) -> None:
    """B4 emits branch_skipped event and returns None."""
    b4 = B4_PlannerRequery(session_writer=session_writer_mock)

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
    }

    outcome = await b4.attempt(ctx)

    assert outcome is None
    # Check that event was emitted
    session_writer_mock.append_action_log.assert_called()
    event = session_writer_mock.append_action_log.call_args[0][0]
    assert event["event"] == "branch_skipped"
    assert event["branch"] == "B4_PLANNER_REQUERY"
    assert "Phase 4" in event["reason"]


# ===== B5_APPLESCRIPT TESTS =====


@pytest.mark.asyncio
async def test_b5_name() -> None:
    """B5 has correct name."""
    b5 = B5_AppleScriptFallback(None, None, None, None, None)
    assert b5.name == "B5_APPLESCRIPT_FALLBACK"


@pytest.mark.asyncio
async def test_b5_stagger_delay(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B5 sleeps for stagger_ms before firing."""
    import time

    b5 = B5_AppleScriptFallback(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
        as_stagger_ms=100,  # 100ms for fast test
    )

    # Mock: claim succeeds, T3 resolves, C4 fires
    t3_mock = AsyncMock()
    as_target = MagicMock()
    t3_mock.resolve = AsyncMock(return_value=as_target)

    c4_mock = AsyncMock()
    c4_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C4", status="fired")
    )

    translator_registry_mock.get.side_effect = lambda tier: t3_mock if tier == "T3" else None
    channel_registry_mock.get.side_effect = lambda ch: c4_mock if ch == "C4" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C4")
    idempotency_store_mock.is_claimed.return_value = AsyncMock(claimed_by_channel="C4")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    t_start = time.monotonic()
    outcome = await b5.attempt(ctx)
    t_elapsed = time.monotonic() - t_start

    # Should sleep at least 100ms
    assert t_elapsed >= 0.090  # Allow some margin
    assert outcome is not None
    assert outcome.status == "fired"
    assert outcome.channel == "C4"


@pytest.mark.asyncio
async def test_b5_claim_during_stagger(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
) -> None:
    """B5 returns None if claim expires during stagger."""
    b5 = B5_AppleScriptFallback(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
        as_stagger_ms=50,
    )

    # Mock: claim initially succeeds, then expires during stagger
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C4")
    idempotency_store_mock.is_claimed.return_value = None  # Lost during stagger

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
    }

    outcome = await b5.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b5_t3_unavailable(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
) -> None:
    """B5 returns None if T3 unavailable."""
    b5 = B5_AppleScriptFallback(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
        as_stagger_ms=10,
    )

    # Mock: claim succeeds, T3 not available
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C4")
    idempotency_store_mock.is_claimed.return_value = AsyncMock(claimed_by_channel="C4")
    translator_registry_mock.get.return_value = None

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
    }

    outcome = await b5.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b5_channel_fire_fails(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B5 returns None if C4.fire fails."""
    b5 = B5_AppleScriptFallback(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
        as_stagger_ms=10,
    )

    # Mock: claim succeeds, T3 resolves, C4 fails
    t3_mock = AsyncMock()
    as_target = MagicMock()
    t3_mock.resolve = AsyncMock(return_value=as_target)

    c4_mock = AsyncMock()
    c4_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C4", status="errored", error="AS failed")
    )

    translator_registry_mock.get.side_effect = lambda tier: t3_mock if tier == "T3" else None
    channel_registry_mock.get.side_effect = lambda ch: c4_mock if ch == "C4" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C4")
    idempotency_store_mock.is_claimed.return_value = AsyncMock(claimed_by_channel="C4")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    outcome = await b5.attempt(ctx)

    assert outcome is None


@pytest.mark.asyncio
async def test_b5_emits_events(
    translator_registry_mock,
    channel_registry_mock,
    idempotency_store_mock,
    session_writer_mock,
    channel_outcome_mock,
) -> None:
    """B5 emits attempt/success events."""
    b5 = B5_AppleScriptFallback(
        translator_registry=translator_registry_mock,
        channel_registry=channel_registry_mock,
        idempotency_store=idempotency_store_mock,
        session_writer=session_writer_mock,
        aggregator=None,
        as_stagger_ms=10,
    )

    # Mock success path
    t3_mock = AsyncMock()
    as_target = MagicMock()
    t3_mock.resolve = AsyncMock(return_value=as_target)

    c4_mock = AsyncMock()
    c4_mock.fire = AsyncMock(
        return_value=channel_outcome_mock(channel="C4", status="fired")
    )

    translator_registry_mock.get.side_effect = lambda tier: t3_mock if tier == "T3" else None
    channel_registry_mock.get.side_effect = lambda ch: c4_mock if ch == "C4" else None
    idempotency_store_mock.try_claim.return_value = AsyncMock(claimed_by_channel="C4")
    idempotency_store_mock.is_claimed.return_value = AsyncMock(claimed_by_channel="C4")

    ctx = {
        "bundle_id": "com.test.app",
        "target_key": "btn_test",
        "action_type": "click",
        "pid": 1234,
        "action_id": "action_123",
        "session_id": "sess_001",
    }

    await b5.attempt(ctx)

    # Assert events were emitted
    calls = session_writer_mock.append_action_log.call_args_list
    assert len(calls) >= 1


# ===== INTEGRATION TESTS =====


@pytest.mark.asyncio
async def test_all_branches_runnable() -> None:
    """All 5 branch objects instantiate and are importable."""
    # B1-B2-B5 need mocked deps
    from unittest.mock import AsyncMock

    b1 = B1_Rescroll(
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
        AsyncMock(),
    )
    assert b1.name == "B1_RESCROLL"
    assert isinstance(b1, RecoveryBranch)

    b2 = B2_OCRRegrounding(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    assert b2.name == "B2_OCR_REGROUND"
    assert isinstance(b2, RecoveryBranch)

    # B3-B4 are stubs
    b3 = B3_WorldReplan()
    assert b3.name == "B3_WORLD_REPLAN"
    assert isinstance(b3, RecoveryBranch)

    b4 = B4_PlannerRequery()
    assert b4.name == "B4_PLANNER_REQUERY"
    assert isinstance(b4, RecoveryBranch)

    # B5
    b5 = B5_AppleScriptFallback(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    assert b5.name == "B5_APPLESCRIPT_FALLBACK"
    assert isinstance(b5, RecoveryBranch)


@pytest.mark.asyncio
async def test_branches_re_export() -> None:
    """Branches are re-exported from recovery module."""
    from cua_overlay.recovery import (
        B1_Rescroll,
        B2_OCRRegrounding,
        B3_WorldReplan,
        B4_PlannerRequery,
        B5_AppleScriptFallback,
    )

    assert B1_Rescroll is not None
    assert B2_OCRRegrounding is not None
    assert B3_WorldReplan is not None
    assert B4_PlannerRequery is not None
    assert B5_AppleScriptFallback is not None
