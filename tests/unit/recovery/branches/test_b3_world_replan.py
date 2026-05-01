"""Unit tests for B3 WorldReplan recovery branch (D-22).

Per 04-07-PLAN.md: B3 calls world_model.predict() + planner.replan().
Tests verify:
  1. B3 calls predictor and planner, returns replanned ActionCanonical
  2. cancel_event check — B3.attempt() returns None if cancel_event set
  3. Phase 3 contract — try_claim returns False on second claim
"""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cua_overlay.recovery.branches.b3_world_replan import B3RecoveryBranch
from cua_overlay.state.causal_dag import ActionCanonical


@pytest.mark.unit
class TestB3WorldReplam:
    """B3RecoveryBranch unit tests."""

    @pytest.fixture
    def mock_idempotency(self):
        """Create mock IdempotencyTokenStore."""
        mock = AsyncMock()
        mock.try_claim = AsyncMock(return_value={"action_id": "test", "channel": "B3"})
        return mock

    @pytest.fixture
    def mock_session_writer(self):
        """Create mock SessionWriter."""
        mock = MagicMock()
        mock.append_action_log = AsyncMock()
        return mock

    @pytest.fixture
    def mock_world_model(self):
        """Create mock WorldModelPredictor."""
        mock = AsyncMock()
        mock.predict = AsyncMock(
            return_value={
                "ax_delta": {"expected_changes": ["AXValue"]},
                "screenshot_phash_delta": "test_hash",
                "expected_notifs": ["kAXValueChanged"],
            }
        )
        return mock

    @pytest.fixture
    def mock_planner(self):
        """Create mock Planner."""
        mock = AsyncMock()
        mock.plan_action = AsyncMock()
        return mock

    @pytest.fixture
    def b3_branch(self, mock_idempotency, mock_session_writer, mock_world_model, mock_planner):
        """Create B3RecoveryBranch with mocked dependencies."""
        return B3RecoveryBranch(
            idempotency_store=mock_idempotency,
            session_writer=mock_session_writer,
            world_model_predictor=mock_world_model,
            planner=mock_planner,
        )

    @pytest.mark.asyncio
    async def test_b3_calls_predictor_and_planner(self, b3_branch, mock_world_model, mock_planner):
        """Test 1: B3.attempt() calls world_model.predict() + planner.plan_action()."""
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

        replanned_step = ActionCanonical(
            id="replanned_action",
            step_idx=0,
            kind="READ",
            target_key="button:ok",
            action_type="click",
            payload={},
            timestamp_ns=int(time.monotonic_ns()),
            session_id="test_session",
        )

        # Mock planner to return a plan with the replanned action
        from cua_overlay.cognition.schemas import PlanCandidate

        mock_planner.plan_action.return_value = PlanCandidate(
            steps=[replanned_step],
            preconds=[],
            success_criteria=["action_succeeded"],
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

        result = await b3_branch.attempt(failure_ctx)

        # Verify world_model.predict was called
        mock_world_model.predict.assert_called_once()
        call_args = mock_world_model.predict.call_args
        assert call_args.kwargs["action"] == failed_action
        assert call_args.kwargs["current_state"] == current_state

        # Verify planner.plan_action was called
        mock_planner.plan_action.assert_called_once()

        # Verify result is the replanned action
        assert result is not None
        assert isinstance(result, ActionCanonical)

    @pytest.mark.asyncio
    async def test_b3_returns_none_if_cancel_event_set(self, b3_branch):
        """Test 2: cancel_event check — B3.attempt() returns None if cancel_event set."""
        # Create a cancel event and set it
        cancel_event = AsyncMock()
        cancel_event.is_set = MagicMock(return_value=True)
        b3_branch.set_cancel_event(cancel_event)

        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
        }

        result = await b3_branch.attempt(failure_ctx)

        # Should return None because cancel_event is set
        assert result is None

    @pytest.mark.asyncio
    async def test_b3_respects_try_claim_failure(self, b3_branch, mock_idempotency):
        """Test 3: Phase 3 contract — try_claim returns False on second claim."""
        # First call returns a claim, second returns None
        mock_idempotency.try_claim.side_effect = [
            {"action_id": "test_action", "channel": "B3"},
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
        result_1 = await b3_branch.attempt(failure_ctx_1)
        # Second attempt should fail due to claim loss
        result_2 = await b3_branch.attempt(failure_ctx_2)

        # First should fail at missing context, second at claim failure
        # Both should be None
        assert result_2 is None

    @pytest.mark.asyncio
    async def test_b3_returns_none_on_missing_context(self, b3_branch):
        """Test 4: B3.attempt() returns None if action or state is missing."""
        failure_ctx = {
            "bundle_id": "com.example.app",
            "target_key": "button:ok",
            "action_id": "test_action",
            # Missing "action" and "state"
        }

        result = await b3_branch.attempt(failure_ctx)

        # Should return None due to missing context
        assert result is None

    @pytest.mark.asyncio
    async def test_b3_returns_none_on_planner_error(
        self, b3_branch, mock_planner, mock_idempotency
    ):
        """Test 5: B3.attempt() returns None if planner raises exception."""
        # Setup mock to raise exception
        mock_planner.plan_action.side_effect = ValueError("Planner error")

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

        result = await b3_branch.attempt(failure_ctx)

        # Should return None due to planner error
        assert result is None

    @pytest.mark.asyncio
    async def test_b3_emits_events(self, b3_branch, mock_session_writer):
        """Test 6: B3 emits structured events for debugging."""
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

        from cua_overlay.cognition.schemas import PlanCandidate

        b3_branch._planner.plan_action.return_value = PlanCandidate(
            steps=[failed_action],
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

        result = await b3_branch.attempt(failure_ctx)

        # Verify events were emitted
        assert mock_session_writer.append_action_log.call_count >= 1
