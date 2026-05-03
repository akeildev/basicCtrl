"""End-to-end through RaceOrchestrator: drive Calculator 5 + 3 = 8.

Companion to test_calculator_e2e_arithmetic.py. The direct test goes
T1 -> C2 with no race wrapper. THIS test goes through the full Phase 2
RaceOrchestrator.execute(...) path:

  classify -> select_for_priority -> resolve+validate -> AX subscribe ->
  L1 snapshot -> select channels (C2/C1/C3 for Calculator T1/T4/T5) ->
  race_first_complete -> Aggregator.verify -> DuplicateReceipt.record ->
  fill action.tier+channel from winner -> emit race telemetry.

Pass criteria:
  - Calculator display reads "8" after the 5-step sequence.
  - Each step's winner is T1 (Calculator's preferred tier per KNOWN_APPS).
  - At least one race_winner event landed in SessionWriter's action_log.
  - Optional: at least one race_loser event landed (proves multi-channel
    fan-out really happened — Calculator priority is ['T1','T4','T5'] so
    C2 + C1 + C3 should all be in the channel set for D-10 RACE-eligible
    'click' verb).

Skipped by default unless `CUA_RUN_E2E_RACE=1`. Requires Accessibility
permission for the Python interpreter (same gate as CUA_RUN_E2E_CALC).
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import pytest

from basicctrl.translators.base import TargetSpec


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_E2E_RACE") != "1",
        reason="race orchestrator end-to-end on Calculator; set CUA_RUN_E2E_RACE=1 to run",
    ),
]


def _read_calculator_display(pid: int) -> str | None:
    """Same display-reader as test_calculator_e2e_arithmetic — walk AX tree
    and return the last digit-bearing AXStaticText in BFS order."""
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


def _build_orchestrator(session_dir: Path):
    """Wire a real RaceOrchestrator with all Phase 1+2 deps registered.

    Returns (race_orch, axmgr, bridge, ws, session) so the test can teardown
    + read the action_log_path.
    """
    from basicctrl.actions import (
        DuplicateReceipt,
        IdempotencyTokenStore,
        RaceOrchestrator,
    )
    from basicctrl.actions.channel_registry import ChannelRegistry
    from basicctrl.actions.channels import (
        C1SkyLightChannel,
        C2AXPressChannel,
        C3CGEventChannel,
        C4AppleScriptChannel,
        C5CDPInputChannel,
    )
    from basicctrl.ax.observer import AXEventBridge
    from basicctrl.persist import SessionWriter
    from basicctrl.profile.classifier import classify
    from basicctrl.translators import (
        T1AXTranslator,
        T2CDPTranslator,
        T3AppleScriptTranslator,
        T4VisionTranslator,
        T5PixelTranslator,
    )
    from basicctrl.translators.registry import TranslatorRegistry
    from basicctrl.verifier import (
        Aggregator,
        AXObserverManager,
        L0Push,
        L1Cheap,
        L2Medium,
        L3Stub,
        NSWorkspaceObserver,
        WeightedVote,
    )

    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop=loop)
    bridge.start()
    axmgr = AXObserverManager(bridge=bridge)
    axmgr.start()
    ws = NSWorkspaceObserver(loop=loop)
    ws.start()

    l0 = L0Push(axmgr=axmgr, ws=ws, kq=None)
    aggregator = Aggregator(
        l0=l0, l1=L1Cheap(), l2=L2Medium(), l3=L3Stub(), vote=WeightedVote()
    )

    session = SessionWriter(base=session_dir)

    translators = TranslatorRegistry()
    translators.register(T1AXTranslator())
    translators.register(T2CDPTranslator())
    translators.register(T3AppleScriptTranslator())
    t4 = T4VisionTranslator()
    translators.register(t4)
    translators.register(T5PixelTranslator(t4=t4))

    channels = ChannelRegistry()
    channels.register(C1SkyLightChannel())
    channels.register(C2AXPressChannel())
    channels.register(C3CGEventChannel())
    channels.register(C4AppleScriptChannel())
    channels.register(C5CDPInputChannel())

    race_orch = RaceOrchestrator(
        translator_registry=translators,
        channel_registry=channels,
        idem_store=IdempotencyTokenStore(session),
        duplicate_receipt=DuplicateReceipt(),
        axmgr=axmgr,
        aggregator=aggregator,
        l1_cheap=L1Cheap(),
        classifier=classify,
        session_writer=session,
    )
    return race_orch, axmgr, bridge, ws, session


async def _click_via_race(
    race_orch,
    pid: int,
    label_aliases: list[str],
):
    """Try each label alias until race_orch.execute returns. Returns the
    (action, post) tuple on first success or raises on total failure."""
    from basicctrl.actions.race_orchestrator import NoTargetResolvable
    from basicctrl.actions.race_policy import RacePolicy

    last_exc: Exception | None = None
    for label in label_aliases:
        try:
            action, post = await race_orch.execute(
                bundle_id="com.apple.calculator",
                pid=pid,
                target_spec=TargetSpec(label=label),
                action_type="click",
                payload={"label": label},
                race_policy=RacePolicy.RACE,
            )
            return action, post
        except NoTargetResolvable as exc:
            last_exc = exc
            continue
    raise AssertionError(
        f"no label in {label_aliases!r} resolved on Calculator pid={pid}"
    ) from last_exc


@pytest.mark.asyncio
async def test_race_orchestrator_drives_calculator_5_plus_3_equals_8(
    calculator_pid: int, tmp_path: Path
) -> None:
    """RaceOrchestrator.execute drives Calculator through 5 + 3 = and reads 8."""
    race_orch, axmgr, bridge, ws, session = _build_orchestrator(tmp_path)
    pid = calculator_pid
    actions: list = []
    posts: list = []

    try:
        # Reset display.
        action, post = await _click_via_race(
            race_orch, pid, ["All Clear", "Clear", "AC", "C"]
        )
        actions.append(action); posts.append(post)
        await asyncio.sleep(0.3)

        action, post = await _click_via_race(race_orch, pid, ["5"])
        actions.append(action); posts.append(post)
        await asyncio.sleep(0.2)

        action, post = await _click_via_race(
            race_orch, pid, ["+", "Add", "Plus"]
        )
        actions.append(action); posts.append(post)
        await asyncio.sleep(0.2)

        action, post = await _click_via_race(race_orch, pid, ["3"])
        actions.append(action); posts.append(post)
        await asyncio.sleep(0.2)

        action, post = await _click_via_race(
            race_orch, pid, ["=", "Equals", "Equal"]
        )
        actions.append(action); posts.append(post)
        await asyncio.sleep(0.5)

        display = _read_calculator_display(pid)
        assert display == "8", (
            f"expected '8' on Calculator display, got {display!r}. "
            f"action winners: {[(a.tier, a.channel) for a in actions]!r}"
        )

        # Every winner should be T1 — Calculator priority is ['T1','T4','T5']
        # and T1 is fastest (in-process AX call vs CGEvent+postToPid hop).
        for a in actions:
            assert a.tier == "T1", (
                f"expected T1 to win on Calculator; got {a.tier!r} for "
                f"action_id={a.id!r} target_key={a.target_key!r}"
            )

        # Post-F9 fix: verifier sees AXValueChanged from the display via the
        # AX-application-root subscription. Every click should verify L0 push
        # (confidence == 1.0). The All Clear click is the exception — when
        # the display already reads "0" the press doesn't change AXValue, so
        # AXValueChanged doesn't fire. Skip that one in the assertion.
        verified_count = sum(1 for p in posts[1:] if p.verified)
        assert verified_count >= 4, (
            f"expected >=4 of the last 4 clicks to verify via L0 push; "
            f"got {verified_count}. posts={[(p.verified, p.confidence) for p in posts]!r}"
        )

        # NDJSON race telemetry sanity check.
        events = [
            json.loads(line)
            for line in Path(session.action_log_path)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        winner_events = [e for e in events if e.get("event") == "race_winner"]
        loser_events = [e for e in events if e.get("event") == "race_loser"]
        assert len(winner_events) >= 5, (
            f"expected >= 5 race_winner events (one per click); "
            f"got {len(winner_events)}"
        )
        # Calculator priority is T1/T4/T5 -> channels C2/C1/C3 — all three
        # should fan out per click, so loser events must exist.
        assert len(loser_events) >= 1, (
            "expected >= 1 race_loser event for D-10 RACE click on Calculator "
            "(zero losers would mean accidental SINGLE_CHANNEL path)"
        )
    finally:
        await axmgr.stop()
        bridge.stop()
        ws.stop()
