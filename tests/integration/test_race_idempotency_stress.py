"""SC #4 — 100 racing fires on Calculator → 0 double-clicks (idempotency holds).

Pass thresholds (per VALIDATION.md):
  - count(claim_events) == 100
  - count(verified_events) == 100
  - count(near_miss_duplicate) == 0

Uses Phase 1's calculator_pid fixture (fastest, no-auth bootstrap).
"""
from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path

import pytest

from cua_overlay.actions.race_policy import RacePolicy

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_100_racing_fires_zero_double_clicks(calculator_pid) -> None:
    """SC #4: drive 100 race-policy clicks on Calculator '5'; assert 0 double-clicks."""
    from cua_overlay.actions import (
        DuplicateReceipt,
        IdempotencyTokenStore,
        RaceOrchestrator,
    )
    from cua_overlay.actions.channel_registry import ChannelRegistry
    from cua_overlay.ax.observer import AXEventBridge
    from cua_overlay.persist import SessionWriter
    from cua_overlay.profile.classifier import classify
    from cua_overlay.translators.base import TargetSpec
    from cua_overlay.translators.registry import TranslatorRegistry
    from cua_overlay.verifier import (
        Aggregator,
        AXObserverManager,
        L0Push,
        L1Cheap,
        L2Medium,
        L3Stub,
        NSWorkspaceObserver,
        WeightedVote,
    )
    import cua_overlay.translators  # noqa: F401 — register on import
    import cua_overlay.actions.channels  # noqa: F401 — register on import

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

        N = 100
        action_ids: list[str] = []
        for _ in range(N):
            action, post = await race_orch.execute(
                bundle_id="com.apple.calculator",
                pid=calculator_pid,
                target_spec=TargetSpec(label="5"),
                action_type="click",
                payload={"x": 664, "y": 908, "label": "5"},
                race_policy=RacePolicy.RACE,
            )
            action_ids.append(action.id)
            # Brief settle so AX observer events drain.
            await asyncio.sleep(0.01)

        # Read action log and tally.
        events = [
            json.loads(line)
            for line in Path(session.action_log_path)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]

        action_id_set = set(action_ids)
        claim_events = [
            e for e in events
            if e.get("event") == "idempotency_claim"
            and e.get("action_id") in action_id_set
        ]
        race_winner_events = [
            e for e in events
            if e.get("event") == "race_winner"
            and e.get("action_id") in action_id_set
        ]
        near_miss_events = [
            e for e in events
            if e.get("event") == "near_miss_duplicate"
            and e.get("action_id") in action_id_set
        ]

        # SC #4 pass thresholds.
        assert len(claim_events) == N, (
            f"expected {N} claim_events, got {len(claim_events)}"
        )
        assert len(race_winner_events) == N, (
            f"expected {N} race_winner events (one per action), got {len(race_winner_events)}"
        )
        assert len(near_miss_events) == 0, (
            f"expected 0 near_miss_duplicate events; got {len(near_miss_events)}: "
            f"{near_miss_events}"
        )

        # WARN-6 — C1/C3 dedup assertion. C1SkyLightChannel and C3CGEventChannel
        # are functionally identical in Phase 2 (both fire CGEventPostToPid;
        # C1's SkyLight upgrade is deferred to Phase 6). When translator_priority
        # selects T4 (default→C1) AND T5 (default→C3), both channels race over
        # the same syscall path; idempotency MUST deduplicate so only ONE
        # actually fires for any given action_id.
        claims_by_action: dict[str, set[str]] = defaultdict(set)
        fires_by_action: dict[str, set[str]] = defaultdict(set)
        for ev in events:
            aid = ev.get("action_id")
            if aid not in action_id_set:
                continue
            if ev.get("event") == "idempotency_claim":
                ch = ev.get("channel")
                if ch:
                    claims_by_action[aid].add(ch)
            if ev.get("event") in ("race_winner", "channel_fired"):
                ch = ev.get("channel")
                status = ev.get("status")
                if ch and status == "fired":
                    fires_by_action[aid].add(ch)

        # Per action: at most one channel produced a SUCCESSFUL claim
        # (try_claim atomicity is the contract — losers see status="skipped").
        for aid, chans in claims_by_action.items():
            assert len(chans) == 1, (
                f"action {aid}: expected exactly 1 channel to win the claim, "
                f"got {len(chans)}: {chans} (T-2-07 atomicity broken)"
            )
        # Per action: at most one of (C1, C3) actually fired (dedup over the
        # CGEventPostToPid syscall path — both channels share kernel surface).
        for aid, fired in fires_by_action.items():
            cgevent_fires = fired & {"C1", "C3"}
            assert len(cgevent_fires) <= 1, (
                f"action {aid}: both C1 and C3 fired {cgevent_fires} — "
                f"CGEventPostToPid dedup failed (Phase 2 hard rule: at most "
                f"one of C1/C3 per action)"
            )
    finally:
        await axmgr.stop()
        bridge.stop()
        ws.stop()
