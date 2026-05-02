"""Cognition graceful-disable tests (Phase B / F12-adjacent).

Per ULTRAPLAN Phase B1: when an API key is missing, cognition modules must
raise `CognitionDisabledError` (not a generic `ValueError`) so that
`main.py` can catch the specific signal and substitute stub branches.

These tests pin that contract.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from cua_overlay.cognition import (
    CognitionDisabledError,
    Planner,
    VerifierLLM,
    WorldModelPredictor,
)


@pytest.mark.unit
class TestGracefulDisable:
    """Each cognition module raises CognitionDisabledError when its key is unset."""

    def test_planner_raises_cognition_disabled_when_key_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(CognitionDisabledError) as exc:
                Planner()
        assert exc.value.module == "Planner"
        assert "ANTHROPIC_API_KEY" in exc.value.reason

    def test_planner_succeeds_when_key_present(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            p = Planner()
        assert p.api_key == "sk-test"

    def test_world_model_raises_cognition_disabled_when_key_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(CognitionDisabledError) as exc:
                WorldModelPredictor()
        assert exc.value.module == "WorldModelPredictor"
        assert "ANTHROPIC_API_KEY" in exc.value.reason

    def test_world_model_succeeds_when_key_present(self):
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-test"}):
            wmp = WorldModelPredictor()
        assert wmp.api_key == "sk-test"

    def test_verifier_llm_raises_cognition_disabled_when_key_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(CognitionDisabledError) as exc:
                VerifierLLM()
        assert exc.value.module == "VerifierLLM"
        assert "OPENAI_API_KEY" in exc.value.reason

    def test_verifier_llm_succeeds_when_key_present(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}):
            v = VerifierLLM()
        assert v.api_key == "sk-test"

    def test_cognition_disabled_error_is_runtime_error(self):
        """RuntimeError subclass — main.py catches RuntimeError-tree exceptions
        and falls back to stubs."""
        err = CognitionDisabledError(module="X", reason="y")
        assert isinstance(err, RuntimeError)
