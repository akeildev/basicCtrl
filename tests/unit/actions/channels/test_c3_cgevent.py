"""ACT-01 / ACT-04 — C3 CGEvent channel unit tests with mocked Quartz surface.

Covers the fire-path contract from CONTEXT.md D-14 / D-17 / D-18:
    1. try_claim BEFORE syscall → if lost, status='skipped'
    2. cancel_event.is_set() BEFORE syscall → if cancelled, status='cancelled'
    3. CGEventPostToPid in asyncio.to_thread → status='fired'

C3 is functionally identical to C1 in Phase 2 — both wrap public
CGEventPostToPid. The semantic distinction:
    * C1 = "background no-cursor-warp tier" (Phase 6 SkyLight upgrade)
    * C3 = "foreground with cursor tier" — stays public CGEventPostToPid forever

C3 imports ``_post_left_click`` from c1_skylight to avoid duplication; this
test asserts that import structure to keep DRY enforced.

T-2-05 mitigation property: C3 module must NEVER reference ``CGEvent.post``
(without ToPid) or ``kCGSessionEventTap`` / ``kCGHIDEventTap`` — those would
warp the cursor globally.
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

from cua_overlay.actions.channels import c1_skylight, c3_cgevent
from cua_overlay.actions.channels.c3_cgevent import C3CGEventChannel
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.persist.session_writer import SessionWriter
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.translators.base import TranslatorTarget


# ─── helpers ────────────────────────────────────────────────────────────────


def _fake_uielement(pid: int = 4321) -> UIElement:
    return UIElement(
        role="AXUnknown",
        role_path="AXVision/yolo[1]",
        label="black pawn",
        bbox=Bbox(x=300, y=400, w=40, h=40),
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
        target_key="composite-key-c3",
        action_type="click",
        payload={},
        timestamp_ns=time.monotonic_ns(),
        session_id="unit-sess-c3",
    )


def _fake_target(pid: int = 4321) -> TranslatorTarget:
    return TranslatorTarget(
        element=_fake_uielement(pid=pid),
        grounded_bbox=Bbox(x=300, y=400, w=40, h=40),
    )


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyTokenStore:
    return IdempotencyTokenStore(SessionWriter(base=tmp_path))


# ─── tests ──────────────────────────────────────────────────────────────────


def test_name_is_C3() -> None:
    """C3CGEventChannel declares name='C3' (Channel Protocol contract)."""
    assert C3CGEventChannel().name == "C3"


@pytest.mark.asyncio
async def test_fire_returns_fired_on_success(store: IdempotencyTokenStore) -> None:
    """fire returns ChannelOutcome(channel='C3', status='fired', fired_at_ns set).

    The shared C1 helper is patched to capture (pid, cx, cy) so we can assert
    C3 fires at the bbox CENTER for the right pid.
    """
    captured: list[tuple[int, float, float]] = []

    def _fake_post(pid: int, cx: float, cy: float) -> None:
        captured.append((pid, cx, cy))

    target = _fake_target(pid=4321)
    action = _fake_action()
    cancel = anyio.Event()

    channel = C3CGEventChannel()
    # C3 imports _post_left_click from c1_skylight; patching the c1_skylight
    # symbol does NOT propagate because c3_cgevent already bound the name at
    # import time. Patch on c3_cgevent instead.
    with patch.object(c3_cgevent, "_post_left_click", _fake_post):
        outcome = await channel.fire(action, target, store, cancel)

    assert outcome.channel == "C3"
    assert outcome.status == "fired"
    assert outcome.fired_at_ns is not None
    # bbox(300, 400, 40, 40) → center (320, 420)
    assert captured == [(4321, 320.0, 420.0)]


@pytest.mark.asyncio
async def test_fire_skipped_on_idempotency_lost(
    store: IdempotencyTokenStore,
) -> None:
    """T-2-01 mitigation: second fire on same action_id returns skipped.

    The post helper must NOT be called when the claim is lost — preventing
    the duplicate mouse-post race bug (T-2-05/T-2-08).
    """
    captured: list[tuple[int, float, float]] = []

    def _fake_post(pid: int, cx: float, cy: float) -> None:
        captured.append((pid, cx, cy))

    target = _fake_target()
    action = _fake_action()
    cancel = anyio.Event()

    # Pre-claim under a different channel.
    pre_claim = await store.try_claim(action.id, "C1")
    assert pre_claim is not None

    channel = C3CGEventChannel()
    with patch.object(c3_cgevent, "_post_left_click", _fake_post):
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

    channel = C3CGEventChannel()
    with patch.object(c3_cgevent, "_post_left_click", _fake_post):
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

    channel = C3CGEventChannel()
    with patch.object(c3_cgevent, "_post_left_click", _fake_post):
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

    channel = C3CGEventChannel()
    with patch.object(c3_cgevent, "_post_left_click", _boom):
        outcome = await channel.fire(action, target, store, cancel)

    assert outcome.status == "errored"
    assert "simulated CGEventPostToPid fail" in (outcome.error or "")


# ─── DRY invariant — C3 must reuse C1's post helper, not duplicate ──────────


def test_c3_imports_post_helper_from_c1() -> None:
    """C3 must reuse C1's _post_left_click (DRY); the bound symbol on
    c3_cgevent must be the same function object as on c1_skylight."""
    assert c3_cgevent._post_left_click is c1_skylight._post_left_click, (
        "C3 must import _post_left_click FROM c1_skylight; do not duplicate the helper"
    )


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
    """T-2-05 mitigation grep — c3_cgevent.py must NOT reference
    kCGSessionEventTap or kCGHIDEventTap as CODE. Docstring mentions
    explaining the prohibition are allowed."""
    code = _strip_docstrings_and_comments(Path(c3_cgevent.__file__))
    assert "kCGSessionEventTap" not in code, (
        "C3 must not import or reference kCGSessionEventTap in code (T-2-05 cursor warp)"
    )
    assert "kCGHIDEventTap" not in code, (
        "C3 must not import or reference kCGHIDEventTap in code (T-2-05 cursor warp)"
    )
