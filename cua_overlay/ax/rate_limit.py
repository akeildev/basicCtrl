"""Per-pid token bucket — Pitfall P2 (cmux #2985) mitigation.

Hard rule from CLAUDE.md:
    Never poll AX at >20 calls/sec/pid (cmux #2985 stalls Cocoa main thread).

cmux #2985 documents the AX framework saturation point at ~30 calls/sec/pid
on the target app's main thread. We cap at 20/sec/pid leaving headroom; the
P2 prevention rule list (PITFALLS.md) makes this mandatory at the
``AXUIElementWrapper`` entry-point so it's automatic rather than something
each call site has to remember.

Behaviour:

* **Per-pid isolation** — depleting app A's quota does NOT affect app B.
* **Fail-open** — when the bucket is empty, ``acquire`` returns ``False`` (it
  does not block, does not raise). Callers MUST handle ``False`` by serving
  the last-cached value with confidence reduced by 0.2 (P2 prevention rule 5;
  saturating AX is worse than slightly-stale state).
* **Burst tolerance** — capacity equals rate, so a fresh bucket grants 20
  tokens immediately; refill replenishes at ``rate`` tokens/sec linearly.
"""
from __future__ import annotations

import asyncio
import time

import structlog


class TokenBucket:
    """Asyncio-safe per-pid token bucket.

    ``rate_per_sec`` is the steady-state grant rate; ``capacity`` is the burst
    size. The Phase-1 default of (20, 20) keeps us safely under the 30/sec
    cmux #2985 saturation point.
    """

    def __init__(self, rate_per_sec: float = 20.0, capacity: int = 20) -> None:
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens: dict[int, float] = {}
        self.last_refill: dict[int, float] = {}
        self._lock = asyncio.Lock()
        self._log = structlog.get_logger()

    async def acquire(self, pid: int) -> bool:
        """Take one token for ``pid``.

        Returns ``True`` if a token was granted; ``False`` if the bucket is
        empty for this pid. Never blocks longer than the lock acquisition; the
        fail-open contract means callers handle ``False`` themselves.

        On deny, emits a structured ``ax.rate_limited`` event with the pid so
        the action log shows where rate limiting actually fired.
        """
        async with self._lock:
            now = time.monotonic()
            if pid not in self.tokens:
                # First call for this pid — start full.
                self.tokens[pid] = float(self.capacity)
                self.last_refill[pid] = now
            else:
                elapsed = now - self.last_refill[pid]
                self.tokens[pid] = min(
                    float(self.capacity),
                    self.tokens[pid] + elapsed * self.rate,
                )
                self.last_refill[pid] = now

            if self.tokens[pid] >= 1.0:
                self.tokens[pid] -= 1.0
                return True

            # Fail-open per Pitfall P2 prevention rule 5: caller falls to cache.
            self._log.warning(
                "ax.rate_limited",
                pid=pid,
                rate=self.rate,
                capacity=self.capacity,
            )
            return False
