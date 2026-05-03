"""Unit tests for Planner agent (D-03, D-20).

Per D-03: Opus 4.x with prompt caching.
Per D-20: Query episodic memory BEFORE LLM call.
Per D-07: WorldModelPredictor heuristic predictions.
"""
import pytest

pytest.importorskip("basicctrl.cognition.planner")

import json
from unittest.mock import AsyncMock, MagicMock, patch

from basicctrl.cognition.planner import Planner, WorldModelPredictor
from basicctrl.cognition.schemas import PlanCandidate
from basicctrl.state.causal_dag import ActionCanonical


@pytest.mark.unit
class TestPlanner:
    """Planner (D-03, D-20) tests."""

    @pytest.fixture
    def planner(self):
        """Create planner with mocked API key."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            return Planner(api_key="test-key")

    @pytest.mark.asyncio
    async def test_plan_action_returns_plan_candidate(self, planner):
        """Test 1: plan_action() returns PlanCandidate with steps + preconds."""
        # Mock the Opus response with simple dict-based steps
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "steps": ["step1_placeholder", "step2_placeholder"],
                        "preconds": ["precond1"],
                        "success_criteria": ["target was clicked"],
                    }
                )
            )
        ]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        planner.client = mock_client
        planner._client_initialized = True

        plan = await planner.plan_action(
            task_description="Click the button",
            current_state=MagicMock(),
        )

        assert isinstance(plan, PlanCandidate)
        assert len(plan.steps) > 0
        assert plan.bounded is True

    @pytest.mark.asyncio
    async def test_episodic_lookup_before_llm(self, planner):
        """Test 2: Episodic lookup called BEFORE LLM (D-20)."""
        # Create mock episodic with a hit
        mock_episodic = AsyncMock()
        mock_hit = MagicMock()
        mock_hit.similarity = 0.95
        mock_hit.recipe = MagicMock(
            steps=[],
            preconditions=[],
            success_criteria=[],
        )
        mock_episodic.lookup.return_value = [mock_hit]

        planner.episodic = mock_episodic

        # Create mock query
        mock_query = MagicMock()

        # Plan action with episodic query
        plan = await planner.plan_action(
            task_description="Click the button",
            current_state=MagicMock(),
            episodic_query=mock_query,
        )

        # Verify episodic was called BEFORE any LLM setup
        mock_episodic.lookup.assert_called_once_with(mock_query)
        assert isinstance(plan, PlanCandidate)
        assert plan.bounded is True

    @pytest.mark.asyncio
    async def test_bounded_generation_max_steps(self, planner):
        """Test 3: PlanCandidate.steps length <= max_steps (20)."""
        # Mock response with 30 steps
        mock_response = MagicMock()
        steps_data = [f"step-{i}" for i in range(30)]
        mock_response.content = [
            MagicMock(
                text=json.dumps(
                    {
                        "steps": steps_data,
                        "preconds": [],
                        "success_criteria": [],
                    }
                )
            )
        ]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        planner.client = mock_client
        planner._client_initialized = True

        plan = await planner.plan_action(
            task_description="Task",
            current_state=MagicMock(),
        )

        # Should be truncated to max_steps=20
        assert len(plan.steps) <= planner.max_steps
        assert len(plan.steps) <= 20

    @pytest.mark.asyncio
    async def test_prompt_caching_enabled(self, planner):
        """Test 4: Prompt caching enabled (cache_control header)."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"steps": [], "preconds": [], "success_criteria": []}')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        planner.client = mock_client
        planner._client_initialized = True

        await planner.plan_action(
            task_description="Task",
            current_state=MagicMock(),
        )

        # Verify cache_control was in the call
        call_args = mock_client.messages.create.call_args
        system_arg = call_args[1]["system"]
        assert isinstance(system_arg, list)
        assert any(
            "cache_control" in item and item["cache_control"].get("type") == "ephemeral"
            for item in system_arg
        )


@pytest.mark.unit
class TestWorldModelPredictor:
    """WorldModelPredictor (D-07) tests."""

    @pytest.fixture
    def predictor(self):
        """Create predictor with mocked API key."""
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            return WorldModelPredictor(api_key="test-key")

    @pytest.mark.asyncio
    async def test_predict_returns_predicted_state(self, predictor):
        """Test 1: predict() returns dict with ax_delta + phash_delta + notifs."""
        mock_action = MagicMock()
        mock_action.action_type = "click"
        mock_state = MagicMock()

        result = await predictor.predict(
            action=mock_action,
            current_state=mock_state,
        )

        assert isinstance(result, dict)
        assert "ax_delta" in result
        assert "screenshot_phash_delta" in result
        assert "expected_notifs" in result

    @pytest.mark.asyncio
    async def test_predict_on_click_heuristic(self, predictor):
        """Test 2: predict() on click action predicts reasonable delta."""
        mock_action = MagicMock()
        mock_action.action_type = "click"
        mock_state = MagicMock()

        result = await predictor.predict(action=mock_action, current_state=mock_state)

        # Click should predict AXValue + notification changes
        assert "AXValue" in result["ax_delta"].get("expected_changes", [])
        assert "kAXValueChanged" in result["expected_notifs"]
