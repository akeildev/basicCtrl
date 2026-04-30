"""ACT-01 / D-14 — C5 CDP Input.dispatchMouseEvent channel unit tests.

Wave-2 plan 02-06: C5CDPInputChannel implements Channel Protocol with
name='C5'; reuses ws_url from TranslatorTarget.extras (T2 puts it there);
calls Input.dispatchMouseEvent(mousePressed, mouseReleased) at the
content-quad center after atomic try_claim + cancel-event guard.

These tests use a fake CDPClient factory so no real CDP socket is needed.
Real Slack integration lives in tests/integration/test_slack_t2_wins.py.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest

from cua_overlay.actions.channels.c5_cdp_input import C5CDPInputChannel
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.persist.session_writer import SessionWriter
from cua_overlay.state.causal_dag import ActionCanonical, HoarePre
from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.translators.base import TranslatorTarget


# ─── helpers ────────────────────────────────────────────────────────────────


def _fake_action(action_id: str = "act-c5-1") -> ActionCanonical:
    """Build a minimal ActionCanonical for testing C5.fire."""
    return ActionCanonical(
        id=action_id,
        kind="MUTATE",
        action_type="click",
        pre=HoarePre(
            target_role="AXButton",
            target_label="message_container",
            target_role_path="CDPElement[42]",
            target_pid=1234,
            target_bundle_id="com.tinyspeck.slackmacgap",
        ),
    )


def _fake_target(
    *, ws_url: str = "ws://localhost:9222/devtools/browser/abc",
    session_id: str = "sess-1",
    node_id: int = 42,
    cx: float = 100.0, cy: float = 200.0,
) -> TranslatorTarget:
    """Build a TranslatorTarget shaped like T2CDPTranslator.resolve() output."""
    now = datetime.now(timezone.utc)
    elem = UIElement(
        role="AXUnknown",
        role_path=f"CDPElement[{node_id}]",
        label="message_container",
        bbox=Bbox(x=cx - 10, y=cy - 10, w=20, h=20),
        pid=1234,
        bundle_id="com.tinyspeck.slackmacgap",
        window_id=0,
        discovered_at=now,
        last_seen_at=now,
        source=[Source.CDP],
    )
    return TranslatorTarget(
        element=elem,
        cdp_node_id=node_id,
        cdp_session_id=session_id,
        grounded_bbox=Bbox(x=cx - 10, y=cy - 10, w=20, h=20),
        extras={"ws_url": ws_url},
    )


class _FakeCDPClient:
    """Fake CDPClient context manager. Records all dispatched mouse events."""

    last_instance: "_FakeCDPClient | None" = None

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.events: list[dict[str, Any]] = []
        _FakeCDPClient.last_instance = self
        # Build the cdp.send.<Domain>.<method> attribute tree.
        self.send = MagicMock()
        async def _dispatch(params: dict[str, Any] | None = None,
                            sessionId: str | None = None) -> dict[str, Any]:
            self.events.append({"params": params, "sessionId": sessionId})
            return {}
        self.send.Input.dispatchMouseEvent = _dispatch

    async def __aenter__(self) -> "_FakeCDPClient":
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False


@pytest.fixture
def fake_session_writer(tmp_path):
    """Real SessionWriter pointing at a tmp directory."""
    return SessionWriter(session_dir=tmp_path / "sess")


@pytest.fixture
def store(fake_session_writer):
    return IdempotencyTokenStore(session_writer=fake_session_writer)


# ─── tests ──────────────────────────────────────────────────────────────────


def test_name_is_C5() -> None:
    assert C5CDPInputChannel().name == "C5"


@pytest.mark.asyncio
async def test_fire_dispatches_press_and_release(store) -> None:
    """C5 must dispatch BOTH mousePressed AND mouseReleased to complete a click."""
    ch = C5CDPInputChannel(cdp_client_factory=_FakeCDPClient)
    target = _fake_target(cx=100.0, cy=200.0)
    cancel = anyio.Event()
    outcome = await ch.fire(_fake_action(), target, store, cancel)

    assert outcome.channel == "C5"
    assert outcome.status == "fired"
    assert outcome.fired_at_ns is not None

    inst = _FakeCDPClient.last_instance
    assert inst is not None
    assert len(inst.events) == 2
    # Press first.
    p0 = inst.events[0]
    assert p0["params"]["type"] == "mousePressed"
    assert p0["params"]["button"] == "left"
    assert p0["params"]["clickCount"] == 1
    assert p0["params"]["x"] == 100.0
    assert p0["params"]["y"] == 200.0
    assert p0["sessionId"] == "sess-1"
    # Release second.
    p1 = inst.events[1]
    assert p1["params"]["type"] == "mouseReleased"
    assert p1["sessionId"] == "sess-1"


@pytest.mark.asyncio
async def test_fire_skipped_on_idempotency_lost(store) -> None:
    """Second fire on same action_id returns skipped (T-2-01 race ordering)."""
    ch = C5CDPInputChannel(cdp_client_factory=_FakeCDPClient)
    target = _fake_target()
    action = _fake_action()
    cancel = anyio.Event()

    first = await ch.fire(action, target, store, cancel)
    assert first.status == "fired"

    second = await ch.fire(action, target, store, cancel)
    assert second.status == "skipped"
    assert second.skipped_reason == "idempotency_lost"


@pytest.mark.asyncio
async def test_fire_cancelled_when_cancel_event_set(store) -> None:
    """cancel_event.is_set() before syscall → return cancelled, no dispatch.

    The claim is held (action_id stays burned) so the orchestrator's race
    winner stays canonical (T-2-08 race-cancel correctness)."""
    ch = C5CDPInputChannel(cdp_client_factory=_FakeCDPClient)
    target = _fake_target()
    cancel = anyio.Event()
    cancel.set()

    # Reset class-level last_instance to detect "no client constructed".
    _FakeCDPClient.last_instance = None
    outcome = await ch.fire(_fake_action(), target, store, cancel)
    assert outcome.status == "cancelled"
    # Critical: no CDPClient should have been constructed.
    assert _FakeCDPClient.last_instance is None


@pytest.mark.asyncio
async def test_fire_errored_when_no_session_id(store) -> None:
    ch = C5CDPInputChannel(cdp_client_factory=_FakeCDPClient)
    target = _fake_target()
    bad = target.model_copy(update={"cdp_session_id": None})
    cancel = anyio.Event()
    outcome = await ch.fire(_fake_action(), bad, store, cancel)
    assert outcome.status == "errored"
    assert outcome.error is not None


@pytest.mark.asyncio
async def test_fire_errored_when_no_grounded_bbox(store) -> None:
    ch = C5CDPInputChannel(cdp_client_factory=_FakeCDPClient)
    target = _fake_target()
    bad = target.model_copy(update={"grounded_bbox": None})
    cancel = anyio.Event()
    outcome = await ch.fire(_fake_action(), bad, store, cancel)
    assert outcome.status == "errored"


@pytest.mark.asyncio
async def test_fire_errored_when_no_ws_url_in_extras(store) -> None:
    """C5 reads ws_url from target.extras; missing → errored."""
    ch = C5CDPInputChannel(cdp_client_factory=_FakeCDPClient)
    target = _fake_target()
    bad = target.model_copy(update={"extras": {}})
    cancel = anyio.Event()
    outcome = await ch.fire(_fake_action(), bad, store, cancel)
    assert outcome.status == "errored"
    assert "ws_url" in (outcome.error or "")


@pytest.mark.asyncio
async def test_fire_errored_when_factory_raises(store) -> None:
    """Channel must never raise across the boundary; CDP failures → errored."""
    def _boom(ws_url: str) -> Any:
        raise RuntimeError("simulated socket fail")

    ch = C5CDPInputChannel(cdp_client_factory=_boom)
    target = _fake_target()
    cancel = anyio.Event()
    outcome = await ch.fire(_fake_action(), target, store, cancel)
    assert outcome.status == "errored"
    assert "simulated socket fail" in (outcome.error or "")


@pytest.mark.asyncio
async def test_fire_dispatches_at_bbox_center(store) -> None:
    """Click coordinate is the bbox CENTER (x + w/2, y + h/2)."""
    ch = C5CDPInputChannel(cdp_client_factory=_FakeCDPClient)
    # bbox(40,60,20,30) → center (50,75)
    now = datetime.now(timezone.utc)
    elem = UIElement(
        role="AXUnknown", role_path="CDPElement[1]", label="x",
        bbox=Bbox(x=40, y=60, w=20, h=30),
        pid=1, bundle_id="b", window_id=0,
        discovered_at=now, last_seen_at=now, source=[Source.CDP],
    )
    target = TranslatorTarget(
        element=elem, cdp_node_id=1, cdp_session_id="s",
        grounded_bbox=Bbox(x=40, y=60, w=20, h=30),
        extras={"ws_url": "ws://localhost:9222/x"},
    )
    cancel = anyio.Event()
    out = await ch.fire(_fake_action("act-center"), target, store, cancel)
    assert out.status == "fired"
    inst = _FakeCDPClient.last_instance
    assert inst is not None
    assert inst.events[0]["params"]["x"] == 50  # 40 + 20/2
    assert inst.events[0]["params"]["y"] == 75  # 60 + 30/2
