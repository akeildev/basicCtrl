"""Tests for recovery orchestrator.

Comprehensive coverage of:
  - Cycle bounds (max 2 cycles before escalation)
  - Branch routing (failure_class → correct branch set)
  - Circuit breaker integration (check before attempt, record after)
  - Heal-rate budget (pause at >5%)
  - Race orchestration (first-verified wins, losers cancelled)
  - Event logging (recovery_log, branch_failed, escalated)
  - Error handling (classifier failure, branch exception)
  - Context updates between cycles (previous_failures_count increment)
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from typing import Optional

import pytest

from basicctrl.recovery.circuit_breaker import CircuitBreaker
from basicctrl.recovery.classifier import FailureClass, FailureClassifier
from basicctrl.recovery.orchestrator import RecoveryOrchestrator
from basicctrl.actions.channels.base import ChannelOutcome


@pytest.fixture
def classifier_mock() -> AsyncMock:
    """Mock FailureClassifier.classify."""
    mock = AsyncMock()
    # Default: return PERCEPTUAL classification
    mock.classify = MagicMock(return_value=(FailureClass.PERCEPTUAL, 75))
    return mock


@pytest.fixture
def circuit_breaker_mock() -> AsyncMock:
    """Mock CircuitBreaker."""
    mock = AsyncMock()
    mock.is_tripped = AsyncMock(return_value=False)
    mock.record_failure = AsyncMock(return_value=False)
    return mock


@pytest.fixture
def branch_mock() -> MagicMock:
    """Factory for creating mock recovery branch instances."""

    def _build(
        name: str = "B1_TEST",
        attempt_return: Optional[ChannelOutcome] = None,
    ) -> MagicMock:
        branch = MagicMock()
        branch.name = name
        branch.attempt = AsyncMock(return_value=attempt_return)
        return branch

    return _build


@pytest.fixture
def session_writer_mock() -> AsyncMock:
    """Mock SessionWriter."""
    mock = AsyncMock()
    mock.append_action_log = AsyncMock()
    return mock


@pytest.fixture
def aggregator_mock() -> AsyncMock:
    """Mock Aggregator."""
    mock = AsyncMock()
    mock.verify = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def orchestrator(
    classifier_mock: AsyncMock,
    circuit_breaker_mock: AsyncMock,
    session_writer_mock: AsyncMock,
    aggregator_mock: AsyncMock,
) -> RecoveryOrchestrator:
    """Create orchestrator with mocked dependencies."""
    return RecoveryOrchestrator(
        classifier=classifier_mock,
        circuit_breaker=circuit_breaker_mock,
        branches_list=[],
        session_writer=session_writer_mock,
        aggregator=aggregator_mock,
        max_cycles=2,
        heal_rate_budget=0.05,
    )


class TestCycleBounds:
    """Tests for bounded cycle loop (max 2 cycles)."""

    @pytest.mark.asyncio
    async def test_recovery_succeeds_on_first_cycle(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test recovery succeeds on first try, returns immediately."""
        # Setup: one branch succeeds
        b1 = branch_mock(name="B1_RESCROLL")
        outcome = ChannelOutcome(
            channel="C2",
            status="fired",
            verified=True,
            fired_at_ns=1000,
        )
        b1.attempt.return_value = outcome

        orchestrator._branches = [b1]

        # Classify returns PERCEPTUAL → routes to [B1, B2, B4]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify
        assert result is not None
        assert result.verified is True
        assert len(recovery_log) > 0
        # Should have recovery_succeeded event
        success_events = [e for e in recovery_log if e.get("event") == "recovery_succeeded"]
        assert len(success_events) == 1
        assert success_events[0]["cycle"] == 1

    @pytest.mark.asyncio
    async def test_recovery_retries_second_cycle(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test recovery retries on cycle 2 and succeeds."""
        # Setup: B1 fails on cycle 1, succeeds on cycle 2
        b1 = branch_mock(name="B1_RESCROLL")

        # Simulate: first call fails (None), second call succeeds
        outcome_success = ChannelOutcome(
            channel="C2",
            status="fired",
            verified=True,
            fired_at_ns=2000,
        )
        b1.attempt.side_effect = [None, outcome_success]

        orchestrator._branches = [b1]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify
        assert result is not None
        assert result.verified is True
        success_events = [e for e in recovery_log if e.get("event") == "recovery_succeeded"]
        assert len(success_events) == 1
        assert success_events[0]["cycle"] == 2

        # Should have attempted B1 twice
        assert b1.attempt.call_count == 2

    @pytest.mark.asyncio
    async def test_recovery_escalates_after_max_cycles(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test recovery escalates to user after 2 failed cycles."""
        # Setup: B1 always fails (returns None)
        b1 = branch_mock(name="B1_RESCROLL")
        b1.attempt.return_value = None

        orchestrator._branches = [b1]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Setup escalate callback
        escalate_callback = AsyncMock()
        orchestrator._escalate_callback = escalate_callback

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify
        assert result is None
        # Should have recovery_exhausted event
        exhausted_events = [
            e for e in recovery_log
            if e.get("event") == "recovery_exhausted"
        ]
        assert len(exhausted_events) == 1
        assert exhausted_events[0]["cycles_tried"] == 2

        # Escalate callback should have been called
        escalate_callback.assert_called_once()


class TestBranchRouting:
    """Tests for failure class → branch routing."""

    @pytest.mark.asyncio
    async def test_classify_perceptual_routes_to_correct_branches(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test PERCEPTUAL class routes to [B1, B2, B4]."""
        from basicctrl.recovery.classifier import FAILURE_CLASS_TO_BRANCHES

        # Setup branches
        b1 = branch_mock(name="B1_RESCROLL")
        b2 = branch_mock(name="B2_OCR_REGROUND")
        b4 = branch_mock(name="B4_PLANNER")

        # All return None so we hit max cycles
        for b in [b1, b2, b4]:
            b.attempt.return_value = None

        orchestrator._branches = [b1, b2, b4]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify: each of the 3 branches should have been called
        assert b1.attempt.call_count > 0
        assert b2.attempt.call_count > 0
        assert b4.attempt.call_count > 0

    @pytest.mark.asyncio
    async def test_classify_actuation_routes_to_correct_branches(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test ACTUATION class routes to [B1, B2, B5]."""
        # Setup branches
        b1 = branch_mock(name="B1_RESCROLL")
        b2 = branch_mock(name="B2_OCR_REGROUND")
        b5 = branch_mock(name="B5_APPLESCRIPT")

        for b in [b1, b2, b5]:
            b.attempt.return_value = None

        orchestrator._branches = [b1, b2, b5]
        classifier_mock.classify.return_value = (
            FailureClass.ACTUATION,
            75,
        )

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify: each of the 3 branches should have been called
        assert b1.attempt.call_count > 0
        assert b2.attempt.call_count > 0
        assert b5.attempt.call_count > 0


class TestCircuitBreaker:
    """Tests for circuit breaker integration."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_tripped_skips_recovery(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test recovery skips when circuit breaker is tripped."""
        # Setup: breaker is tripped
        circuit_breaker_mock.is_tripped.return_value = True

        # Setup escalate callback
        escalate_callback = AsyncMock()
        orchestrator._escalate_callback = escalate_callback

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify
        assert result is None
        breaker_events = [
            e for e in recovery_log
            if e.get("event") == "recovery_skipped_breaker_tripped"
        ]
        assert len(breaker_events) == 1

        # Escalate should be called
        escalate_callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_failure_after_cycle(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test circuit breaker record_failure is called after each failed cycle."""
        # Setup branches
        b1 = branch_mock(name="B1_RESCROLL")
        b1.attempt.return_value = None

        orchestrator._branches = [b1]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        # Create app profile mock
        app_profile_mock = MagicMock()
        app_profile_mock.translator_priority = ["T1", "T2"]

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx, app_profile_mock)

        # Verify: record_failure called twice (once per cycle)
        assert circuit_breaker_mock.record_failure.call_count == 2


class TestHealBudget:
    """Tests for heal-rate budget enforcement."""

    @pytest.mark.asyncio
    async def test_heal_rate_budget_exceeded_pauses_recovery(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        failure_ctx_factory,
    ) -> None:
        """Test recovery pauses when heal budget ratio exceeds threshold."""
        # Setup: set high heal count to trigger budget threshold
        orchestrator._heal_event_count = 100
        orchestrator._total_actions = 1000  # ratio = 10%, exceeds 5% threshold

        # Setup escalate callback
        escalate_callback = AsyncMock()
        orchestrator._escalate_callback = escalate_callback

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify
        assert result is None
        budget_events = [
            e for e in recovery_log
            if e.get("event") == "recovery_skipped_heal_budget_exceeded"
        ]
        assert len(budget_events) == 1
        assert budget_events[0]["heal_ratio"] > 0.05

        # Escalate should be called
        escalate_callback.assert_called_once()


class TestRaceOrchestration:
    """Tests for branch racing and first-verified wins."""

    @pytest.mark.asyncio
    async def test_race_first_complete_first_branch_wins(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test first verified branch wins, others cancelled."""
        # Setup: B1 succeeds, B2/B3 would fail
        b1 = branch_mock(name="B1_RESCROLL")
        outcome1 = ChannelOutcome(
            channel="C2",
            status="fired",
            verified=True,
            fired_at_ns=1000,
        )
        b1.attempt.return_value = outcome1

        b2 = branch_mock(name="B2_OCR_REGROUND")
        b2.attempt.return_value = None

        b3 = branch_mock(name="B3_WORLD_REPLAN")
        b3.attempt.return_value = None

        orchestrator._branches = [b1, b2, b3]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify
        assert result is not None
        assert result.verified is True
        # B1 should have succeeded on first cycle
        success_events = [
            e for e in recovery_log
            if e.get("event") == "recovery_succeeded"
        ]
        assert len(success_events) == 1


class TestEventLogging:
    """Tests for event logging to recovery_log."""

    @pytest.mark.asyncio
    async def test_recovery_events_logged_to_session_writer(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test all recovery events logged via session_writer."""
        b1 = branch_mock(name="B1_RESCROLL")
        b1.attempt.return_value = None

        orchestrator._branches = [b1]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify: session_writer.append_action_log was called
        assert session_writer_mock.append_action_log.call_count > 0

    @pytest.mark.asyncio
    async def test_failed_branches_logged_to_recovery_log(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test failed branches logged with reason."""
        b1 = branch_mock(name="B1_RESCROLL")
        b1.attempt.return_value = None

        orchestrator._branches = [b1]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(
            bundle_id="com.test.app",
            last_error="test error message",
        )

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify: recovery_branch_failed events in log
        failed_events = [
            e for e in recovery_log
            if e.get("event") == "recovery_branch_failed"
        ]
        assert len(failed_events) > 0


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_recovery_handles_classifier_failure(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        failure_ctx_factory,
    ) -> None:
        """Test classifier exception is propagated."""
        # Setup: classifier raises exception
        classifier_mock.classify.side_effect = ValueError("classify error")

        ctx = failure_ctx_factory(bundle_id="com.test.app")

        # Execute — should raise
        with pytest.raises(ValueError, match="classify error"):
            await orchestrator.attempt(ctx)

    @pytest.mark.asyncio
    async def test_recovery_context_updated_between_cycles(
        self,
        orchestrator: RecoveryOrchestrator,
        classifier_mock: AsyncMock,
        circuit_breaker_mock: AsyncMock,
        session_writer_mock: AsyncMock,
        branch_mock,
        failure_ctx_factory,
    ) -> None:
        """Test previous_failures_count incremented between cycles."""
        # Setup: B1 fails on cycle 1, succeeds on cycle 2
        b1 = branch_mock(name="B1_RESCROLL")

        # Track the failure_ctx passed to attempt each time
        called_contexts: list[dict] = []

        async def track_attempt(ctx):
            called_contexts.append(ctx.copy())
            if len(called_contexts) == 1:
                return None  # Fail cycle 1
            # Succeed cycle 2
            return ChannelOutcome(
                channel="C2",
                status="fired",
                verified=True,
            )

        b1.attempt = track_attempt

        orchestrator._branches = [b1]
        classifier_mock.classify.return_value = (
            FailureClass.PERCEPTUAL,
            75,
        )

        ctx = failure_ctx_factory(
            bundle_id="com.test.app",
        )
        ctx["previous_failures_count"] = 0

        # Execute
        result, recovery_log = await orchestrator.attempt(ctx)

        # Verify: context was updated between calls
        assert len(called_contexts) == 2
        assert (
            called_contexts[1].get("previous_failures_count", 0) >
            called_contexts[0].get("previous_failures_count", 0)
        )


class TestHealRateBudgetTracking:
    """Tests for heal-rate budget increment methods."""

    @pytest.mark.asyncio
    async def test_increment_heal_count(self, orchestrator: RecoveryOrchestrator) -> None:
        """Test heal count increment."""
        assert orchestrator._heal_event_count == 0
        await orchestrator.increment_heal_count(3)
        assert orchestrator._heal_event_count == 3

    @pytest.mark.asyncio
    async def test_increment_action_count(
        self, orchestrator: RecoveryOrchestrator
    ) -> None:
        """Test action count increment."""
        assert orchestrator._total_actions == 0
        await orchestrator.increment_action_count(5)
        assert orchestrator._total_actions == 5

    @pytest.mark.asyncio
    async def test_get_heal_ratio(self, orchestrator: RecoveryOrchestrator) -> None:
        """Test heal ratio calculation."""
        # Set counters
        orchestrator._heal_event_count = 5
        orchestrator._total_actions = 100
        ratio = await orchestrator._get_heal_ratio()
        assert ratio == 0.05  # Exactly 5%

        # Zero actions
        orchestrator._total_actions = 0
        ratio = await orchestrator._get_heal_ratio()
        assert ratio == 0.0


class TestEscalation:
    """Tests for escalation to user."""

    @pytest.mark.asyncio
    async def test_escalate_suggests_action_for_common_errors(
        self, orchestrator: RecoveryOrchestrator
    ) -> None:
        """Test suggested action heuristics."""
        # Test AX error
        suggestion = orchestrator._suggest_action_for_error(
            "kAXErrorAPIDisabled", "max_cycles_exhausted"
        )
        assert "Accessibility" in suggestion or "System Settings" in suggestion

        # Test network error
        suggestion = orchestrator._suggest_action_for_error(
            "cdp ws closed", "max_cycles_exhausted"
        )
        assert "internet" in suggestion.lower()

        # Test timeout
        suggestion = orchestrator._suggest_action_for_error(
            "timed out", "max_cycles_exhausted"
        )
        assert "unresponsive" in suggestion.lower()
