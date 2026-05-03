"""Speculative pre-execution — predicts N+1, N+2 READ-ONLY (P22 mitigation).

Per D-10: Speculator predicts next 2 steps in parallel with current step's verifier.
Pydantic type system enforces kind=Literal["READ"] — speculation is READ-only only.

P22 MITIGATION: Mutation gate at orchestrator blocks any speculative MUTATE action
until N is VERIFIED. Type system prevents construction of MUTATE speculations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from basicctrl.state.causal_dag import ActionCanonical, StateGraph

from basicctrl.cognition.schemas import SpeculativeDraft

logger = structlog.get_logger(__name__)


class Speculator:
    """Predict N+1, N+2 steps in parallel (READ-only type gate, P22)."""

    def __init__(self):
        """Initialize speculator with hit-rate tracking."""
        self.hits = 0
        self.misses = 0

    async def predict_n_plus_k(
        self,
        current_action: ActionCanonical,
        current_state: StateGraph,
        step_index: int,
        k: int = 2,
    ) -> list[SpeculativeDraft]:
        """
        D-10: Predict steps N+1, N+2 in parallel with N's verifier.

        Per D-10 + P22: speculation is READ-ONLY only. Type system enforces
        SpeculativeDraft.kind = Literal["READ"] — Pydantic rejects kind="MUTATE".

        Args:
            current_action: The action at step N (just fired, being verified)
            current_state: Current state after N's post-condition
            step_index: Index of current step (N)
            k: How many steps ahead to predict (default 2: N+1, N+2)

        Returns:
            List[SpeculativeDraft]: Predicted next k steps, all kind="READ"

        Raises:
            ValidationError: If any draft attempts kind="MUTATE" (Pydantic enforces)
        """
        drafts: list[SpeculativeDraft] = []

        # Placeholder implementation: generate synthetic READ-only predictions
        # Phase 5 will wire in real Planner.plan_action() calls with lookahead
        for i in range(1, k + 1):
            next_index = step_index + i

            # Create a speculative draft (all READ-only)
            # In Phase 5: call planner with "given state S, what's the next action?"
            draft = SpeculativeDraft(
                action=current_action,  # Placeholder; real: planner's candidate
                kind="READ",  # P22: type-enforced to READ only
                step_index=next_index,
                confidence_estimate=0.60,  # Placeholder; real: planner confidence
            )
            drafts.append(draft)

        logger.info(
            "speculative_predict",
            step_index=step_index,
            predicted_steps=k,
            drafts_created=len(drafts),
        )

        return drafts

    def record_hit(self) -> None:
        """Record a hit: N+1 prediction matched actual N+1."""
        self.hits += 1

    def record_miss(self) -> None:
        """Record a miss: N+1 prediction did not match actual N+1."""
        self.misses += 1

    def hit_rate(self) -> float:
        """Return hit rate (hits / (hits + misses))."""
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total


class SpeculationMutationGate:
    """Runtime gate: blocks speculative MUTATE action until N is VERIFIED."""

    async def check_can_fire(
        self,
        draft: SpeculativeDraft,
        current_verified_step: int,
    ) -> bool:
        """
        Check if speculative draft can fire (mutation gate for P22).

        Args:
            draft: SpeculativeDraft to check
            current_verified_step: Index of the last VERIFIED step

        Returns:
            True if draft can fire; False if blocked by mutation gate

        Rule: If draft.kind="MUTATE", block until draft.step_index <= current_verified_step.
        (In practice, kind=Literal["READ"] prevents MUTATE at type level, so this is
        belt-and-suspenders runtime enforcement.)
        """
        # Type system should prevent kind="MUTATE" entirely
        # This is runtime belt-and-suspenders: reject MUTATE until N verified
        if draft.kind != "READ":
            # P22: should never reach here (type enforced)
            logger.error(
                "speculation_mutation_attempted",
                draft_step=draft.step_index,
                kind=draft.kind,
            )
            return False

        # READ-only drafts can always fire
        return True
