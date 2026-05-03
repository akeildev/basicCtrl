"""End-to-end: drive Calculator through 5 + 3 = 8 via the framework.

This is the canonical "does it actually work?" smoke for the Phase 1+2 path:
T1AXTranslator resolves each labelled button by walking Calculator's AX tree,
C2AXPressChannel fires kAXPress on the resolved AXUIElement, and after the
sequence completes the Calculator's display reads "8".

Skipped by default unless `CUA_RUN_E2E_CALC=1`. Tests the integration of:
  - profile.classifier (Calculator KnownApp short-circuit)
  - translators.t1_ax (label-based AX walk + ax_ref preservation)
  - actions.channels.c2_ax_press (kAXPress on AXUIElement)
  - actions.idempotency (per-action try_claim)
  - persist.session_writer (NDJSON action_log)

Why a separate file: the existing test_calculator_click.py is gated by F1
(L0+L1 verifier mismatch); this test verifies the action-firing path directly
by reading the Calculator display via AX, not via the L0+L1 ensemble.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from pathlib import Path

import anyio
import pytest

from basicctrl.actions.channels.c2_ax_press import C2AXPressChannel
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.persist.session_writer import SessionWriter
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.translators.base import TargetSpec
from basicctrl.translators.t1_ax import T1AXTranslator


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_E2E_CALC") != "1",
        reason="end-to-end Calculator arithmetic test; set CUA_RUN_E2E_CALC=1 to run",
    ),
]


def _read_calculator_display(pid: int) -> str | None:
    """Walk Calculator's AX tree, return the most-recent AXStaticText AXValue
    that contains a digit. The display sits at depth 7 as an AXStaticText
    inside an AXScrollArea (description='Edit field'). The result is the LAST
    digit-bearing AXStaticText found in BFS order.
    """
    from ApplicationServices import (  # type: ignore[import-not-found]
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
    )

    app = AXUIElementCreateApplication(pid)
    queue: list[tuple[object, int]] = [(app, 0)]
    seen = 0
    last_value: str | None = None
    while queue and seen < 300:
        elem, depth = queue.pop(0)
        seen += 1
        _, role = AXUIElementCopyAttributeValue(elem, "AXRole", None)
        _, value = AXUIElementCopyAttributeValue(elem, "AXValue", None)
        if role == "AXStaticText" and value:
            clean = str(value).replace("‎", "").strip()
            if any(c.isdigit() for c in clean):
                last_value = clean
        if depth >= 8:
            continue
        _, children = AXUIElementCopyAttributeValue(elem, "AXChildren", None)
        if children:
            for c in list(children)[:50]:
                queue.append((c, depth + 1))
    return last_value


async def _click(
    store: IdempotencyTokenStore,
    pid: int,
    label_aliases: list[str],
) -> bool:
    """Try each label in `label_aliases` until one resolves; fire C2 on it.

    Each call constructs a fresh T1AXTranslator so its internal walk bucket
    starts at full capacity. Sharing one T1 across many resolves drains the
    bucket and stalls subsequent walks.
    """
    for label in label_aliases:
        t1 = T1AXTranslator()
        target = await t1.resolve("com.apple.calculator", pid, TargetSpec(label=label))
        if target is None:
            continue
        action = ActionCanonical(
            id=uuid.uuid4().hex,
            step_idx=0,
            kind="MUTATE",
            target_key=target.element.composite_key,
            action_type="click",
            payload={},
            timestamp_ns=time.monotonic_ns(),
            session_id="e2e-arithmetic",
        )
        outcome = await C2AXPressChannel().fire(action, target, store, anyio.Event())
        return outcome.status == "fired"
    return False


@pytest.mark.asyncio
async def test_framework_drives_calculator_5_plus_3_equals_8(
    calculator_pid: int, tmp_path: Path
) -> None:
    """The framework should drive Calculator through 5 + 3 = and read 8."""
    sw = SessionWriter(base=tmp_path)
    store = IdempotencyTokenStore(sw)
    pid = calculator_pid

    # Reset the display to a known state.
    cleared = await _click(store, pid,["All Clear", "Clear", "AC", "C"])
    assert cleared, "could not click All Clear/Clear"
    await asyncio.sleep(0.3)

    assert await _click(store, pid,["5"]), "could not click '5'"
    await asyncio.sleep(0.2)

    assert await _click(store, pid,["+", "Add", "Plus"]), "could not click '+'"
    await asyncio.sleep(0.2)

    assert await _click(store, pid,["3"]), "could not click '3'"
    await asyncio.sleep(0.2)

    assert await _click(store, pid,["=", "Equals", "Equal"]), "could not click '='"
    await asyncio.sleep(0.5)

    display = _read_calculator_display(pid)
    assert display == "8", (
        f"expected '8' on Calculator display, got {display!r}. "
        f"This means the framework either failed to fire one of the clicks "
        f"or Calculator received them but didn't compute as expected."
    )
