"""Tests for circuit breaker.

Covers trip logic, translator priority reordering, event emission,
60s window reset, and target independence.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from basicctrl.recovery.circuit_breaker import CircuitBreaker, BreakState
from basicctrl.profile.classifier import AppProfile


@pytest.fixture
async def circuit_breaker_with_mock_writer() -> CircuitBreaker:
    """Create CircuitBreaker with mocked SessionWriter."""
    mock_writer = AsyncMock()
    mock_writer.append_action_log = AsyncMock()
    return CircuitBreaker(session_writer=mock_writer)


@pytest.fixture
async def circuit_breaker() -> CircuitBreaker:
    """Create CircuitBreaker without SessionWriter (for simple tests)."""
    return CircuitBreaker(session_writer=None)


@pytest.fixture
def mock_app_profile() -> AppProfile:
    """Create a mock AppProfile with translator_priority."""
    return AppProfile(
        bundle_id="com.test.app",
        translator_priority=["T1", "T2", "T4", "T5"],
        probed_at=datetime.utcnow(),
        probe_latency_ms=100,
    )


async def test_circuit_breaker_is_not_tripped_on_first_two_failures(
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test that is_tripped returns False after 1-2 failures."""
    bundle_id = "com.test.app"
    target_key = "target1"

    # Record first failure
    result = await circuit_breaker.record_failure(bundle_id, target_key, None)
    assert result is False
    assert await circuit_breaker.is_tripped(bundle_id, target_key) is False

    # Record second failure
    result = await circuit_breaker.record_failure(bundle_id, target_key, None)
    assert result is False
    assert await circuit_breaker.is_tripped(bundle_id, target_key) is False


async def test_circuit_breaker_trips_on_third_failure(
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test that circuit breaker trips on 3rd consecutive failure."""
    bundle_id = "com.test.app"
    target_key = "target1"

    # Record failures 1 and 2
    await circuit_breaker.record_failure(bundle_id, target_key, None)
    await circuit_breaker.record_failure(bundle_id, target_key, None)

    # Record 3rd failure — should trip
    result = await circuit_breaker.record_failure(bundle_id, target_key, None)
    assert result is True
    assert await circuit_breaker.is_tripped(bundle_id, target_key) is True


async def test_circuit_breaker_reorders_translator_priority(
    circuit_breaker: CircuitBreaker, mock_app_profile: AppProfile
) -> None:
    """Test that tripping reorders translator_priority."""
    bundle_id = "com.test.app"
    target_key = "target1"

    # Verify initial priority
    assert mock_app_profile.translator_priority == ["T1", "T2", "T4", "T5"]

    # Record 3 failures — on 3rd, should reorder
    await circuit_breaker.record_failure(bundle_id, target_key, None)
    await circuit_breaker.record_failure(bundle_id, target_key, None)
    await circuit_breaker.record_failure(bundle_id, target_key, mock_app_profile)

    # Verify T1 was moved to end
    assert mock_app_profile.translator_priority == ["T2", "T4", "T5", "T1"]


async def test_circuit_breaker_emits_trip_event(
    circuit_breaker_with_mock_writer: CircuitBreaker,
) -> None:
    """Test that trip emits circuit_breaker_tripped event."""
    bundle_id = "com.test.app"
    target_key = "target1"

    # Record 3 failures
    await circuit_breaker_with_mock_writer.record_failure(bundle_id, target_key, None)
    await circuit_breaker_with_mock_writer.record_failure(bundle_id, target_key, None)
    await circuit_breaker_with_mock_writer.record_failure(bundle_id, target_key, None)

    # Verify append_action_log was called with trip event
    calls = circuit_breaker_with_mock_writer._session_writer.append_action_log.call_args_list
    assert len(calls) == 1
    event = calls[0][0][0]
    assert event["event"] == "circuit_breaker_tripped"
    assert event["bundle_id"] == bundle_id
    assert event["target_key"] == target_key
    assert event["failure_count"] == 3


async def test_circuit_breaker_resets_after_60s(
    circuit_breaker: CircuitBreaker, monkeypatch
) -> None:
    """Test that 60s window resets the failure count."""
    bundle_id = "com.test.app"
    target_key = "target1"

    # Record first failure at t=0
    await circuit_breaker.record_failure(bundle_id, target_key, None)
    assert await circuit_breaker.is_tripped(bundle_id, target_key) is False

    # Mock datetime.utcnow() to return 65s later
    original_datetime = datetime
    future_time = datetime.utcnow() + timedelta(seconds=65)

    class MockDatetime:
        @staticmethod
        def utcnow():
            return future_time

    # Patch datetime in circuit_breaker module
    monkeypatch.setattr("basicctrl.recovery.circuit_breaker.datetime", MockDatetime)

    # Record second failure (should reset count to 1)
    result = await circuit_breaker.record_failure(bundle_id, target_key, None)
    assert result is False
    assert await circuit_breaker.is_tripped(bundle_id, target_key) is False


async def test_circuit_breaker_reset_clears_state(
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test manual reset clears breaker state."""
    bundle_id = "com.test.app"
    target_key = "target1"

    # Trip breaker
    await circuit_breaker.record_failure(bundle_id, target_key, None)
    await circuit_breaker.record_failure(bundle_id, target_key, None)
    await circuit_breaker.record_failure(bundle_id, target_key, None)

    assert await circuit_breaker.is_tripped(bundle_id, target_key) is True

    # Reset
    await circuit_breaker.reset(bundle_id, target_key)

    # Verify breaker is no longer tripped
    assert await circuit_breaker.is_tripped(bundle_id, target_key) is False


async def test_circuit_breaker_different_targets_independent(
    circuit_breaker: CircuitBreaker,
) -> None:
    """Test that different targets have independent failure counts."""
    bundle_id = "com.test.app"
    target_a = "target_a"
    target_b = "target_b"

    # Record 2 failures on target A
    await circuit_breaker.record_failure(bundle_id, target_a, None)
    await circuit_breaker.record_failure(bundle_id, target_a, None)

    # Record 1 failure on target B
    await circuit_breaker.record_failure(bundle_id, target_b, None)

    # Verify A not tripped (only 2 failures)
    assert await circuit_breaker.is_tripped(bundle_id, target_a) is False

    # Verify B not tripped (only 1 failure)
    assert await circuit_breaker.is_tripped(bundle_id, target_b) is False

    # Record 3rd failure on A — should trip A only
    result = await circuit_breaker.record_failure(bundle_id, target_a, None)
    assert result is True
    assert await circuit_breaker.is_tripped(bundle_id, target_a) is True
    assert await circuit_breaker.is_tripped(bundle_id, target_b) is False
