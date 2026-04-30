"""Unit tests for Apple FM tier-0 classifier (P6, P7 mitigation).

Per PLAN 04-02:
- Test 1: Enum validation passes on valid output
- Test 2: JSON response rejected (P6 hallucination mitigation)
- Test 3: Timeout graceful fallback
- Test 4: Text-only API gate (schema has no pixels field)
"""
import pytest
from unittest import mock

from cua_overlay.cognition.apple_fm import AppleFMClassifier
from cua_overlay.cognition.schemas import AppleFMOutput


def _make_classifier_with_mock(return_value: str) -> tuple:
    """Helper: create classifier and mock _call_apple_fm."""
    classifier = AppleFMClassifier()
    original_call = classifier._call_apple_fm

    def mock_call(prompt: str) -> str:
        return return_value

    classifier._call_apple_fm = mock_call
    return classifier, original_call


class TestAppleFMClassifier:
    """Test Apple FM classifier enum validation + P6/P7 mitigations."""

    @pytest.mark.asyncio
    async def test_enum_validation_passes_on_valid_output(self):
        """Test 1: Enum validation passes on valid output (T1, T2, retry, etc.)."""
        classifier, original = _make_classifier_with_mock("T1")
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            assert result is not None
            assert isinstance(result, AppleFMOutput)
            assert result.output == "T1"
        finally:
            classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_enum_validation_all_valid_values(self):
        """Test all allowed enum values pass validation."""
        valid_outputs = ["T1", "T2", "T3", "T4", "T5", "retry", "escalate", "abort"]

        with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
            for output_val in valid_outputs:
                classifier, original = _make_classifier_with_mock(output_val)
                try:
                    result = await classifier.classify("test", "route_translator")
                    assert result is not None
                    # Expect the enum value as-is (mixed case: T1-T5 uppercase, others lowercase)
                    assert result.output == output_val
                finally:
                    classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_json_response_rejected_p6_mitigation(self):
        """Test 2: JSON response rejected (P6 hallucination marker)."""
        classifier, original = _make_classifier_with_mock('{"translator": "T1", "confidence": 0.95}')
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            # P6 gate should reject JSON
            assert result is None
        finally:
            classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_json_with_quoted_field_rejected(self):
        """Test P6: quoted strings also rejected (alternative JSON marker)."""
        classifier, original = _make_classifier_with_mock('"T1"')
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            assert result is None
        finally:
            classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_invalid_enum_value_rejected(self):
        """Test: Invalid enum value rejected (not in allowed list)."""
        classifier, original = _make_classifier_with_mock("T99")
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            assert result is None
        finally:
            classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_timeout_graceful_fallback(self):
        """Test 3: SDK timeout handled gracefully (returns None, caller falls through)."""
        classifier = AppleFMClassifier()
        original_call = classifier._call_apple_fm

        def mock_call_timeout(prompt: str) -> str:
            raise TimeoutError("Apple FM timed out")

        classifier._call_apple_fm = mock_call_timeout
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            assert result is None
        finally:
            classifier._call_apple_fm = original_call

    @pytest.mark.asyncio
    async def test_sdk_unavailable_returns_none(self):
        """Test: SDK unavailable (ImportError) returns None gracefully."""
        classifier = AppleFMClassifier()

        with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", False):
            result = await classifier.classify("test state", "route_translator")

        assert result is None

    @pytest.mark.asyncio
    async def test_text_only_api_gate_via_schema(self):
        """Test 4: Type-system gate — input has no pixels field (P7).

        AppleFMClassifier.classify() takes state_description: str only.
        No image_bytes parameter. Verification: function signature.
        """
        classifier = AppleFMClassifier()

        # Verify the signature has no pixels/image/bytes parameter
        import inspect
        sig = inspect.signature(classifier.classify)
        params = list(sig.parameters.keys())

        assert "state_description" in params
        assert "decision_context" in params
        # Explicitly verify NO image_bytes or pixels field
        assert "image_bytes" not in params
        assert "pixels" not in params
        assert "screenshot" not in params

    @pytest.mark.asyncio
    async def test_whitespace_handling(self):
        """Test: Leading/trailing whitespace stripped before validation."""
        classifier, original = _make_classifier_with_mock("  T2  \n")
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            assert result is not None
            assert result.output == "T2"
        finally:
            classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_case_insensitive_matching(self):
        """Test: Output matched case-insensitively (enum uppercase)."""
        classifier, original = _make_classifier_with_mock("t3")
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            assert result is not None
            assert result.output == "T3"
        finally:
            classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self):
        """Test: Empty response handled gracefully."""
        classifier, original = _make_classifier_with_mock("")
        try:
            with mock.patch("cua_overlay.cognition.apple_fm.HAS_APPLE_FM", True):
                result = await classifier.classify("test state", "route_translator")
            assert result is None
        finally:
            classifier._call_apple_fm = original

    @pytest.mark.asyncio
    async def test_prompt_construction_respects_token_cap(self):
        """Test: Prompt respects P6 constraint (~500 tokens max)."""
        classifier = AppleFMClassifier()

        # Verify _make_prompt doesn't exceed token budget
        prompt = classifier._make_prompt(
            "short state",
            "route_translator"
        )
        # Count approximate tokens (rough: len(prompt.split()) / 1.3)
        token_count = len(prompt.split()) // 1
        assert token_count < 600  # Budget: ~500 tokens

    def test_prompt_construction_small_enum(self):
        """Test: Prompt construction for different contexts."""
        classifier = AppleFMClassifier()

        prompt = classifier._make_prompt(
            "Modal dialog open",
            "route_translator"
        )
        assert "UI state" in prompt or "state" in prompt
        assert "translator" in prompt.lower() or "route" in prompt.lower()
