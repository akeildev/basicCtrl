"""Unit tests for VerifierLLM agent (D-06).

Per D-06: V-Droid pattern, prefill-only, prefix-cached.
"""
import pytest

pytest.importorskip("cua_overlay.cognition.verifier_llm")

from unittest.mock import AsyncMock, MagicMock, patch

from cua_overlay.cognition.verifier_llm import VerifierLLM


@pytest.mark.unit
class TestVerifierLLM:
    """VerifierLLM (D-06, V-Droid) tests."""

    @pytest.fixture
    def verifier(self):
        """Create verifier with mocked API key."""
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            return VerifierLLM(api_key="test-key")

    @pytest.mark.asyncio
    async def test_verify_returns_bool_and_confidence(self, verifier):
        """Test 1: verify() returns (bool, float) tuple."""
        mock_action = MagicMock()
        mock_action.action_type = "click"
        mock_pre_state = MagicMock()
        mock_post_state = MagicMock()
        mock_hoare_pre = MagicMock()
        mock_hoare_post = MagicMock()

        verified, confidence = await verifier.verify(
            action=mock_action,
            pre_state=mock_pre_state,
            post_state=mock_post_state,
            hoare_pre=mock_hoare_pre,
            hoare_post=mock_hoare_post,
        )

        assert isinstance(verified, bool)
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    @pytest.mark.asyncio
    async def test_verify_expected_triple_high_confidence(self, verifier):
        """Test 2: verify() on expected Hoare triple returns high confidence."""
        mock_action = MagicMock()
        mock_action.action_type = "click"
        mock_pre_state = MagicMock()
        mock_post_state = MagicMock()
        mock_hoare_pre = MagicMock()
        mock_hoare_post = MagicMock()

        verified, confidence = await verifier.verify(
            action=mock_action,
            pre_state=mock_pre_state,
            post_state=mock_post_state,
            hoare_pre=mock_hoare_pre,
            hoare_post=mock_hoare_post,
        )

        # Phase 4 stub returns True, 0.85
        assert verified is True
        assert confidence >= 0.8

    @pytest.mark.asyncio
    async def test_batching_groups_multiple_verifications(self, verifier):
        """Test 3: Multiple verify() calls queued for batching."""
        # Queue 5 verifications
        for i in range(5):
            mock_action = MagicMock()
            mock_action.action_type = f"action_{i}"
            await verifier.verify(
                action=mock_action,
                pre_state=MagicMock(),
                post_state=MagicMock(),
                hoare_pre=MagicMock(),
                hoare_post=MagicMock(),
            )

        # After flush, pending should be empty
        assert len(verifier._pending_verifications) == 0

    @pytest.mark.asyncio
    async def test_batch_size_triggers_flush(self, verifier):
        """Test 4: Batch size limit triggers automatic flush."""
        # Create verifier with small batch size
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            small_verifier = VerifierLLM(api_key="test-key", batch_size=3)

        # Mock client
        small_verifier.client = AsyncMock()
        small_verifier._client_initialized = True

        # Queue 3 verifications (should trigger flush on 3rd)
        for i in range(3):
            mock_action = MagicMock()
            mock_action.action_type = f"action_{i}"
            await small_verifier.verify(
                action=mock_action,
                pre_state=MagicMock(),
                post_state=MagicMock(),
                hoare_pre=MagicMock(),
                hoare_post=MagicMock(),
            )

        # After reaching batch_size, pending should be flushed
        assert len(small_verifier._pending_verifications) == 0

    @pytest.mark.asyncio
    async def test_prefix_caching_system_prompt(self, verifier):
        """Test 5: System prompt built for prefix caching."""
        system_prompt = verifier._build_system_prompt()

        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 0
        assert "deterministic" in system_prompt.lower()
        assert "Hoare" in system_prompt

    @pytest.mark.asyncio
    async def test_batch_prompt_construction(self, verifier):
        """Test 6: Batch prompt built from multiple verifications."""
        verifications = [
            {
                "action": MagicMock(action_type="click", target_key="btn-1"),
                "hoare_pre": MagicMock(target_exists=True, target_enabled=True),
                "hoare_post": MagicMock(confidence=0.9, verified=True),
            }
            for _ in range(3)
        ]

        batch_prompt = verifier._build_batch_prompt(verifications)

        assert isinstance(batch_prompt, str)
        assert "Verification 1:" in batch_prompt
        assert "Verification 3:" in batch_prompt
        assert "JSON" in batch_prompt
