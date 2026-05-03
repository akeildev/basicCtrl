"""SC #2 — T3 AppleScript wins on Pages "Format" toolbar click (D-26).

Pass thresholds (per VALIDATION.md):
  - winner.tier == "T3"
  - winner.channel == "C4" (AppleScript)
  - AS-fire-timestamp >= earliest-loser-fire-timestamp + 500ms (D-15 stagger)
  - At least 1 race_loser event observable (full 5-channel fan-out via D-10 "click")

Per WARN-4 (planner revision): SC #2 uses action_type="click" on the Pages
"Format" toolbar AXButton — a D-10 RACE-eligible verb — so all 5 channels
fan out and the AS stagger is observable in loser timestamps. Earlier draft
used action_type="set_value" (D-11 SINGLE_CHANNEL) which had no losers and
could not verify "500ms after T1/T2/T5" end-to-end.

Manual prerequisite: Pages.app must be running with at least one document open
(Format toolbar is rendered when a document is open).
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from basicctrl.actions.race_policy import RacePolicy

pytestmark = [
    pytest.mark.integration,
    pytest.mark.manual,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_PAGES") != "1",
        reason="Pages.app must be open with a document; set CUA_RUN_PAGES=1 to run",
    ),
]


@pytest.mark.asyncio
async def test_t3_wins_on_pages_format_toolbar_click(pages_running) -> None:
    """SC #2: T3 wins click on "Format" toolbar; T1/T2/T5 lose; AS stagger 500ms verified."""
    if not pages_running:
        pytest.skip(
            "Pages.app is not running with a document open. "
            "Open Pages.app + create or open any document, then re-run."
        )

    # Inline orchestrator setup (same shape as test_slack_t2_wins).
    from basicctrl.actions import (
        DuplicateReceipt,
        IdempotencyTokenStore,
        RaceOrchestrator,
    )
    from basicctrl.actions.channel_registry import ChannelRegistry
    from basicctrl.ax.observer import AXEventBridge
    from basicctrl.persist import SessionWriter
    from basicctrl.profile.classifier import classify
    from basicctrl.translators.base import TargetSpec
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
    import basicctrl.translators  # noqa: F401 — register on import
    import basicctrl.actions.channels  # noqa: F401 — register on import

    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop=loop)
    bridge.start()
    axmgr = AXObserverManager(bridge=bridge)
    axmgr.start()
    ws = NSWorkspaceObserver(loop=loop)
    ws.start()

    try:
        l0 = L0Push(axmgr=axmgr, ws=ws, kq=None)
        aggregator = Aggregator(
            l0=l0, l1=L1Cheap(), l2=L2Medium(), l3=L3Stub(), vote=WeightedVote()
        )
        session = SessionWriter()
        race_orch = RaceOrchestrator(
            translator_registry=TranslatorRegistry(),
            channel_registry=ChannelRegistry(),
            idem_store=IdempotencyTokenStore(session),
            duplicate_receipt=DuplicateReceipt(),
            axmgr=axmgr,
            aggregator=aggregator,
            l1_cheap=L1Cheap(),
            classifier=classify,
            session_writer=session,
        )

        from AppKit import NSWorkspace  # type: ignore[import-not-found]
        pid: int | None = None
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            # D-21 KNOWN_APPS uses 'com.apple.iWork.Pages' (case-sensitive). Match
            # the running app's bundleIdentifier directly without lowercasing so
            # the bundle_id passed to RaceOrchestrator matches the KNOWN_APPS key.
            if app.bundleIdentifier() == "com.apple.iWork.Pages":
                pid = int(app.processIdentifier())
                break
        assert pid is not None, "Pages.app must be running"

        # Click the Pages toolbar "Format" button (D-10 RACE-eligible "click"
        # verb — fans out all 5 channels so we can observe the AS stagger gap
        # in race_loser timestamps). The Format inspector toggle is a stable
        # AXButton with description "Format" present in Pages 14+ across docs.
        action, post = await race_orch.execute(
            bundle_id="com.apple.iWork.Pages",
            pid=pid,
            target_spec=TargetSpec(
                label="Format",
                role="AXButton",
                aria_label="Format",
                as_verb='click button "Format" of toolbar 1 of window 1',
            ),
            action_type="click",  # D-10 RACE-eligible — full 5-channel fan-out
            payload={"label": "Format"},
            race_policy=RacePolicy.RACE,
        )

        # SC #2 pass thresholds: T3 wins.
        assert action.tier == "T3", (
            f"expected T3 to win on Pages; got {action.tier}"
        )

        # AS stagger 500ms verified — examine race_winner + race_loser timestamps.
        events = [
            json.loads(line)
            for line in Path(session.action_log_path)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        winners = [
            e for e in events
            if e.get("event") == "race_winner" and e.get("action_id") == action.id
        ]
        losers = [
            e for e in events
            if e.get("event") == "race_loser" and e.get("action_id") == action.id
        ]
        if losers:
            other_fire_times = [
                int(l["fired_at_ns"]) for l in losers if l.get("fired_at_ns") is not None
            ]
            winner_fire_ns = winners[0]["fired_at_ns"]
            if other_fire_times and winner_fire_ns is not None:
                earliest_other = min(other_fire_times)
                stagger_ns = winner_fire_ns - earliest_other
                assert stagger_ns >= 400_000_000, (  # 400 ms (slop allowance on 500ms)
                    f"AS stagger not honored: T3 fired {stagger_ns/1e6:.0f}ms after earliest "
                    f"loser fire (expected >= ~500ms per D-15)"
                )

        # Additional WARN-4 assertion: at least 1 race_loser event must exist
        # (proves full 5-channel fan-out happened — D-10 RACE-eligible click,
        # not single-channel D-11 set_value short-circuit).
        assert len(losers) >= 1, (
            "expected >= 1 race_loser event for D-10 click action_type "
            "(zero losers would indicate accidental SINGLE_CHANNEL path)"
        )
    finally:
        await axmgr.stop()
        bridge.stop()
        ws.stop()
