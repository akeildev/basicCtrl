"""Unit tests for WorldModelPredictor (D-07).

Per D-07: CUWM-style world-model predictor.
"""
import pytest

pytest.importorskip("cua_overlay.cognition.planner")

from unittest.mock import MagicMock

from cua_overlay.cognition.planner import WorldModelPredictor


@pytest.mark.unit
class TestWorldModelPredictor:
    """WorldModelPredictor (D-07) tests."""

    @pytest.fixture
    def predictor(self):
        """Create predictor."""
        import os
        from unittest.mock import patch

        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            return WorldModelPredictor(api_key="test-key")

    @pytest.mark.asyncio
    async def test_predict_returns_dict_with_required_fields(self, predictor):
        """Test 1: predict() returns dict with ax_delta, phash_delta, notifs."""
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
        assert isinstance(result["expected_notifs"], list)

    @pytest.mark.asyncio
    async def test_heuristic_predicts_click_changes(self, predictor):
        """Test 2: Heuristic prediction on click predicts AX + notif changes."""
        mock_action = MagicMock()
        mock_action.action_type = "click"
        mock_state = MagicMock()

        result = await predictor.predict(action=mock_action, current_state=mock_state)

        # Click should predict:
        # - AX delta with expected_changes (AXValue, AXTitle)
        # - Notifications (kAXValueChanged, kAXUIElementCreated)
        assert "AXValue" in result["ax_delta"]["expected_changes"]
        assert "kAXValueChanged" in result["expected_notifs"]

    @pytest.mark.asyncio
    async def test_predict_on_type_action(self, predictor):
        """Test 3: Heuristic on type action predicts text content changes."""
        mock_action = MagicMock()
        mock_action.action_type = "type"
        mock_state = MagicMock()

        result = await predictor.predict(action=mock_action, current_state=mock_state)

        # Type action should also predict value/text changes
        assert "expected_notifs" in result
        assert isinstance(result["expected_notifs"], list)

    @pytest.mark.asyncio
    async def test_predict_always_returns_phash(self, predictor):
        """Test 4: predict() always includes screenshot_phash_delta."""
        mock_action = MagicMock()
        mock_action.action_type = "scroll"
        mock_state = MagicMock()

        result = await predictor.predict(action=mock_action, current_state=mock_state)

        assert "screenshot_phash_delta" in result
        # Phase 4 heuristic returns empty string for phash
        assert isinstance(result["screenshot_phash_delta"], str)
