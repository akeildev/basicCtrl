"""Fixtures for recovery unit tests.

All fixtures mock Phase 1/2 dependencies to allow recovery tests to run
without full integration setup.
"""
from __future__ import annotations

from typing import Any, Callable, TypedDict
from unittest.mock import AsyncMock

import pytest


class FailureCtxDict(TypedDict):
    """Type definition for failure context (placeholder until FailureCtx defined)."""

    bundle_id: str
    target_key: str
    failure_class: str
    confidence: float
    last_error: str


@pytest.fixture
def failure_ctx_factory() -> Callable[[str, str, str, float, str], FailureCtxDict]:
    """Factory fixture that builds FailureCtx dicts for testing.

    Parameters:
      - bundle_id: app bundle identifier
      - target_key: composite key from Phase 1
      - failure_class: enum name (default PERCEPTUAL)
      - confidence: verifier confidence 0-1 (default 0.3)
      - last_error: error message (default "test error")

    Returns: dict matching FailureCtx contract.
    """

    def _build(
        bundle_id: str = "com.test.app",
        target_key: str = "test_target",
        failure_class: str = "PERCEPTUAL",
        confidence: float = 0.3,
        last_error: str = "test error",
    ) -> FailureCtxDict:
        return {
            "bundle_id": bundle_id,
            "target_key": target_key,
            "failure_class": failure_class,
            "confidence": confidence,
            "last_error": last_error,
        }

    return _build


@pytest.fixture
def verifier_mock() -> AsyncMock:
    """AsyncMock for Aggregator.verify.

    Returns HoarePost with verified=False by default (simulates failure).
    Tests can configure: verifier_mock.return_value = HoarePost(verified=True, ...)
    """
    mock = AsyncMock()
    mock.return_value = None  # Will be configured per-test
    return mock


@pytest.fixture
def session_writer_mock() -> AsyncMock:
    """AsyncMock for SessionWriter.append_action_log.

    Tests can assert calls: session_writer_mock.append_action_log.assert_called
    """
    mock = AsyncMock()
    mock.append_action_log = AsyncMock()
    return mock


@pytest.fixture
def idempotency_store_mock() -> AsyncMock:
    """AsyncMock for IdempotencyTokenStore from Phase 2.

    Tests can configure: idempotency_store_mock.try_claim.return_value = True/False
    """
    mock = AsyncMock()
    mock.try_claim = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def axmgr_mock() -> AsyncMock:
    """AsyncMock for AXObserverManager.expect (Phase 1).

    Default: succeeds with no error.
    """
    mock = AsyncMock()
    mock.expect = AsyncMock(return_value=None)
    return mock
