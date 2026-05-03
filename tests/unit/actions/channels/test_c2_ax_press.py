"""ACT-04 — C2 AX kAXPress channel unit tests with mocked AX surface.

Covers the fire-path contract from CONTEXT.md D-17 / D-18:
    1. try_claim BEFORE syscall → if lost, status='skipped'
    2. cancel_event.is_set() BEFORE syscall → if cancelled, status='cancelled'
    3. AXUIElementPerformAction in asyncio.to_thread → status='fired'

These tests run on any host (no Calculator, no TCC); real Calculator
integration lives in tests/integration/test_t1_calculator.py.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anyio
import pytest

from basicctrl.actions.channels.c2_ax_press import C2AXPressChannel
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.persist.session_writer import SessionWriter
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.state.graph import Bbox, UIElement
from basicctrl.translators.base import TranslatorTarget


def _fake_uielement() -> UIElement:
    return UIElement(
        role="AXButton",
        role_path="AXApplication/AXButton[5]",
        label="5",
        bbox=Bbox(x=10, y=20, w=30, h=40),
        pid=1234,
        bundle_id="com.apple.calculator",
        window_id=0,
        discovered_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
    )


def _fake_action() -> ActionCanonical:
    return ActionCanonical(
        id=uuid.uuid4().hex,
        step_idx=1,
        kind="MUTATE",
        target_key="composite-key",
        action_type="click",
        payload={},
        timestamp_ns=time.monotonic_ns(),
        session_id="unit-sess",
    )


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyTokenStore:
    return IdempotencyTokenStore(SessionWriter(base=tmp_path))


def test_name_is_C2() -> None:
    """C2AXPressChannel declares name='C2' (Channel Protocol contract)."""
    c = C2AXPressChannel()
    assert c.name == "C2"


async def test_fire_returns_fired_on_success(store: IdempotencyTokenStore) -> None:
    """fire returns ChannelOutcome(channel='C2', status='fired', fired_at_ns set)."""
    target = TranslatorTarget(element=_fake_uielement(), ax_element=object())
    action = _fake_action()
    cancel_event = anyio.Event()

    fake_module = SimpleNamespace(AXUIElementPerformAction=lambda elem, action_name: 0)
    channel = C2AXPressChannel()
    with patch.dict("sys.modules", {"HIServices": fake_module}):
        outcome = await channel.fire(action, target, store, cancel_event)

    assert outcome.channel == "C2"
    assert outcome.status == "fired"
    assert outcome.fired_at_ns is not None


async def test_fire_skipped_on_idempotency_lost(
    store: IdempotencyTokenStore,
) -> None:
    """T-2-01 mitigation: second fire on same action_id returns skipped."""
    target = TranslatorTarget(element=_fake_uielement(), ax_element=object())
    action = _fake_action()
    cancel_event = anyio.Event()

    # Pre-claim the action_id under a different channel.
    pre_claim = await store.try_claim(action.id, "C1")
    assert pre_claim is not None

    channel = C2AXPressChannel()
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "skipped"
    assert outcome.skipped_reason == "idempotency_lost"


async def test_fire_cancelled_when_cancel_event_set(
    store: IdempotencyTokenStore,
) -> None:
    """D-18 kill-switch: cancel_event set BEFORE fire → status='cancelled'."""
    target = TranslatorTarget(element=_fake_uielement(), ax_element=object())
    action = _fake_action()
    cancel_event = anyio.Event()
    cancel_event.set()

    channel = C2AXPressChannel()
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "cancelled"
    assert outcome.fired_at_ns is None


async def test_fire_errored_on_no_ax_element(store: IdempotencyTokenStore) -> None:
    """Defensive: ax_element=None → status='errored', error='no_ax_element'."""
    target = TranslatorTarget(element=_fake_uielement(), ax_element=None)
    action = _fake_action()
    cancel_event = anyio.Event()

    channel = C2AXPressChannel()
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "errored"
    assert outcome.error == "no_ax_element"


async def test_fire_errored_on_ax_nonzero_err(store: IdempotencyTokenStore) -> None:
    """AXUIElementPerformAction returning non-zero err → status='errored'."""
    target = TranslatorTarget(element=_fake_uielement(), ax_element=object())
    action = _fake_action()
    cancel_event = anyio.Event()

    fake_module = SimpleNamespace(
        AXUIElementPerformAction=lambda elem, action_name: -25200
    )
    channel = C2AXPressChannel()
    with patch.dict("sys.modules", {"HIServices": fake_module}):
        outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "errored"
    assert outcome.error is not None
    assert "AXErr" in outcome.error
