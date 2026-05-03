"""TRANS-01 / ACT-04 integration test — T1 + C2 fires Calculator '5' button.

Per CONTEXT.md D-14: T1 default channel binding is C2 (kAXPress). This test
verifies the end-to-end flow: T1 resolves Calculator's '5' button via the
AX walk, then C2 fires AXUIElementPerformAction with try_claim and
cancel_event guards.

Uses a *session-scoped* Calculator fixture (NOT the function-scoped
``calculator_pid`` from Phase 1's conftest). Phase 1's fixture SIGTERMs
Calculator on each teardown, which races the next test's relaunch and
leaves the AX tree in a half-painted state where T1 can't find the keypad
(verified empirically: tests 2-4 fail when paired with the function-scoped
fixture). For Phase 2 translators that need to walk the same app multiple
times, a session-scoped Calculator that stays warm is the right shape.

Skipped under SKIP_INTEGRATION=1 or when Calculator/AppKit unavailable.
"""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
import uuid
from pathlib import Path
from typing import Iterator

import anyio
import pytest

from basicctrl.actions.channels.c2_ax_press import C2AXPressChannel
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.persist.session_writer import SessionWriter
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.translators.base import TargetSpec, TranslatorTarget
from basicctrl.translators.t1_ax import T1AXTranslator


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def calculator_session_pid() -> Iterator[int]:
    """Module-scoped Calculator fixture — launched once, reused across tests.

    Phase 1's function-scoped ``calculator_pid`` fixture (in ``tests/conftest.py``)
    SIGTERMs Calculator on every test teardown; the next test's ``open -a
    Calculator`` may race the still-terminating instance, returning a stale
    pid whose AX tree never paints. This module needs to walk the SAME
    Calculator multiple times in sequence, so we override with a module-scope
    fixture that launches once and tears down at module-exit.
    """
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("integration tests skipped via SKIP_INTEGRATION=1")
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("AppKit (pyobjc) not available — install dev deps first")

    # Make sure no stale Calculator from prior test sessions is around.
    subprocess.run(["pkill", "-9", "-x", "Calculator"], check=False)
    time.sleep(1.0)

    subprocess.run(["open", "-a", "Calculator"], check=True)
    deadline = time.monotonic() + 5.0
    pid: int | None = None
    while time.monotonic() < deadline:
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if (app.bundleIdentifier() or "").lower() == "com.apple.calculator":
                pid = int(app.processIdentifier())
                break
        if pid is not None:
            break
        time.sleep(0.1)
    if pid is None:
        pytest.skip("Calculator.app failed to launch within 5s")

    # Activate so the keypad paints.
    subprocess.run(
        ["osascript", "-e", 'tell application "Calculator" to activate'],
        check=False, timeout=2.0,
    )
    time.sleep(2.0)  # let the keypad finish layout

    # AX readiness probe — wait for the AX tree to expose a window with children.
    # Without this, a previous test's pkill -9 cycle can leave Calculator in a
    # state where the process is alive (NSWorkspace happy) but the AX subsystem
    # hasn't finished rebuilding the tree, and T1's walker reads zero children.
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
        )
        ax_app = AXUIElementCreateApplication(pid)
        ready_deadline = time.monotonic() + 5.0
        while time.monotonic() < ready_deadline:
            err, windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
            if err == 0 and windows:
                err2, win_children = AXUIElementCopyAttributeValue(
                    windows[0], "AXChildren", None
                )
                if err2 == 0 and win_children:
                    break
            time.sleep(0.1)
        else:
            pytest.skip(
                f"Calculator pid={pid} AX tree never populated within 5s "
                f"(probably a race with a prior test's pkill cycle)"
            )
    except ImportError:
        pass  # ApplicationServices not available; skip the probe

    # Don't SIGTERM — see .planning/INTEGRATION-DEBUG.md F2. Leave Calculator
    # running so subsequent tests can reuse the same warm AX tree.
    yield pid


async def _resolve_5(pid: int) -> TranslatorTarget:
    """Resolve Calculator's '5' button. Uses a fresh T1AXTranslator (full bucket).

    The session-scoped ``calculator_session_pid`` fixture guarantees Calculator
    is up and painted; this helper just walks via T1 with a short retry budget
    in case the AX tree is briefly unstable between AppKit refresh cycles.
    """
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        # Fresh translator each attempt — bucket starts full at 200 tokens.
        t1 = T1AXTranslator()
        target = await t1.resolve(
            "com.apple.calculator", pid, TargetSpec(label="5")
        )
        if target is not None:
            return target
        await asyncio.sleep(0.5)
    pytest.fail("T1 could not resolve Calculator '5' button within 5s")
    raise AssertionError("unreachable")  # for type-checker


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


async def test_t1_resolves_calc_5_button(calculator_session_pid: int) -> None:
    """T1 resolves Calculator's '5' button via the AX walk.

    Verifies TRANS-01: T1AXTranslator returns a TranslatorTarget with both
    a UIElement (label='5') and an opaque AXUIElementRef (non-None).
    """
    target = await _resolve_5(calculator_session_pid)
    assert target.element.label.strip() == "5"
    assert target.ax_element is not None


async def test_c2_fires_calc_5_button(
    calculator_session_pid: int, store: IdempotencyTokenStore
) -> None:
    """C2 fires AXUIElementPerformAction on the resolved target.

    Verifies ACT-04: C2AXPressChannel.fire returns
    ChannelOutcome(channel='C2', status='fired', fired_at_ns=...).
    """
    target = await _resolve_5(calculator_session_pid)

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
    calculator_session_pid: int, store: IdempotencyTokenStore
) -> None:
    """ACT-03: second fire on same action_id returns skipped/idempotency_lost."""
    target = await _resolve_5(calculator_session_pid)
    action = _build_action(target.element.composite_key, "test-sess")
    cancel_event = anyio.Event()
    channel = C2AXPressChannel()

    first = await channel.fire(action, target, store, cancel_event)
    assert first.status == "fired"

    second = await channel.fire(action, target, store, cancel_event)
    assert second.status == "skipped"
    assert second.skipped_reason == "idempotency_lost"


async def test_c2_pre_syscall_cancel_event(
    calculator_session_pid: int, store: IdempotencyTokenStore
) -> None:
    """D-18 OS-level kill-switch: cancel_event.is_set() before syscall → cancelled.

    Note the order: claim is held (try_claim happens BEFORE cancel check per
    the contract), but the AXUIElementPerformAction syscall does NOT run.
    """
    target = await _resolve_5(calculator_session_pid)
    action = _build_action(target.element.composite_key, "test-sess")
    cancel_event = anyio.Event()
    cancel_event.set()  # cancel BEFORE fire
    channel = C2AXPressChannel()

    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "cancelled"
    assert outcome.fired_at_ns is None
