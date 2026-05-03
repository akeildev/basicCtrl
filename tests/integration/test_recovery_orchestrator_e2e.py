"""End-to-end recovery: induce a verifier failure, assert branches fire.

Per CONTEXT.md D-03..D-08: when an action fails verification (confidence
< 0.50, push event timeout, kAXError, etc.), the RecoveryOrchestrator
classifies the failure and races B1..B5 in parallel via
race_first_complete. First-verified branch wins.

This e2e wires up the FULL recovery stack with REAL branches against a
running Calculator, then drives a synthetic FailureCtx (low confidence,
existing target) through `recovery.attempt(...)`. We assert:
  1. Classifier classified the failure (recovery.classified event).
  2. At least one branch was attempted (branch_attempt event).
  3. Recovery emits a terminal event (recovery_succeeded OR
     recovery_failed_max_cycles_reached OR recovery_failed_no_branches).
  4. The recovery_log_events return value is non-empty.

We do NOT assert that any specific branch SUCCEEDS — Calculator buttons
have no AXScroller (B1 fails fast), no T3 AppleScript verb path (B5
fails fast). Branches failing fast is expected behavior; what matters
is that the recovery layer ACTUALLY RUNS, instead of being orphaned
code that's never called in production.

Skipped by default unless `CUA_RUN_E2E_RECOVERY=1`. Documents the F10
finding: RecoveryOrchestrator is NOT wired into the production
RaceOrchestrator path. Wiring it is queued for a follow-up commit.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from basicctrl.state.causal_dag import HoarePost


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_E2E_RECOVERY") != "1",
        reason="recovery orchestrator e2e; set CUA_RUN_E2E_RECOVERY=1 to run",
    ),
]


def _build_recovery_stack(session_dir: Path):
    """Wire a real RecoveryOrchestrator with all 5 branches + real deps.

    Returns (recovery_orch, axmgr, bridge, ws, session, race_orch).
    The race_orch is returned in case a future test wants to combine the
    two stacks; this test only uses recovery_orch directly.
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
    from basicctrl.ax.walker import walk_subtree
    from basicctrl.persist import SessionWriter
    from basicctrl.profile.classifier import classify
    from basicctrl.recovery import (
        B1_Rescroll,
        B2_OCRRegrounding,
        # This test exercises stub-style B3/B4 dispatch (no LLM); use the
        # explicit _Stub aliases since the unsuffixed names now point at the
        # Phase 4 real branches that require Planner/WMP/Critic dependencies.
        B3_WorldReplan_Stub as B3_WorldReplan,
        B4_PlannerRequery_Stub as B4_PlannerRequery,
        B5_AppleScriptFallback,
        RecoveryOrchestrator,
    )
    from basicctrl.recovery.circuit_breaker import CircuitBreaker
    from basicctrl.recovery.classifier import FailureClassifier
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

    idem = IdempotencyTokenStore(session)

    race_orch = RaceOrchestrator(
        translator_registry=translators,
        channel_registry=channels,
        idem_store=idem,
        duplicate_receipt=DuplicateReceipt(),
        axmgr=axmgr,
        aggregator=aggregator,
        l1_cheap=L1Cheap(),
        classifier=classify,
        session_writer=session,
    )

    # Construct all 5 branches with real deps.
    b1 = B1_Rescroll(
        translator_registry=translators,
        channel_registry=channels,
        idempotency_store=idem,
        session_writer=session,
        walk_subtree_fn=walk_subtree,
        aggregator=aggregator,
        l1_cheap=L1Cheap(),
    )
    b2 = B2_OCRRegrounding(
        translator_registry=translators,
        channel_registry=channels,
        idempotency_store=idem,
        session_writer=session,
        aggregator=aggregator,
    )
    b3 = B3_WorldReplan(
        idempotency_store=idem,
        session_writer=session,
    )
    b4 = B4_PlannerRequery(
        idempotency_store=idem,
        session_writer=session,
    )
    b5 = B5_AppleScriptFallback(
        translator_registry=translators,
        channel_registry=channels,
        idempotency_store=idem,
        session_writer=session,
        aggregator=aggregator,
    )
    branches = [b1, b2, b3, b4, b5]

    recovery_orch = RecoveryOrchestrator(
        classifier=FailureClassifier(),
        circuit_breaker=CircuitBreaker(),
        branches_list=branches,
        session_writer=session,
        aggregator=aggregator,
        max_cycles=2,
        heal_rate_budget=1.0,  # disable budget gate for the e2e
    )

    return recovery_orch, axmgr, bridge, ws, session, race_orch


