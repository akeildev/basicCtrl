# STUB: replaced by Plan 01-03 on merge
"""Token-bucket rate limiter — Wave-2 stub.

This is a Wave-2 import-compatibility stub. Plan 01-03 owns the real
implementation (see plan 01-03 Task 1). The orchestrator will overwrite this
file with Plan 01-03's full implementation via ``-X theirs`` strategy on merge.

This minimal version exists so Plan 01-04 imports succeed; the real bucket
caps at 20/sec/pid with structured logging and asyncio locking.
"""
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Stub TokenBucket. Real impl in Plan 01-03 (see plan 01-03 Task 1)."""

    def __init__(self, rate_per_sec: float = 20.0, capacity: int = 20) -> None:
        self.rate_per_sec = rate_per_sec
        self.capacity = capacity
        self._tokens: dict[int, float] = {}
        self._last_refill: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, pid: int) -> bool:
        """Returns True if a token was granted; False if rate-limited.

        Stub semantics match Plan 01-03's contract closely enough for Plan 01-04
        unit tests to import and call this without crashing.
        """
        async with self._lock:
            now = time.monotonic()
            if pid not in self._tokens:
                self._tokens[pid] = float(self.capacity)
                self._last_refill[pid] = now
            elapsed = now - self._last_refill[pid]
            self._tokens[pid] = min(
                float(self.capacity), self._tokens[pid] + elapsed * self.rate_per_sec
            )
            self._last_refill[pid] = now
            if self._tokens[pid] >= 1.0:
                self._tokens[pid] -= 1.0
                return True
            return False
