"""L3 LLM contract + Phase 1 stub.

Per VERIFY-07: L3 LLM fallback (300-800 ms target) — only when ensemble
confidence < 0.30. Phase 1 ships the contract Protocol locked for Phase 4
to implement, plus an ``L3Stub`` that raises ``NotImplementedError`` when
invoked. The Aggregator (Plan 06 Task 3) catches the exception and emits
a structured ``l3.unavailable_phase1`` warning event.

Phase 1 invariant: ANY L3 escalation in Phase 1 is a bug — L0+L1
deterministic ensemble must produce confidence >= 0.50 (VERIFIED) OR
< 0.30 (escalate to L3, which raises). The corridor (0.30, 0.50) is
covered by L2 in Plan 06. The Calculator demo (Plan 09) keeps confidence
above 0.50, so L2/L3 never fire.

Phase 4 will provide implementations using:

* Claude Opus 4 (cloud) — primary planner & verifier
* GPT-5 (cloud, ensemble vote) — disagreement tiebreaker
* V-Droid prefill-only verifier (local fast path) — sub-second
  verification on common interactions

The Protocol is ``@runtime_checkable`` so call-sites can ``isinstance``
test against any conforming object — useful for Phase 4 swapping at
runtime based on configured backend.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from basicctrl.state.causal_dag import HoarePost


@runtime_checkable
class L3Contract(Protocol):
    """LLM verifier contract — Phase 4 implements; Phase 1 stubs.

    Phase 4 will provide implementations using:

    * Claude Opus 4 (cloud) — primary planner & verifier
    * GPT-5 (cloud, ensemble vote) — disagreement tiebreaker
    * V-Droid prefill-only verifier (local fast path) — sub-second
      verification on common interactions

    The signature mirrors the Phase 4 expected interface so the swap is
    a one-line aggregator constructor change. Decoupling via ``Protocol``
    means any object with a matching ``async def verify(...) -> tuple[float, str]``
    satisfies the contract — duck typing with type-checker support.
    """

    async def verify(
        self,
        screenshot: Optional[bytes],
        expected: HoarePost,
        actual_signals: dict[str, float],
    ) -> tuple[float, str]:
        """Returns ``(confidence, reasoning)``. Confidence in [0.0, 1.0]."""
        ...


class L3Stub:
    """Phase 1: must NEVER be called. If reached, throws.

    The Calculator demo (Plan 09) asserts this stub is never invoked.
    If it is, that's a bug: L0+L1+L2 deterministic ensemble should
    produce confidence >= 0.50 OR < 0.30 (escalate). Phase 1's invariant
    is "stay above 0.50" for the demo target.

    Phase 4 swaps in a real implementation — until then, the aggregator
    catches NotImplementedError gracefully and emits a structured
    'l3.unavailable_phase1' warning event so the operator can diagnose.
    """

    async def verify(self, *args: object, **kwargs: object) -> tuple[float, str]:
        """Catch-all signature — ANY positional/keyword args raise.

        Phase 4 will replace this with a strict signature matching
        ``L3Contract.verify``. Until then, the catch-all ensures any
        accidental Phase 1 invocation surfaces immediately rather than
        silently proceeding with a fabricated confidence value.
        """
        raise NotImplementedError(
            "L3 LLM verifier is Phase 4 — Phase 1 should never reach this path. "
            "L0+L1+L2 deterministic ensemble must produce confidence >= 0.50 OR < 0.30; "
            "anything in (0.30, 0.50) means tune the WeightedVote table."
        )