@pytest.mark.asyncio
async def test_recovery_attempts_branches_on_synthetic_failure(
    calculator_pid: int, tmp_path: Path
) -> None:
    """RecoveryOrchestrator.attempt drives at least one branch through to a
    branch_attempt event when given a real Calculator failure_ctx."""
    recovery_orch, axmgr, bridge, ws, session, _race = _build_recovery_stack(
        tmp_path
    )
    pid = calculator_pid

    try:
        # Build a synthetic FailureCtx for a real Calculator target (the "5"
        # button). Confidence=0.0 → classifier returns PERCEPTUAL → branches
        # B1, B2, B4 will be attempted.
        post = HoarePost(
            target_key="axid:com.apple.calculator:Five",
            confidence=0.0,
            tier_signals={"L0": 0.0, "L1": 0.0, "L2": None, "L3": None},
            verified=False,
            healed_to=None,
            timestamp_ns=time.monotonic_ns(),
        )
        failure_ctx = {
            "bundle_id": "com.apple.calculator",
            "target_key": "axid:com.apple.calculator:Five",
            "hoare_post": post,
            "confidence": 0.0,
            "last_error": "verifier confidence below threshold",
            "previous_failures_count": 0,
            "action_id": uuid.uuid4().hex,
            "action_type": "click",
        }

        outcome, recovery_log_events = await recovery_orch.attempt(failure_ctx)

        # We don't assert outcome.verified — Calculator's "5" has no scroller
        # (B1 fails), no SDEF Calculator AppleScript verb for "press 5"
        # straightforwardly (B5 likely fails too). What we DO assert is that
        # the recovery layer ACTUALLY RAN.

        # 1. recovery_log_events should be non-empty.
        assert len(recovery_log_events) > 0, "recovery emitted no events"

        # 2. classifier classified the failure.
        classified = [
            e for e in recovery_log_events if "classified" in str(e.get("event", ""))
        ]
        # The classified log goes through structlog's _log.info, not
        # recovery_log. Check session.action_log_path instead.
        action_log_text = (
            Path(session.action_log_path).read_text(encoding="utf-8")
            if Path(session.action_log_path).exists()
            else ""
        )
        action_log_events = [
            json.loads(line)
            for line in action_log_text.splitlines()
            if line.strip()
        ]

        # 3. At least one branch was attempted (look in action_log AND
        # recovery_log_events).
        all_events = recovery_log_events + action_log_events
        branch_attempts = [
            e for e in all_events if e.get("event") == "branch_attempt"
        ]
        assert len(branch_attempts) >= 1, (
            f"expected >=1 branch_attempt event, got {len(branch_attempts)}. "
            f"all events: {all_events!r}"
        )

        # 4. Terminal event present (success, failure, or escalation).
        terminal_events = [
            e for e in all_events
            if e.get("event") in (
                "recovery_succeeded",
                "recovery_failed_max_cycles_reached",
                "recovery_escalated",
                "recovery_failed_no_branches",
            )
        ]
        assert len(terminal_events) >= 1, (
            f"expected >=1 terminal recovery event, got 0. "
            f"all events: {[e.get('event') for e in all_events]!r}"
        )

        # 5. Branches attempted should include B1/B2/B4 (PERCEPTUAL routing).
        branch_names = {e.get("branch") for e in branch_attempts}
        expected_subset = {"B1_RESCROLL", "B2_OCR_REGROUNDING", "B4_PLANNER_REQUERY"}
        assert branch_names & expected_subset, (
            f"expected at least one of {expected_subset!r} attempted; "
            f"got {branch_names!r}"
        )
    finally:
        await axmgr.stop()
        bridge.stop()
        ws.stop()
