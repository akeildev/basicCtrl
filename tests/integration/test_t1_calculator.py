"""TRANS-01 / ACT-04 integration test — T1 + C2 fires Calculator '5' button.

Reuses Phase 1's calculator_pid fixture (tests/conftest.py).

Per CONTEXT.md D-14: T1 default channel binding is C2 (kAXPress). This test
verifies the end-to-end flow: T1 resolves Calculator's '5' button via the
depth-3 AX walk, then C2 fires AXUIElementPerformAction with try_claim and
cancel_event guards.

Skipped under SKIP_INTEGRATION=1 or when Calculator/AppKit unavailable.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import anyio
import pytest

from cua_overlay.actions.channels.c2_ax_press import C2AXPressChannel
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.persist.session_writer import SessionWriter
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TargetSpec
from cua_overlay.translators.t1_ax import T1AXTranslator


pytestmark = pytest.mark.integration


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyTokenStore:
    """Per-test IdempotencyTokenStore wired to a tmp SessionWriter."""
    sw = SessionWriter(base=tmp_path)
    return IdempotencyTokenStore(sw)


def _build_action(target_key: str, session_id: str) -> ActionCanonical:
    return ActionCanonical(
        id=uuid.uuid4().hex,
        step_idx=1,
        kind="MUTATE",
        target_key=target_key,
        action_type="click",
        payload={},
        timestamp_ns=time.monotonic_ns(),
        session_id=session_id,
    )


async def test_t1_resolves_calc_5_button(calculator_pid: int) -> None:
    """T1 resolves Calculator's '5' button via depth-3 AX walk.

    Verifies TRANS-01: T1AXTranslator returns a TranslatorTarget with both
    a UIElement (label='5') and an opaque AXUIElementRef (non-None).
    """
    t1 = T1AXTranslator()
    target = await t1.resolve(
        "com.apple.calculator",
        calculator_pid,
        TargetSpec(label="5"),
    )
    assert target is not None, "T1 must resolve Calculator '5' button"
    assert target.element.label.strip() == "5"
    assert target.ax_element is not None


async def test_c2_fires_calc_5_button(
    calculator_pid: int, store: IdempotencyTokenStore
) -> None:
    """C2 fires AXUIElementPerformAction on the resolved target.

    Verifies ACT-04: C2AXPressChannel.fire returns
    ChannelOutcome(channel='C2', status='fired', fired_at_ns=...).
    """
    t1 = T1AXTranslator()
    target = await t1.resolve(
        "com.apple.calculator",
        calculator_pid,
        TargetSpec(label="5"),
    )
    assert target is not None, "T1 prerequisite — '5' button must resolve"

    action = _build_action(target.element.composite_key, "test-sess")
    cancel_event = anyio.Event()
    channel = C2AXPressChannel()

    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.channel == "C2"
    assert outcome.status == "fired", (
        f"unexpected status {outcome.status}: error={outcome.error}"
    )
    assert outcome.fired_at_ns is not None


async def test_c2_idempotency_second_fire_skipped(
    calculator_pid: int, store: IdempotencyTokenStore
) -> None:
    """ACT-03: second fire on same action_id returns skipped/idempotency_lost."""
    t1 = T1AXTranslator()
    target = await t1.resolve(
        "com.apple.calculator", calculator_pid, TargetSpec(label="5")
    )
    assert target is not None
    action = _build_action(target.element.composite_key, "test-sess")
    cancel_event = anyio.Event()
    channel = C2AXPressChannel()

    first = await channel.fire(action, target, store, cancel_event)
    assert first.status == "fired"

    second = await channel.fire(action, target, store, cancel_event)
    assert second.status == "skipped"
    assert second.skipped_reason == "idempotency_lost"


async def test_c2_pre_syscall_cancel_event(
    calculator_pid: int, store: IdempotencyTokenStore
) -> None:
    """D-18 OS-level kill-switch: cancel_event.is_set() before syscall → cancelled.

    Note the order: claim is held (try_claim happens BEFORE cancel check per
    the contract), but the AXUIElementPerformAction syscall does NOT run.
    """
    t1 = T1AXTranslator()
    target = await t1.resolve(
        "com.apple.calculator", calculator_pid, TargetSpec(label="5")
    )
    assert target is not None
    action = _build_action(target.element.composite_key, "test-sess")
    cancel_event = anyio.Event()
    cancel_event.set()  # cancel BEFORE fire
    channel = C2AXPressChannel()

    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "cancelled"
    assert outcome.fired_at_ns is None
