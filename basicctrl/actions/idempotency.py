"""ACT-03 — atomic idempotency token store (D-16, D-17, D-18).

Authority hierarchy:
    1. self._claims dict — live race authority (in-memory, asyncio.Lock-guarded)
    2. SessionWriter NDJSON action_log — replay/forensics

Claim semantics:
    try_claim returns ChannelClaim if action_id is fresh (atomic claim);
    returns None if already claimed by another channel.

Per CONTEXT.md D-16: dict authoritative for live race; NDJSON for replay.
Per CONTEXT.md D-17: token written BEFORE any channel fires.
Per CONTEXT.md D-18: is_claimed lock-free peek for OS-level pre-syscall kill-switch.
Per RESEARCH.md Pitfall F: first-claimer-wins is correct by design — race
happens at the OS level, not at the Python claim level.
"""
from __future__ import annotations

import asyncio
import time
from typing import Literal, Optional

import structlog
from pydantic import BaseModel, ConfigDict

from cua_overlay.persist.session_writer import SessionWriter


class ChannelClaim(BaseModel):
    """Atomic record of which channel claimed an action_id, when."""

    model_config = ConfigDict(frozen=True)

    action_id: str
    claimed_at_ns: int
    claimed_by_channel: Literal["C1", "C2", "C3", "C4", "C5"]


class IdempotencyTokenStore:
    """Process-local atomic claim store + NDJSON trace.

    Per D-16 the dict is authoritative for live race; the NDJSON sink is for
    Phase 4 cassette replay only. asyncio.Lock guards the whole dict mutation
    (Pitfall F: this is correct — channels race at the OS level, not at the
    Python claim level).

    Per D-17 the claim is written BEFORE any channel fires.
    Per D-18 is_claimed is a lock-free peek so channels can do a cheap
    pre-syscall check without re-acquiring the lock.
    """

    def __init__(self, session_writer: SessionWriter) -> None:
        self._claims: dict[str, ChannelClaim] = {}
        self._lock = asyncio.Lock()
        self._session = session_writer
        self._log = structlog.get_logger()

    async def try_claim(
        self,
        action_id: str,
        channel: Literal["C1", "C2", "C3", "C4", "C5"],
    ) -> Optional[ChannelClaim]:
        """Atomic claim. Returns ChannelClaim on success, None if already claimed.

        Writes claim event to SessionWriter NDJSON inside the lock so the
        ordering is preserved even under concurrent contention.
        """
        async with self._lock:
            existing = self._claims.get(action_id)
            if existing is not None:
                self._log.debug(
                    "idempotency.claim_lost",
                    action_id=action_id,
                    requested_channel=channel,
                    held_by=existing.claimed_by_channel,
                )
                return None
            claim = ChannelClaim(
                action_id=action_id,
                claimed_at_ns=time.monotonic_ns(),
                claimed_by_channel=channel,
            )
            self._claims[action_id] = claim
            self._session.append_action_log(
                {
                    "event": "idempotency_claim",
                    "action_id": action_id,
                    "channel": channel,
                    "claimed_at_ns": claim.claimed_at_ns,
                }
            )
            return claim

    def is_claimed(self, action_id: str) -> Optional[ChannelClaim]:
        """Lock-free peek (D-18). Channels call this immediately before the
        OS syscall so cancellation can trim the ~50µs uncancellable window."""
        return self._claims.get(action_id)
