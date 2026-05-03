"""SC #1 — T2 CDP wins on Slack message_container click (D-25).

Pass thresholds (per VALIDATION.md):
  - winner.tier == "T2"
  - winner.channel == "C5"
  - >= 4 losers with status in {cancelled, skipped}
  - near_miss_duplicate_count == 0

Manual prerequisite: Slack must be relaunched with --remote-debugging-port=9222.
The slack_cdp_ws fixture probes localhost:9222 and skips if not present.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from basicctrl.actions.race_policy import RacePolicy

pytestmark = [pytest.mark.integration, pytest.mark.manual]


@pytest.mark.asyncio
async def test_t2_wins_on_slack_message_click(slack_cdp_ws) -> None:
    """SC #1: race click on a Slack message_container; T2 CDP wins, 4 losers cancelled."""
    if slack_cdp_ws is None:
        pytest.skip(
            "Slack not running on localhost:9222. "
            "Run: pkill -9 Slack; sleep 1; open -a Slack --args --remote-debugging-port=9222"
        )

    # Build the same RaceOrchestrator main.py builds, but inline so the test
    # owns lifecycle (avoids tearing down the long-lived MCP proxy).
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
        idem_store = IdempotencyTokenStore(session)

        race_orch = RaceOrchestrator(
            translator_registry=TranslatorRegistry(),
            channel_registry=ChannelRegistry(),
            idem_store=idem_store,
            duplicate_receipt=DuplicateReceipt(),
            axmgr=axmgr,
            aggregator=aggregator,
            l1_cheap=L1Cheap(),
            classifier=classify,
            session_writer=session,
        )

        # Find Slack pid via NSWorkspace.
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
        pid: int | None = None
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            # D-21 KNOWN_APPS key 'com.tinyspeck.slackmacgap' is already lowercase
            # so a direct exact-string match works. Avoid double-lowercasing to
            # surface any future casing drift in Slack's bundle ID.
            if app.bundleIdentifier() == "com.tinyspeck.slackmacgap":
                pid = int(app.processIdentifier())
                break
        assert pid is not None, "Slack must be running"

        # Race click on first message_container in the workspace.
        action, post = await race_orch.execute(
            bundle_id="com.tinyspeck.slackmacgap",
            pid=pid,
            target_spec=TargetSpec(css='[data-qa="message_container"]'),
            action_type="click",
            payload={},
            race_policy=RacePolicy.RACE,
        )

        # SC #1 pass thresholds.
        assert action.tier == "T2", (
            f"expected T2 to win on Slack; got {action.tier} (channel={action.channel})"
        )
        assert action.channel == "C5", (
            f"expected C5 (CDP Input.dispatchMouseEvent); got {action.channel}"
        )
        # The race_winner / race_loser events live in session.action_log.
        # Read the log and assert >= 4 losers + 0 near_miss_duplicate.
        path = Path(session.action_log_path)
        events = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        losers = [
            e for e in events
            if e.get("event") == "race_loser" and e.get("action_id") == action.id
        ]
        winners = [
            e for e in events
            if e.get("event") == "race_winner" and e.get("action_id") == action.id
        ]
        near_misses = [
            e for e in events
            if e.get("event") == "near_miss_duplicate" and e.get("action_id") == action.id
        ]
        assert len(winners) == 1
        assert len(losers) >= 4, (
            f"expected >= 4 losers, got {len(losers)}; events={losers}"
        )
        for loser in losers:
            assert loser["status"] in ("cancelled", "skipped"), (
                f"loser status not cancelled/skipped: {loser}"
            )
        assert len(near_misses) == 0
    finally:
        await axmgr.stop()
        bridge.stop()
        ws.stop()
