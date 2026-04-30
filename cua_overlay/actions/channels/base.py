"""Channel Protocol + ChannelOutcome (frozen Pydantic).

Each channel is `async fire(action, target, store, cancel_event) -> ChannelOutcome`.

Per RESEARCH.md §"Pattern 9 Channel Registry Shape":
    1. Try claim via store.try_claim → if lost, return status='skipped'
    2. Pre-syscall kill-switch via cancel_event.is_set() → if cancelled, return status='cancelled'
    3. Fire syscall (the ~50µs uncancellable kernel window for C1/C3)
    4. Return ChannelOutcome(status='fired', fired_at_ns=now)

Verifier signal in outcome.verified is set by the orchestrator AFTER the
verifier ladder runs, NOT by the channel itself (channels don't trust
their own success bit; they trust the verifier).
"""
from __future__ import annotations

from typing import Literal, Optional, Protocol, runtime_checkable

import anyio
from pydantic import BaseModel, ConfigDict

from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TranslatorTarget


class ChannelOutcome(BaseModel):
    """Per-channel fire outcome. Frozen — channels return new instances rather
    than mutating (T-2-06 / T-2-08 race-cancel correctness)."""

    model_config = ConfigDict(frozen=True)

    channel: Literal["C1", "C2", "C3", "C4", "C5"]
    status: Literal["fired", "skipped", "cancelled", "errored"]
    fired_at_ns: Optional[int] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
    # `verified` is set by orchestrator post-verifier; channels never set it.
    verified: bool = False


@runtime_checkable
class Channel(Protocol):
    """Channel Protocol. C1..C5 implement this; race orchestrator fans out."""

    name: Literal["C1", "C2", "C3", "C4", "C5"]

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        """Fire the action via this channel.

        MUST: try_claim BEFORE syscall; check cancel_event.is_set() BEFORE syscall;
        return frozen ChannelOutcome with status reflecting actual delivery.
        MUST NOT: call the verifier; set outcome.verified; mutate caller state.
        """
        ...
