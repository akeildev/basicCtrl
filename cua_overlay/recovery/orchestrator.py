"""Recovery orchestrator — parallel recovery branch fanout with bounded cycles.

Per CONTEXT.md D-09..D-11, D-16, D-25: RecoveryOrchestrator coordinates
parallel recovery branch execution after verification failure. It:

1. Consults circuit breaker; skips if tripped (D-12)
2. Checks heal-rate budget; pauses if >5% (D-16)
3. Classifies failure via FailureClassifier (D-01/D-02)
4. Fans out 5 branches in parallel via race_first_complete (D-09)
5. First verified branch wins; losers cancelled (anyio pattern from Phase 2)
6. Logs all outcomes to recovery_log.ndjson for RL training (D-10)
7. Records failures for circuit breaker increment (D-12)
8. Bounded to max 2 cycles (D-11); escalates to user after that

Pattern: Reuse Phase 2's anyio cancel_scope race pattern for clean
branch cancellation. Use @runtime_checkable RecoveryBranch Protocol.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Tuple

import anyio
import structlog

from cua_overlay.recovery.classifier import (
    FailureClass,
    FailureClassifier,
    FailureCtx,
    FAILURE_CLASS_TO_BRANCHES,
)
from cua_overlay.recovery.circuit_breaker import CircuitBreaker

if TYPE_CHECKING:
    from cua_overlay.actions.channels.base import ChannelOutcome
    from cua_overlay.persist.session_writer import SessionWriter
    from cua_overlay.profile.classifier import AppProfile
    from cua_overlay.verifier.aggregator import Aggregator

_log = structlog.get_logger()


class RecoveryOrchestrator:
    """Orchestrate parallel recovery branches after verification failure.

    Bounded by max_cycles (default 2) and heal-rate budget (default 5%).
    First-verified-branch wins via race_first_complete pattern from Phase 2.
    All outcomes logged to recovery_log.ndjson for RL training + session replay.
    """

    def __init__(
        self,
        classifier: FailureClassifier,
        circuit_breaker: CircuitBreaker,
        branches_list: List[Any],  # RecoveryBranch instances [B1-B5]
        session_writer: SessionWriter,
        aggregator: Aggregator,
        max_cycles: int = 2,
        heal_rate_budget: float = 0.05,
        escalate_callback: Optional[Callable[[dict], Any]] = None,
    ):
        """Initialize recovery orchestrator.

        Args:
            classifier: FailureClassifier for classifying failures into 6 classes
            circuit_breaker: CircuitBreaker for preventing cascading failures
            branches_list: List of RecoveryBranch instances [B1, B2, B3, B4, B5]
            session_writer: SessionWriter for logging events + heal-rate tracking
            aggregator: Aggregator for verifying branch outcomes
            max_cycles: Max recovery cycles before escalating to user (default 2)
            heal_rate_budget: Heal budget threshold as fraction 0.0-1.0 (default 0.05 = 5%)
            escalate_callback: Optional async callable invoked when recovery escalates
                Called with dict containing action_id, target_key, branches_tried, etc.
        """
        self._classifier = classifier
        self._breaker = circuit_breaker
        self._branches = branches_list
        self._session = session_writer
        self._aggregator = aggregator
        self.max_cycles = max_cycles
        self._heal_budget = heal_rate_budget
        self._escalate_callback = escalate_callback

        # Heal-rate budget tracking (incremented by external callers during session)
        self._heal_event_count = 0
        self._total_actions = 0
        self._lock = asyncio.Lock()

    async def increment_heal_count(self, count: int = 1) -> None:
        """Track heal events (called externally after each heal).

        Args:
            count: Number of heals to add (default 1)
        """
        async with self._lock:
            self._heal_event_count += count

    async def increment_action_count(self, count: int = 1) -> None:
        """Track total actions (called by RaceOrchestrator after each action).

        Args:
            count: Number of actions to add (default 1)
        """
        async with self._lock:
            self._total_actions += count

    async def _get_heal_ratio(self) -> float:
        """Return current heal-to-action ratio (0.0-1.0).

        Returns:
            heal_event_count / max(1, total_actions), clamped to [0.0, 1.0]
        """
        async with self._lock:
            if self._total_actions == 0:
                return 0.0
            ratio = self._heal_event_count / max(1, self._total_actions)
            return min(1.0, max(0.0, ratio))

    async def attempt(
        self,
        failure_ctx: FailureCtx,
        app_profile: Optional[AppProfile] = None,
    ) -> Tuple[Optional[ChannelOutcome], List[dict]]:
        """Attempt recovery after verification failure.

        Core loop (per D-11 bounded cycles):
          1. Check circuit breaker; skip if tripped
          2. Check heal-rate budget; pause if >5%
          3. Classify failure into 6 classes
          4. Look up branches for this class
          5. Fan out branches in parallel via race_first_complete
          6. First-verified-branch wins; losers cancelled
          7. Log outcomes to recovery_log.ndjson for RL training
          8. Record failure for circuit breaker
          9. Repeat up to max_cycles; escalate to user if all fail

        Args:
            failure_ctx: FailureCtx with bundle_id, target_key, hoare_post,
                confidence, last_error, previous_failures_count
            app_profile: Optional AppProfile for circuit breaker reordering

        Returns:
            Tuple[winning_outcome, recovery_log_events] where:
              - winning_outcome: ChannelOutcome from first-verified branch,
                or None if all cycles fail
              - recovery_log_events: list of structured dicts for RL training
        """
        action_id = str(uuid.uuid4())
        bundle_id = failure_ctx["bundle_id"]
        target_key = failure_ctx["target_key"]
        recovery_log_events: List[dict] = []

        structlog.contextvars.bind_contextvars(
            action_id=action_id, bundle_id=bundle_id, target_key=target_key
        )

        _log.info(
            "recovery.attempt_start",
            action_id=action_id,
            bundle_id=bundle_id,
            target_key=target_key,
        )

        # Main recovery cycle loop (max 2 attempts per D-11)
        cycle = 0
        while cycle < self.max_cycles:
            cycle += 1

            _log.debug(
                "recovery.cycle_start",
                cycle=cycle,
                max_cycles=self.max_cycles,
            )

            # D-12: Circuit breaker check
            if await self._breaker.is_tripped(bundle_id, target_key):
                event = {
                    "event": "recovery_skipped_breaker_tripped",
                    "action_id": action_id,
                    "bundle_id": bundle_id,
                    "target_key": target_key,
                    "cycle": cycle,
                    "ts": datetime.utcnow().isoformat(),
                }
                recovery_log_events.append(event)
                await self._session.append_action_log(event)

                _log.info("recovery.breaker_tripped", action_id=action_id)
                await self._escalate_to_user(
                    action_id=action_id,
                    target_key=target_key,
                    last_error=failure_ctx.get("last_error", "unknown"),
                    branches_attempted=[],
                    reason="circuit_breaker_tripped",
                )
                return None, recovery_log_events

            # D-16: Heal-rate budget check
            heal_ratio = await self._get_heal_ratio()
            if heal_ratio > self._heal_budget:
                event = {
                    "event": "recovery_skipped_heal_budget_exceeded",
                    "action_id": action_id,
                    "bundle_id": bundle_id,
                    "target_key": target_key,
                    "cycle": cycle,
                    "heal_ratio": float(heal_ratio),
                    "heal_budget": self._heal_budget,
                    "ts": datetime.utcnow().isoformat(),
                }
                recovery_log_events.append(event)
                await self._session.append_action_log(event)

                _log.info(
                    "recovery.heal_budget_exceeded",
                    action_id=action_id,
                    heal_ratio=heal_ratio,
                )
                await self._escalate_to_user(
                    action_id=action_id,
                    target_key=target_key,
                    last_error="heal rate budget exceeded",
                    branches_attempted=[],
                    reason="heal_budget_exceeded",
                )
                return None, recovery_log_events

            # D-01/D-02: Classify failure
            failure_class, classify_confidence = self._classifier.classify(
                failure_ctx
            )
            _log.info(
                "recovery.classified",
                action_id=action_id,
                failure_class=failure_class.value,
                confidence_pct=classify_confidence,
            )

            # Look up branches for this class
            branch_ids = FAILURE_CLASS_TO_BRANCHES.get(failure_class, [])
            branches_to_try = [
                b for b in self._branches if self._get_branch_name(b) in branch_ids
            ]

            if not branches_to_try:
                # No branches for this class; shouldn't happen in normal operation
                _log.warning(
                    "recovery.no_branches_for_class",
                    action_id=action_id,
                    failure_class=failure_class.value,
                )
                await self._escalate_to_user(
                    action_id=action_id,
                    target_key=target_key,
                    last_error=failure_ctx.get("last_error", "unknown"),
                    branches_attempted=branch_ids,
                    reason="no_branches_available",
                )
                return None, recovery_log_events

            # D-09: Fan out branches in parallel
            winning_outcome, all_outcomes = await self._race_branches(
                branches_to_try, failure_ctx
            )

            if winning_outcome is not None:
                # D-03: Log success to recovery_log
                event = {
                    "event": "recovery_succeeded",
                    "action_id": action_id,
                    "cycle": cycle,
                    "winning_branch": self._get_branch_name(
                        all_outcomes[0][0]
                    ),  # branch name
                    "bundle_id": bundle_id,
                    "target_key": target_key,
                    "ts": datetime.utcnow().isoformat(),
                }
                recovery_log_events.append(event)
                await self._session.append_action_log(event)

                _log.info(
                    "recovery.succeeded",
                    action_id=action_id,
                    cycle=cycle,
                    winning_branch=self._get_branch_name(all_outcomes[0][0]),
                )
                return winning_outcome, recovery_log_events

            # D-10: Log failed branches to RL training buffer
            for branch, outcome in all_outcomes:
                branch_name = self._get_branch_name(branch)
                error_msg = (
                    outcome.error if outcome and hasattr(outcome, "error")
                    else "unknown error"
                )
                event = {
                    "event": "recovery_branch_failed",
                    "action_id": action_id,
                    "cycle": cycle,
                    "branch": branch_name,
                    "reason": str(error_msg),
                    "bundle_id": bundle_id,
                    "target_key": target_key,
                    "ts": datetime.utcnow().isoformat(),
                }
                recovery_log_events.append(event)
                await self._session.append_action_log(event)

                _log.debug(
                    "recovery.branch_failed",
                    action_id=action_id,
                    branch=branch_name,
                    reason=error_msg,
                )

            # D-12: Record failure for circuit breaker
            if app_profile is not None:
                just_tripped = await self._breaker.record_failure(
                    bundle_id, target_key, app_profile
                )
                if just_tripped:
                    _log.info(
                        "recovery.circuit_breaker_tripped_after_record",
                        action_id=action_id,
                        bundle_id=bundle_id,
                        target_key=target_key,
                    )
            else:
                # Still record without profile
                await self._breaker.record_failure(bundle_id, target_key, None)

            # Prepare for next cycle
            if cycle < self.max_cycles:
                # Update context for next iteration
                prev_count = failure_ctx.get("previous_failures_count", 0)
                failure_ctx["previous_failures_count"] = prev_count + 1
                _log.debug(
                    "recovery.cycle_complete_prepare_next",
                    action_id=action_id,
                    cycle=cycle,
                )

        # D-11: Escalate after max cycles exhausted
        event = {
            "event": "recovery_exhausted",
            "action_id": action_id,
            "cycles_tried": self.max_cycles,
            "branches_attempted": branch_ids,
            "bundle_id": bundle_id,
            "target_key": target_key,
            "ts": datetime.utcnow().isoformat(),
        }
        recovery_log_events.append(event)
        await self._session.append_action_log(event)

        _log.info(
            "recovery.exhausted",
            action_id=action_id,
            cycles_tried=self.max_cycles,
        )

        await self._escalate_to_user(
            action_id=action_id,
            target_key=target_key,
            last_error=failure_ctx.get("last_error", "unknown"),
            branches_attempted=branch_ids,
            reason="max_cycles_exhausted",
        )

        return None, recovery_log_events

    async def _race_branches(
        self,
        branches: List[Any],
        failure_ctx: FailureCtx,
    ) -> Tuple[Optional[Any], List[Tuple[Any, Optional[Any]]]]:
        """Race branches in parallel; return first-verified + all outcomes.

        Per D-09, D-13: Uses anyio.create_task_group + cancel_scope.cancel()
        pattern from Phase 2 (race_first_complete reused logic).

        Args:
            branches: List of RecoveryBranch instances to race
            failure_ctx: FailureCtx passed to each branch.attempt()

        Returns:
            Tuple[winning_outcome, all_outcomes] where:
              - winning_outcome: ChannelOutcome from first branch to return
                a verified outcome, None if all fail
              - all_outcomes: list of (branch, outcome) tuples for logging
        """
        n_branches = len(branches)
        results: List[Optional[Any]] = [None] * n_branches
        winner_idx_box: List[int] = [-1]

        async def _runner(idx: int, branch: Any, tg: Any) -> None:
            """Run one branch.attempt coroutine."""
            try:
                outcome = await branch.attempt(failure_ctx)
                results[idx] = outcome

                # First non-None outcome wins
                if winner_idx_box[0] == -1 and outcome is not None:
                    # Check if outcome is verified (has verified=True attribute)
                    is_verified = (
                        hasattr(outcome, "verified")
                        and outcome.verified is True
                    )
                    if is_verified or (
                        hasattr(outcome, "status")
                        and outcome.status == "fired"
                    ):
                        winner_idx_box[0] = idx
                        tg.cancel_scope.cancel()

            except anyio.get_cancelled_exc_class():
                # Cancelled by winner; record marker if no result yet
                if results[idx] is None:
                    results[idx] = None
                raise
            except Exception as exc:  # noqa: BLE001
                results[idx] = exc
                _log.debug(
                    "recovery._race_branches._runner_exception",
                    branch_idx=idx,
                    error=str(exc),
                )

        async with anyio.create_task_group() as tg:
            for idx, branch in enumerate(branches):
                tg.start_soon(_runner, idx, branch, tg)

        # Build outcome list: (branch, outcome)
        all_outcomes: List[Tuple[Any, Optional[Any]]] = []
        for idx, branch in enumerate(branches):
            all_outcomes.append((branch, results[idx]))

        # Return winner (if any) + all outcomes
        if winner_idx_box[0] >= 0:
            winning = results[winner_idx_box[0]]
            return winning, all_outcomes
        else:
            return None, all_outcomes

    async def _escalate_to_user(
        self,
        action_id: str,
        target_key: str,
        last_error: str,
        branches_attempted: List[str],
        reason: str = "unknown",
    ) -> None:
        """Escalate recovery failure to user (Phase 3: log; Phase 5: HUD).

        Per D-11, D-25: Emit structured event with actionable message.
        In Phase 3, this logs to recovery_log.ndjson.
        In Phase 5, this surfaces in HUD overlay.

        Args:
            action_id: UUID of the action that failed recovery
            target_key: Composite locator key
            last_error: Last error message from verifier
            branches_attempted: List of branch IDs attempted
            reason: Reason for escalation (circuit_breaker_tripped,
                heal_budget_exceeded, max_cycles_exhausted, etc.)
        """
        # Build user-facing message with suggested action
        suggested_action = self._suggest_action_for_error(last_error, reason)

        event = {
            "event": "recovery_escalated",
            "action_id": action_id,
            "target_key": target_key,
            "last_error": last_error,
            "branches_tried": branches_attempted,
            "reason": reason,
            "suggested_action": suggested_action,
            "ts": datetime.utcnow().isoformat(),
        }

        await self._session.append_action_log(event)

        if self._escalate_callback is not None:
            res = self._escalate_callback(event)
            if hasattr(res, "__await__"):
                await res

        _log.info(
            "recovery.escalated",
            action_id=action_id,
            reason=reason,
            suggested_action=suggested_action,
        )

    def _suggest_action_for_error(self, last_error: str, reason: str) -> str:
        """Suggest next action based on error + reason.

        Per CONTEXT.md specifics: heuristics for common failure modes.

        Args:
            last_error: Error message from verifier
            reason: Escalation reason

        Returns:
            Human-readable suggested action
        """
        error_lower = last_error.lower()
        if "kaxerror" in error_lower and "api" in error_lower:
            return (
                "Open System Settings → Privacy & Security → Accessibility "
                "and ensure this app has permission"
            )
        elif "cdp ws closed" in error_lower:
            return "Check internet connection or browser process status"
        elif "timed out" in error_lower:
            return "App may be unresponsive; try again or restart the app"
        elif reason == "circuit_breaker_tripped":
            return "Target element may be in an invalid state; try refreshing the app"
        elif reason == "heal_budget_exceeded":
            return (
                "Too many selector heals detected; app layout may be unstable"
            )
        elif reason == "max_cycles_exhausted":
            return (
                "Action could not be reliably completed after 2 recovery "
                "attempts; please try again"
            )
        else:
            return "Action failed; please try again or check app state"

    def _get_branch_name(self, branch: Any) -> str:
        """Extract branch name from branch instance.

        Args:
            branch: RecoveryBranch instance

        Returns:
            Branch name (e.g. "B1_RESCROLL")
        """
        if hasattr(branch, "name"):
            return branch.name
        return "UNKNOWN_BRANCH"


# Stub for async import compatibility (modules may import this)
import asyncio  # noqa: E402
