"""Tests for ensemble vote aggregator (D-09, P6 Apple FM gating)."""
import pytest
from unittest.mock import Mock

from basicctrl.cognition.ensemble import EnsembleVotingEngine
from basicctrl.cognition.schemas import AppleFMOutput


@pytest.mark.unit
class TestEnsembleVote:
    """Test 3-model ensemble voting."""

    @pytest.fixture
    def engine(self):
        return EnsembleVotingEngine()

    @pytest.fixture
    def mock_state(self):
        return Mock()

    @pytest.fixture
    def mock_opus_action(self):
        action = Mock()
        action.tier = "T1"
        action.target_bbox = (100.0, 200.0, 150.0, 250.0)
        action.confidence = 0.85
        return action

    @pytest.fixture
    def mock_gpt5_action(self):
        action = Mock()
        action.tier = "T1"
        action.target_bbox = (100.0, 200.0, 150.0, 250.0)
        action.confidence = 0.80
        return action

    @pytest.mark.asyncio
    async def test_two_of_three_agree_majority_wins(
        self, engine, mock_opus_action, mock_gpt5_action, mock_state
    ):
        """Test: When 2 of 3 agree on (tier, bbox), action passes with avg confidence."""
        apple_fm = AppleFMOutput(output="T1")

        action, confidence, model = await engine.vote(
            mock_opus_action, mock_gpt5_action, apple_fm, mock_state
        )

        # Opus and GPT-5 agree on T1 + same bbox
        assert confidence > 0.75  # avg of 0.85 and 0.80
        assert model in ["Opus", "GPT-5"]

    @pytest.mark.asyncio
    async def test_all_three_disagree_tiebreaker(
        self, engine, mock_state
    ):
        """Test: All 3 disagree → tiebreaker uses highest confidence."""
        # Opus votes T1 at 0.90
        opus = Mock()
        opus.tier = "T1"
        opus.target_bbox = (100.0, 200.0, 150.0, 250.0)
        opus.confidence = 0.90

        # GPT-5 votes T2 at 0.70
        gpt5 = Mock()
        gpt5.tier = "T2"
        gpt5.target_bbox = (200.0, 300.0, 250.0, 350.0)
        gpt5.confidence = 0.70

        # Apple FM votes T3 at 0.75
        apple_fm = AppleFMOutput(output="T3")

        action, confidence, model = await engine.vote(opus, gpt5, apple_fm, mock_state)

        # Tiebreaker: highest confidence (Opus at 0.90)
        assert confidence == 0.90
        assert model == "Opus"

    @pytest.mark.asyncio
    async def test_apple_fm_enum_validation_invalid_output(
        self, engine, mock_opus_action, mock_gpt5_action, mock_state
    ):
        """Test: Invalid Apple FM enum value rejected (P6 gate)."""
        # AppleFMOutput validation happens at Pydantic level
        with pytest.raises(ValueError, match="Input should be.*T1.*T2"):
            AppleFMOutput(output="T99")

    @pytest.mark.asyncio
    async def test_all_valid_apple_fm_outputs(self, engine, mock_opus_action, mock_gpt5_action, mock_state):
        """Test: All valid Apple FM enum values accepted."""
        valid_outputs = ["T1", "T2", "T3", "T4", "T5", "retry", "escalate", "abort"]

        for output in valid_outputs:
            fm = AppleFMOutput(output=output)
            assert fm.output == output

    @pytest.mark.asyncio
    async def test_apple_fm_none_graceful_fallback(
        self, engine, mock_opus_action, mock_gpt5_action, mock_state
    ):
        """Test: Apple FM unavailable (None) → vote with Opus + GPT-5 only."""
        action, confidence, model = await engine.vote(
            mock_opus_action, mock_gpt5_action, None, mock_state
        )

        # Should still return an action (2-vote system)
        assert action is not None
        assert confidence > 0.0

    @pytest.mark.asyncio
    async def test_tiebreaker_picks_highest_confidence(
        self, engine, mock_state
    ):
        """Test: Tiebreaker rule uses highest-confidence vote."""
        opus = Mock()
        opus.tier = "T1"
        opus.target_bbox = (100.0, 100.0, 150.0, 150.0)
        opus.confidence = 0.60  # Lower

        gpt5 = Mock()
        gpt5.tier = "T2"
        gpt5.target_bbox = (200.0, 200.0, 250.0, 250.0)
        gpt5.confidence = 0.95  # Highest

        apple_fm = AppleFMOutput(output="T3")

        action, confidence, model = await engine.vote(opus, gpt5, apple_fm, mock_state)

        assert confidence == 0.95
        assert model == "GPT-5"

    @pytest.mark.asyncio
    async def test_fm_policy_outputs_do_not_map_to_tier(self, engine, mock_state):
        """Test: Apple FM policy outputs (retry, escalate, abort) don't map to tier."""
        opus = Mock()
        opus.tier = "T1"
        opus.target_bbox = (100.0, 100.0, 150.0, 150.0)
        opus.confidence = 0.85

        gpt5 = Mock()
        gpt5.tier = "T1"
        gpt5.target_bbox = (100.0, 100.0, 150.0, 150.0)
        gpt5.confidence = 0.80

        # FM outputs "retry" (not a tier) → should not participate in tier voting
        apple_fm = AppleFMOutput(output="retry")

        action, confidence, model = await engine.vote(opus, gpt5, apple_fm, mock_state)

        # Opus + GPT-5 agree on T1, both tier and bbox match
        assert confidence > 0.75
        assert model in ["Opus", "GPT-5"]

    @pytest.mark.asyncio
    async def test_average_confidence_on_agreement(self, engine, mock_state):
        """Test: When 2 votes agree, confidence = avg of agreeing votes."""
        opus = Mock()
        opus.tier = "T1"
        opus.target_bbox = (100.0, 100.0, 150.0, 150.0)
        opus.confidence = 0.80

        gpt5 = Mock()
        gpt5.tier = "T1"
        gpt5.target_bbox = (100.0, 100.0, 150.0, 150.0)
        gpt5.confidence = 0.90

        apple_fm = AppleFMOutput(output="T2")

        action, confidence, model = await engine.vote(opus, gpt5, apple_fm, mock_state)

        # Opus + GPT-5 agree, so confidence = (0.80 + 0.90) / 2 = 0.85
        assert confidence == pytest.approx(0.85)
