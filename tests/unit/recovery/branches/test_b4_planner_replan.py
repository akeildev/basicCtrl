"""Unit tests for B4 PlannerReplan recovery branch (D-23).

Per 04-07-PLAN.md: B4 calls planner.plan_action() N times, then
uses Critic.rank_candidates() to pick the best one.

Tests verify:
  1. B4 generates N candidates and ranks them via Critic
  2. cancel_event check — B4.attempt() returns None if cancel_event set
  3. Phase 3 contract — try_claim returns False on second claim
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from cua_overlay.recovery.branches.b4_planner_replan import B4RecoveryBranch
from cua_overlay.state.causal_dag import ActionCanonical


@pytest.mark.unit
class TestB4PlannerReplan:
    """B4RecoveryBranch unit tests."""

    @pytest.fixture
    def mock_idempotency(self):
        """Create mock IdempotencyTokenStore."""
        mock = AsyncMock()
        mock.try_claim = AsyncMock(return_value={"action_id": "test", "channel": "B4"})
        return mock

    @pytest.fixture
    def mock_session_writer(self):
        """Create mock SessionWriter."""
        mock = MagicMock()
        mock.append_action_log = AsyncMock()
        return mock

    @pytest.fixture
    def mock_planner(self):
        """Create mock Planner."""
        mock = AsyncMock()
        mock.plan_action = AsyncMock()
        return mock

    @pytest.fixture
    def mock_critic(self):
        """Create mock Critic."""
        mock = AsyncMock()
        mock.rank_candidates = AsyncMock()
        return mock

    @pytest.fixture
    def b4_branch(self, mock_idempotency, mock_session_writer, mock_planner, mock_critic):
        """Create B4RecoveryBranch with mocked dependencies."""
        return B4RecoveryBranch(
            idempotency_store=mock_idempotency,
            session_writer=mock_session_writer,
            planner=mock_planner,
            critic=mock_critic,
            num_candidates=3,
        )

    @pytest.mark.asyncio
    async def test_b4_generates_and_ranks_candidates(
        self, b4_branch, mock_planner, mock_critic
    ):
        """Test 1: B4.attempt() generates N candidates + Critic ranks them."""
        # Setup mocks
        failed_action = ActionCanonical(
            id="test_action",
            step_idx=0,
            kind="READ",
            target_key="button:ok",
            action_type="click",
            payload={},
            timestamp_ns=int(time.monotonic_ns()),
            session_id="test_session",
        )

        current_state = MagicMock()
        current_state.app = "com.example.app"

        # Create 3 candidate actions
        candidates = []
        for i in range(3):
            candidate = ActionCanonical(
                id=f"candidate_{i}",
                step_idx=0,
                kind="READ",
                target_key="button:ok",
                action_type="click",
                payload={},
                timestamp_ns=int(time.monotonic_ns()),
                session_id="test_session",
            )
            candidates.append(candidate)

        # Mock planner to return plans with different actions
        from cua_overlay.cognition.schemas import PlanCandidate

        plan_responses = [
            PlanCandidate(
                steps=[candidates[0]],
                preconds=[],
                success_criteria=[],
                bounded=True,
            ),
            PlanCandidate(
                steps=[candidates[1]],
                preconds=[],
                success_criteria=[],
                bounded=True,
            ),
            PlanCandidate(
                steps=[candidates[2]],
                preconds=[],
                success_criteria=[],
                bounded=True,
            ),
        ]

        mock_planner.plan_action.side_effect = plan_responses

        # Mock critic to return the first candidate as best
        mock_critic.rank_candidates.return_value = (candidates[0], 0.85)

        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
            "action": failed_action,
            "state": current_state,
            "session_id": "test_session",
        }

        result = await b4_branch.attempt(failure_ctx)

        # Verify planner was called N times
        assert mock_planner.plan_action.call_count == 3

        # Verify critic was called once with all candidates
        mock_critic.rank_candidates.assert_called_once()
        call_args = mock_critic.rank_candidates.call_args
        assert call_args.kwargs["criterion"] == "planner_replan"
        assert len(call_args.kwargs["candidates"]) == 3

        # Verify result is the best-ranked candidate
        assert result is not None
        assert isinstance(result, ActionCanonical)

    @pytest.mark.asyncio
    async def test_b4_returns_none_if_cancel_event_set(self, b4_branch):
        """Test 2: cancel_event check — B4.attempt() returns None if cancel_event set."""
        # Create a cancel event and set it
        cancel_event = AsyncMock()
        cancel_event.is_set = MagicMock(return_value=True)
        b4_branch.set_cancel_event(cancel_event)

        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
        }

        result = await b4_branch.attempt(failure_ctx)

        # Should return None because cancel_event is set
        assert result is None

    @pytest.mark.asyncio
    async def test_b4_respects_try_claim_failure(self, b4_branch, mock_idempotency):
        """Test 3: Phase 3 contract — try_claim returns False on second claim."""
        # First call returns a claim, second returns None
        mock_idempotency.try_claim.side_effect = [
            {"action_id": "test_action", "channel": "B4"},
            None,  # Second call fails
        ]

        failure_ctx_1 = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
        }

        failure_ctx_2 = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
        }

        # First attempt should claim
        result_1 = await b4_branch.attempt(failure_ctx_1)
        # Second attempt should fail due to claim loss
        result_2 = await b4_branch.attempt(failure_ctx_2)

        # Both should be None (first at missing context, second at claim failure)
        assert result_2 is None

    @pytest.mark.asyncio
    async def test_b4_returns_none_on_missing_context(self, b4_branch):
        """Test 4: B4.attempt() returns None if action or state is missing."""
        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
            # Missing "action" and "state"
        }

        result = await b4_branch.attempt(failure_ctx)

        # Should return None due to missing context
        assert result is None

    @pytest.mark.asyncio
    async def test_b4_returns_none_if_no_candidates_generated(
        self, b4_branch, mock_planner
    ):
        """Test 5: B4.attempt() returns None if planner fails for all candidates."""
        # Mock planner to return empty plans
        from cua_overlay.cognition.schemas import PlanCandidate

        mock_planner.plan_action.side_effect = [
            PlanCandidate(steps=[], preconds=[], success_criteria=[], bounded=True),
            PlanCandidate(steps=[], preconds=[], success_criteria=[], bounded=True),
            PlanCandidate(steps=[], preconds=[], success_criteria=[], bounded=True),
        ]

        failed_action = ActionCanonical(
            id="test_action",
            step_idx=0,
            kind="READ",
            target_key="button:ok",
            action_type="click",
            payload={},
            timestamp_ns=int(time.monotonic_ns()),
            session_id="test_session",
        )

        current_state = MagicMock()

        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
            "action": failed_action,
            "state": current_state,
            "session_id": "test_session",
        }

        result = await b4_branch.attempt(failure_ctx)

        # Should return None because no valid candidates
        assert result is None

    @pytest.mark.asyncio
    async def test_b4_handles_critic_ranking_error(
        self, b4_branch, mock_planner, mock_critic
    ):
        """Test 6: B4.attempt() returns None if Critic ranking fails."""
        # Mock critic to raise exception
        mock_critic.rank_candidates.side_effect = ValueError("Critic error")

        failed_action = ActionCanonical(
            id="test_action",
            step_idx=0,
            kind="READ",
            target_key="button:ok",
            action_type="click",
            payload={},
            timestamp_ns=int(time.monotonic_ns()),
            session_id="test_session",
        )

        current_state = MagicMock()

        # Setup planner to return one valid candidate
        from cua_overlay.cognition.schemas import PlanCandidate

        candidate = ActionCanonical(
            id="candidate_0",
            step_idx=0,
            kind="READ",
            target_key="button:ok",
            action_type="click",
            payload={},
            timestamp_ns=int(time.monotonic_ns()),
            session_id="test_session",
        )

        mock_planner.plan_action.return_value = PlanCandidate(
            steps=[candidate],
            preconds=[],
            success_criteria=[],
            bounded=True,
        )

        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
            "action": failed_action,
            "state": current_state,
            "session_id": "test_session",
        }

        result = await b4_branch.attempt(failure_ctx)

        # Should return None due to critic error
        assert result is None

    @pytest.mark.asyncio
    async def test_b4_emits_events(self, b4_branch, mock_session_writer, mock_planner, mock_critic):
        """Test 7: B4 emits structured events for debugging."""
        failed_action = ActionCanonical(
            id="test_action",
            step_idx=0,
            kind="READ",
            target_key="button:ok",
            action_type="click",
            payload={},
            timestamp_ns=int(time.monotonic_ns()),
            session_id="test_session",
        )

        current_state = MagicMock()

        candidate = ActionCanonical(
            id="candidate_0",
            step_idx=0,
            kind="READ",
            target_key="button:ok",
            action_type="click",
            payload={},
            timestamp_ns=int(time.monotonic_ns()),
            session_id="test_session",
        )

        from cua_overlay.cognition.schemas import PlanCandidate

        mock_planner.plan_action.return_value = PlanCandidate(
            steps=[candidate],
            preconds=[],
            success_criteria=[],
            bounded=True,
        )

        mock_critic.rank_candidates.return_value = (candidate, 0.85)

        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
            "action": failed_action,
            "state": current_state,
            "session_id": "test_session",
        }

        result = await b4_branch.attempt(failure_ctx)

        # Verify events were emitted
        assert mock_session_writer.append_action_log.call_count >= 1
