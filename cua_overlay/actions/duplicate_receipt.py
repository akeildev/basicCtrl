"""ACT-03 / D-19 — 2-second post-fire duplicate receipt ring buffer.

Verifier-side de-dup: a second post on the same (target_axid, action_kind)
within 2 seconds is logged as `near_miss_duplicate` and dropped at the
verifier (the OS-level event already happened; we just don't double-count
it as a state delta).

Per CONTEXT.md D-19. Per RESEARCH.md §"Idempotency receipts".

This is a CYA layer — the primary defense is the IdempotencyTokenStore
(Plan 02-02 Task 1). DuplicateReceipt catches the case where two channels
both delivered to the OS within the ~50µs uncancellable window AND the
verifier somehow saw both events.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, NamedTuple

import structlog


# D-19: 2-second window for considering two posts on the same target+kind
# a near-miss duplicate.
_RING_WINDOW_NS: int = 2_000_000_000


class _Receipt(NamedTuple):
    target_axid: str
    action_kind: str
    ts_ns: int


class DuplicateReceipt:
    """Sliding 2s ring buffer of (target_axid, action_kind, ts_ns) entries.

    record() returns is_duplicate=True iff a matching entry exists with
    ts within 2s. Entries older than 2s are pruned on every call (no GC
    needed; deque popleft is O(1)).
    """

    def __init__(self) -> None:
        self._buffer: Deque[_Receipt] = deque()
        self._log = structlog.get_logger()

    def record(self, target_axid: str, action_kind: str, ts_ns: int) -> bool:
        """Record a post-fire receipt. Return True iff this is a near-miss
        duplicate of one already in the 2s window.

        Always appends the new receipt (even if duplicate) so re-prune of
        the window catches future duplicates within their own 2s.
        """
        # Prune old entries (anything older than ts_ns - 2s).
        cutoff = ts_ns - _RING_WINDOW_NS
        while self._buffer and self._buffer[0].ts_ns < cutoff:
            self._buffer.popleft()

        # Check for a matching live entry (same target + same kind).
        is_duplicate = any(
            r.target_axid == target_axid and r.action_kind == action_kind
            for r in self._buffer
        )

        # Always append the new receipt for forward duplicate detection.
        self._buffer.append(
            _Receipt(target_axid=target_axid, action_kind=action_kind, ts_ns=ts_ns)
        )

        if is_duplicate:
            self._log.warning(
                "near_miss_duplicate",
                target_axid=target_axid,
                action_kind=action_kind,
                ts_ns=ts_ns,
                window_ns=_RING_WINDOW_NS,
            )
        return is_duplicate

    def __len__(self) -> int:
        return len(self._buffer)
