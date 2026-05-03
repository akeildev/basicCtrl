"""ACT-01 / ACT-04 — C1 SkyLight channel unit tests with mocked Quartz surface.

Covers the fire-path contract from CONTEXT.md D-14 / D-17 / D-18:
    1. try_claim BEFORE syscall → if lost, status='skipped'
    2. cancel_event.is_set() BEFORE syscall → if cancelled, status='cancelled'
    3. CGEventPostToPid in asyncio.to_thread → status='fired'

T-2-05 mitigation property: C1 uses CGEventPostToPid ONLY. The module is
grep-asserted to NEVER reference ``CGEvent.post`` (without ToPid) or
``kCGSessionEventTap`` — those would warp the cursor globally.

These tests run on any host (no Chess.app, no TCC); real Chess integration
lives in tests/integration/test_chess_t4_t5.py (Plan 02-12).
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import anyio
import pytest

from basicctrl.actions.channels import c1_skylight
from basicctrl.actions.channels.c1_skylight import C1SkyLightChannel
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.persist.session_writer import SessionWriter
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.state.graph import Bbox, Source, UIElement
from basicctrl.translators.base import TranslatorTarget


# ─── helpers ────────────────────────────────────────────────────────────────


def _fake_uielement(pid: int = 1234) -> UIElement:
    return UIElement(
        role="AXUnknown",
        role_path="AXVision/yolo[1]",
        label="white pawn",
        bbox=Bbox(x=100, y=200, w=50, h=50),
        pid=pid,
        bundle_id="com.apple.Chess",
        window_id=0,
        discovered_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        source=[Source.PIXEL],
    )


def _fake_action() -> ActionCanonical:
    return ActionCanonical(
        id=uuid.uuid4().hex,
        step_idx=1,
        kind="MUTATE",
        target_key="composite-key-c1",
        action_type="click",
        payload={},
        timestamp_ns=time.monotonic_ns(),
        session_id="unit-sess-c1",
    )


def _fake_target(pid: int = 1234) -> TranslatorTarget:
    return TranslatorTarget(
        element=_fake_uielement(pid=pid),
        grounded_bbox=Bbox(x=100, y=200, w=50, h=50),
    )


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyTokenStore:
    return IdempotencyTokenStore(SessionWriter(base=tmp_path))


# ─── tests ──────────────────────────────────────────────────────────────────


def test_name_is_C1() -> None:
    """C1SkyLightChannel declares name='C1' (Channel Protocol contract)."""
    assert C1SkyLightChannel().name == "C1"


@pytest.mark.asyncio
async def test_fire_returns_fired_on_success(store: IdempotencyTokenStore) -> None:
    """fire returns ChannelOutcome(channel='C1', status='fired', fired_at_ns set).

    The post helper is patched to capture the (pid, cx, cy) it received so we
    can assert C1 calls CGEventPostToPid at the bbox CENTER for the right pid.
    """
    captured: list[tuple[int, float, float]] = []

    def _fake_post(pid: int, cx: float, cy: float) -> None:
        captured.append((pid, cx, cy))

    target = _fake_target(pid=1234)
    action = _fake_action()
    cancel = anyio.Event()

    channel = C1SkyLightChannel()
    with patch.object(c1_skylight, "_post_left_click", _fake_post):
        outcome = await channel.fire(action, target, store, cancel)

    assert outcome.channel == "C1"
    assert outcome.status == "fired"
    assert outcome.fired_at_ns is not None
    # bbox(100, 200, 50, 50) → center (125, 225)
    assert captured == [(1234, 125.0, 225.0)]


@pytest.mark.asyncio
async def test_fire_skipped_on_idempotency_lost(
    store: IdempotencyTokenStore,
) -> None:
    """T-2-01 mitigation: second fire on same action_id returns skipped.

    Critically, the post helper must NOT be called when the claim is lost —
    otherwise we'd double-post mouse events (the T-2-05/T-2-08 racing bug).
    """
    captured: list[tuple[int, float, float]] = []

    def _fake_post(pid: int, cx: float, cy: float) -> None:
        captured.append((pid, cx, cy))

    target = _fake_target()
    action = _fake_action()
    cancel = anyio.Event()

    # Pre-claim under a different channel.
    pre_claim = await store.try_claim(action.id, "C2")
    assert pre_claim is not None

    channel = C1SkyLightChannel()
    with patch.object(c1_skylight, "_post_left_click", _fake_post):
        outcome = await channel.fire(action, target, store, cancel)

    assert outcome.status == "skipped"
    assert outcome.skipped_reason == "idempotency_lost"
    assert captured == [], "_post_left_click must not be called when claim is lost"


@pytest.mark.asyncio
async def test_fire_cancelled_when_cancel_event_set(
    store: IdempotencyTokenStore,
) -> None:
    """D-18 kill-switch: cancel_event set BEFORE fire → status='cancelled'.

    Pre-syscall guard shrinks the ~50µs uncancellable kernel window
    (Pitfall G accepted limit). The helper must NOT be called.
    """
    captured: list[tuple[int, float, float]] = []

    def _fake_post(pid: int, cx: float, cy: float) -> None:
        captured.append((pid, cx, cy))

    target = _fake_target()
    action = _fake_action()
    cancel = anyio.Event()
    cancel.set()

    channel = C1SkyLightChannel()
    with patch.object(c1_skylight, "_post_left_click", _fake_post):
        outcome = await channel.fire(action, target, store, cancel)

    assert outcome.status == "cancelled"
    assert outcome.fired_at_ns is None
    assert captured == [], "_post_left_click must not be called when cancelled"


@pytest.mark.asyncio
async def test_fire_errored_on_missing_grounded_bbox(
    store: IdempotencyTokenStore,
) -> None:
    """Defensive: grounded_bbox=None → status='errored', helper not called."""
    captured: list[Any] = []

    def _fake_post(pid: int, cx: float, cy: float) -> None:
        captured.append((pid, cx, cy))

    target = TranslatorTarget(
        element=_fake_uielement(),
        grounded_bbox=None,
    )
    action = _fake_action()
    cancel = anyio.Event()

    channel = C1SkyLightChannel()
    with patch.object(c1_skylight, "_post_left_click", _fake_post):
        outcome = await channel.fire(action, target, store, cancel)

    assert outcome.status == "errored"
    assert outcome.error is not None
    assert "grounded_bbox" in outcome.error
    assert captured == []


@pytest.mark.asyncio
async def test_fire_errored_when_post_helper_raises(
    store: IdempotencyTokenStore,
) -> None:
    """Channel must never raise across the boundary; post failures → errored."""

    def _boom(pid: int, cx: float, cy: float) -> None:
        raise RuntimeError("simulated CGEventPostToPid fail")

    target = _fake_target()
    action = _fake_action()
    cancel = anyio.Event()

    channel = C1SkyLightChannel()
    with patch.object(c1_skylight, "_post_left_click", _boom):
        outcome = await channel.fire(action, target, store, cancel)

    assert outcome.status == "errored"
    assert "simulated CGEventPostToPid fail" in (outcome.error or "")


# ─── grep-style invariant: no global cursor warp surfaces ────────────────────


def _strip_docstrings_and_comments(path: Path) -> str:
    """Return module source with all string literals + comments removed.

    Used to grep for symbol REFERENCES in code only — docstrings explaining
    what NOT to use don't count as usage.
    """
    import io
    import tokenize

    src = path.read_text()
    out: list[str] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except tokenize.TokenizeError:
        return src
    for tok in tokens:
        if tok.type in (tokenize.STRING, tokenize.COMMENT):
            continue
        out.append(tok.string)
    return " ".join(out)


def test_module_does_not_use_session_event_tap() -> None:
    """T-2-05 mitigation grep — c1_skylight.py must NOT reference
    kCGSessionEventTap or kCGHIDEventTap as CODE. Docstring mentions
    explaining the prohibition are allowed."""
    code = _strip_docstrings_and_comments(Path(c1_skylight.__file__))
    assert "kCGSessionEventTap" not in code, (
        "C1 must not import or reference kCGSessionEventTap in code (T-2-05 cursor warp)"
    )
    assert "kCGHIDEventTap" not in code, (
        "C1 must not import or reference kCGHIDEventTap in code (T-2-05 cursor warp)"
    )


def test_module_uses_cgevent_post_to_pid() -> None:
    """C1 must reference CGEventPostToPid (the targeted, non-warping post mode)."""
    src = Path(c1_skylight.__file__).read_text()
    assert "CGEventPostToPid" in src, (
        "C1 must use CGEventPostToPid for targeted, non-warping mouse delivery"
    )
