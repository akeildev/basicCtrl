"""Unit tests for basicctrl.ax.rate_limit.TokenBucket.

Pitfall P2 (cmux #2985) mitigation: token bucket caps AX calls at 20/sec/pid.
Tests verify hard cap, per-pid isolation, refill rate, fail-open semantics, and
structured logging on deny.
"""
from __future__ import annotations

import asyncio

import pytest
import structlog

from basicctrl.ax.rate_limit import TokenBucket


@pytest.mark.asyncio
async def test_initial_burst_grants_20() -> None:
    """A fresh bucket grants exactly ``capacity`` tokens with no refill help."""
    bucket = TokenBucket(rate_per_sec=20.0, capacity=20)
    granted = 0
    for _ in range(20):
        if await bucket.acquire(pid=42):
            granted += 1
    assert granted == 20


@pytest.mark.asyncio
async def test_21st_call_in_first_second_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """The 21st call within the same second returns False.

    We freeze ``time.monotonic`` so refill cannot mask the cap.
    """
    import basicctrl.ax.rate_limit as rl

    frozen = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: frozen[0])

    bucket = TokenBucket(rate_per_sec=20.0, capacity=20)
    for _ in range(20):
        assert await bucket.acquire(pid=42) is True
    # 21st call same instant: bucket is empty, no refill.
    assert await bucket.acquire(pid=42) is False


@pytest.mark.asyncio
async def test_per_pid_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Depleting pid=1's bucket does not affect pid=2."""
    import basicctrl.ax.rate_limit as rl

    frozen = [2000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: frozen[0])

    bucket = TokenBucket(rate_per_sec=20.0, capacity=20)
    # Drain pid=1.
    for _ in range(20):
        assert await bucket.acquire(pid=1) is True
    assert await bucket.acquire(pid=1) is False

    # pid=2 still has a fresh bucket.
    for _ in range(20):
        assert await bucket.acquire(pid=2) is True
    assert await bucket.acquire(pid=2) is False


@pytest.mark.asyncio
async def test_refills_at_20_per_sec(monkeypatch: pytest.MonkeyPatch) -> None:
    """After draining, advancing the clock by 0.5s allows ~10 more grants."""
    import basicctrl.ax.rate_limit as rl

    frozen = [3000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: frozen[0])

    bucket = TokenBucket(rate_per_sec=20.0, capacity=20)
    for _ in range(20):
        assert await bucket.acquire(pid=42) is True
    assert await bucket.acquire(pid=42) is False

    # Advance 0.5s — 10 tokens should have refilled.
    frozen[0] += 0.5
    granted = 0
    for _ in range(15):
        if await bucket.acquire(pid=42):
            granted += 1
    # Allow tiny floating-point fuzz: expect exactly 10.
    assert granted == 10


@pytest.mark.asyncio
async def test_emits_structlog_event_on_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """When acquire() returns False, ``ax.rate_limited`` event is emitted with pid."""
    import basicctrl.ax.rate_limit as rl

    frozen = [4000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: frozen[0])

    bucket = TokenBucket(rate_per_sec=20.0, capacity=20)
    for _ in range(20):
        await bucket.acquire(pid=99)

    with structlog.testing.capture_logs() as captured:
        result = await bucket.acquire(pid=99)
    assert result is False
    assert any(
        e.get("event") == "ax.rate_limited" and e.get("pid") == 99
        for e in captured
    )


@pytest.mark.asyncio
async def test_no_blocking_when_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    """acquire() returns False quickly — does not block, does not raise."""
    import basicctrl.ax.rate_limit as rl

    frozen = [5000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: frozen[0])

    bucket = TokenBucket(rate_per_sec=20.0, capacity=20)
    for _ in range(20):
        await bucket.acquire(pid=7)

    # Should resolve fast; wait_for with tight budget proves non-blocking.
    result = await asyncio.wait_for(bucket.acquire(pid=7), timeout=0.05)
    assert result is False
