"""ACT-01 / ACT-04 — C4 AppleScript channel unit tests.

Covers the fire-path contract from CONTEXT.md D-14 / D-17 / D-18:
    1. try_claim BEFORE syscall → if lost, status='skipped'
    2. cancel_event.is_set() BEFORE the AS call → if cancelled, status='cancelled'
    3. as_target_spec missing → status='errored'
    4. translator.execute returns (result, None) → status='fired'
    5. translator.execute returns ("", err) → status='errored'

T-2-03 mitigation property: C4 reuses T3's dedicated executor (it does NOT
spin up its own ThreadPoolExecutor). The fire-path delegates to
``self._t3.execute`` which runs on the cua-as pool — verified indirectly
via the dedicated-executor test in tests/unit/translators/test_t3_applescript.py.

These tests run on any host (no Pages, no TCC); real Pages integration
(D-26) lives in Plan 02-12.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anyio
import pytest

from basicctrl.actions.channels.c4_applescript import C4AppleScriptChannel
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.persist.session_writer import SessionWriter
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.state.graph import Bbox, Source, UIElement
from basicctrl.translators.base import TranslatorTarget


def _fake_uielement() -> UIElement:
    return UIElement(
        role="AXUnknown",
        role_path="AppleScript[com.apple.iWork.Pages]",
        label="activate",
        bbox=Bbox(x=0, y=0, w=20, h=20),
        pid=4321,
        bundle_id="com.apple.iWork.Pages",
        window_id=0,
        discovered_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        source=[Source.APPLESCRIPT],
    )


def _fake_action() -> ActionCanonical:
    return ActionCanonical(
        id=uuid.uuid4().hex,
        step_idx=1,
        kind="MUTATE",
        target_key="composite-key-as",
        action_type="as_verb",
        payload={},
        timestamp_ns=time.monotonic_ns(),
        session_id="unit-sess",
    )


class _FakeT3:
    """Test double for T3AppleScriptTranslator.execute().

    Records calls and returns a programmable (result, error) tuple. Never
    constructs a real ThreadPoolExecutor — that's exercised in the T3 tests.
    """

    def __init__(self, return_value: tuple[str, Optional[str]] = ("ok", None)) -> None:
        self.return_value = return_value
        self.calls: list[str] = []

    async def execute(
        self, source: str, args: tuple = ()
    ) -> tuple[str, Optional[str]]:
        self.calls.append(source)
        return self.return_value


@pytest.fixture
def store(tmp_path: Path) -> IdempotencyTokenStore:
    return IdempotencyTokenStore(SessionWriter(base=tmp_path))


def test_name_is_C4() -> None:
    """C4AppleScriptChannel declares name='C4' (Channel Protocol contract)."""
    fake = _FakeT3()
    c = C4AppleScriptChannel(translator=fake)  # type: ignore[arg-type]
    assert c.name == "C4"


async def test_fire_returns_fired_on_success(
    store: IdempotencyTokenStore,
) -> None:
    """fire returns ChannelOutcome(channel='C4', status='fired', fired_at_ns set)."""
    fake = _FakeT3(return_value=("ok", None))
    target = TranslatorTarget(
        element=_fake_uielement(),
        as_target_spec='tell application "Pages" to activate',
    )
    action = _fake_action()
    cancel_event = anyio.Event()

    channel = C4AppleScriptChannel(translator=fake)  # type: ignore[arg-type]
    outcome = await channel.fire(action, target, store, cancel_event)

    assert outcome.channel == "C4"
    assert outcome.status == "fired"
    assert outcome.fired_at_ns is not None
    assert fake.calls == ['tell application "Pages" to activate']


async def test_fire_skipped_on_idempotency_lost(
    store: IdempotencyTokenStore,
) -> None:
    """T-2-01 mitigation: second fire on same action_id returns skipped.

    C4 must call try_claim BEFORE submitting to the executor — verified by
    asserting that the fake translator received zero calls when the claim
    is lost."""
    fake = _FakeT3()
    target = TranslatorTarget(
        element=_fake_uielement(),
        as_target_spec='tell application "Pages" to activate',
    )
    action = _fake_action()
    cancel_event = anyio.Event()

    # Pre-claim under a different channel.
    pre_claim = await store.try_claim(action.id, "C2")
    assert pre_claim is not None

    channel = C4AppleScriptChannel(translator=fake)  # type: ignore[arg-type]
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "skipped"
    assert outcome.skipped_reason == "idempotency_lost"
    assert fake.calls == [], "translator.execute must not be called when claim is lost"


async def test_fire_cancelled_when_cancel_event_set(
    store: IdempotencyTokenStore,
) -> None:
    """D-18 kill-switch: cancel_event set after claim, BEFORE the AS call.
    AppleEvent C4 is uncancellable mid-flight; D-15 stagger pushes execution
    past most race windows so this pre-call check usually wins."""
    fake = _FakeT3()
    target = TranslatorTarget(
        element=_fake_uielement(),
        as_target_spec='tell application "Pages" to activate',
    )
    action = _fake_action()
    cancel_event = anyio.Event()
    cancel_event.set()

    channel = C4AppleScriptChannel(translator=fake)  # type: ignore[arg-type]
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "cancelled"
    assert outcome.fired_at_ns is None
    assert fake.calls == [], "translator.execute must not be called when cancelled"


async def test_fire_errored_on_missing_as_target_spec(
    store: IdempotencyTokenStore,
) -> None:
    """Defensive: as_target_spec=None → status='errored'."""
    fake = _FakeT3()
    target = TranslatorTarget(
        element=_fake_uielement(),
        as_target_spec=None,  # missing
    )
    action = _fake_action()
    cancel_event = anyio.Event()

    channel = C4AppleScriptChannel(translator=fake)  # type: ignore[arg-type]
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "errored"
    assert outcome.error is not None
    assert "as_target_spec" in outcome.error
    assert fake.calls == []


async def test_fire_errored_on_translator_runtime_error(
    store: IdempotencyTokenStore,
) -> None:
    """translator.execute returns ('', err) → ChannelOutcome(status='errored')
    with the error string propagated."""
    fake = _FakeT3(return_value=("", "runtime_error: AppleEvent timeout"))
    target = TranslatorTarget(
        element=_fake_uielement(),
        as_target_spec='tell application "Pages" to crash',
    )
    action = _fake_action()
    cancel_event = anyio.Event()

    channel = C4AppleScriptChannel(translator=fake)  # type: ignore[arg-type]
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "errored"
    assert outcome.error is not None
    assert "AppleEvent timeout" in outcome.error


async def test_fire_errored_on_translator_unexpected_raise(
    store: IdempotencyTokenStore,
) -> None:
    """If translator.execute itself raises (contract violation), C4 catches
    and reports rather than letting the exception escape the channel boundary."""

    class _RaisingT3:
        async def execute(
            self, source: str, args: tuple = ()
        ) -> tuple[str, Optional[str]]:
            raise RuntimeError("unexpected boom")

    target = TranslatorTarget(
        element=_fake_uielement(),
        as_target_spec='tell application "Pages" to activate',
    )
    action = _fake_action()
    cancel_event = anyio.Event()

    channel = C4AppleScriptChannel(translator=_RaisingT3())  # type: ignore[arg-type]
    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "errored"
    assert outcome.error is not None
    assert "unexpected boom" in outcome.error


def test_default_translator_constructed_when_none() -> None:
    """If no translator is passed, C4 instantiates a local T3AppleScriptTranslator
    (production path uses the shared registry instance)."""
    channel = C4AppleScriptChannel()
    assert channel._t3 is not None  # noqa: SLF001
    assert channel._t3.tier == "T3"  # noqa: SLF001
    channel._t3.shutdown()  # noqa: SLF001
