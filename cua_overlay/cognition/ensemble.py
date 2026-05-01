"""Ensemble vote aggregator (Opus + GPT-5 + Apple FM).

Per D-09: Three-model voting on action selection. Majority wins; tiebreaker = highest confidence.
Apple FM hard-gated to small-enum only (D-02, P6).

When 2 of 3 agree on (tier, target_bbox), action proceeds with confidence = avg of agreeing votes.
On 3-way disagreement, escalate to user (Critic ranks the 3 candidates; action escalates).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from cua_overlay.state.causal_dag import ActionCanonical, StateGraph

from cua_overlay.cognition.schemas import AppleFMOutput, EnsembleVote

logger = structlog.get_logger(__name__)


class EnsembleVotingEngine:
    """Aggregate 3 model votes on action selection."""

    async def vote(
        self,
        opus_action: ActionCanonical,
        gpt5_action: ActionCanonical,
        apple_fm_output: Optional[AppleFMOutput],
        current_state: StateGraph,
    ) -> tuple[ActionCanonical, float, str]:
        """
        D-09: Aggregate 3 models on action selection.

        Args:
            opus_action: Opus planner's candidate action
            gpt5_action: GPT-5's candidate action
            apple_fm_output: Apple FM classifier output (enum only, or None if unavailable)
            current_state: Current state for context

        Returns:
            (winning_action, confidence, model_name): Selected action, confidence score, model that won

        Behavior:
        - When 2 of 3 agree on (tier, target_bbox): action proceeds, confidence = avg of agreeing votes
        - When all 3 disagree: escalate to user (log event, return highest-confidence candidate)
        """
        # Extract tier and target from Opus and GPT-5 candidates
        opus_tier = opus_action.tier if hasattr(opus_action, "tier") else "T1"
        opus_bbox = opus_action.target_bbox if hasattr(opus_action, "target_bbox") else (0, 0, 0, 0)
        opus_confidence = getattr(opus_action, "confidence", 0.85)

        gpt5_tier = gpt5_action.tier if hasattr(gpt5_action, "tier") else "T1"
        gpt5_bbox = gpt5_action.target_bbox if hasattr(gpt5_action, "target_bbox") else (0, 0, 0, 0)
        gpt5_confidence = getattr(gpt5_action, "confidence", 0.80)

        # Translate Apple FM enum to implied tier
        apple_fm_tier = None
        apple_fm_confidence = 0.75
        if apple_fm_output is not None:
            apple_fm_tier = self._fm_output_to_tier(apple_fm_output.output)

        # Count agreements
        votes = [
            EnsembleVote(
                tier=opus_tier,
                target_bbox=opus_bbox,
                confidence=opus_confidence,
                model="Opus",
            ),
            EnsembleVote(
                tier=gpt5_tier,
                target_bbox=gpt5_bbox,
                confidence=gpt5_confidence,
                model="GPT-5",
            ),
        ]

        if apple_fm_tier is not None:
            votes.append(
                EnsembleVote(
                    tier=apple_fm_tier,
                    target_bbox=(0, 0, 0, 0),  # FM only votes on tier, not target
                    confidence=apple_fm_confidence,
                    model="AppleFM",
                )
            )

        # Check for 2-of-3 agreement on (tier, target_bbox)
        if len(votes) >= 2:
            agreement_map: dict[tuple, list[EnsembleVote]] = {}
            for vote in votes:
                key = (vote.tier, vote.target_bbox)
                if key not in agreement_map:
                    agreement_map[key] = []
                agreement_map[key].append(vote)

            # Check if any (tier, target) has 2+ votes
            for (tier, bbox), agreeing_votes in agreement_map.items():
                if len(agreeing_votes) >= 2:
                    # Majority agreement
                    avg_confidence = sum(v.confidence for v in agreeing_votes) / len(agreeing_votes)
                    winning_model = agreeing_votes[0].model
                    logger.info(
                        "ensemble_vote_majority",
                        tier=tier,
                        agreeing_models=[v.model for v in agreeing_votes],
                        confidence=avg_confidence,
                    )
                    # Return the first agreeing vote's action (we'll reconstruct below)
                    return self._reconstruct_action(
                        opus_action
                        if agreeing_votes[0].model == "Opus"
                        else gpt5_action if agreeing_votes[0].model == "GPT-5"
                        else opus_action,
                        avg_confidence,
                    ), avg_confidence, winning_model

        # 3-way disagreement: use tiebreaker (highest confidence)
        highest_vote = max(votes, key=lambda v: v.confidence)
        logger.warning(
            "ensemble_vote_disagreement",
            all_models=[(v.model, v.tier, v.confidence) for v in votes],
            tiebreaker_model=highest_vote.model,
            tiebreaker_confidence=highest_vote.confidence,
        )

        selected_action = (
            opus_action
            if highest_vote.model == "Opus"
            else gpt5_action if highest_vote.model == "GPT-5"
            else opus_action
        )
        return (
            self._reconstruct_action(selected_action, highest_vote.confidence),
            highest_vote.confidence,
            highest_vote.model,
        )

    def _fm_output_to_tier(self, fm_output: str) -> Optional[str]:
        """Convert Apple FM enum output to translator tier.

        Apple FM outputs: T1, T2, T3, T4, T5 (direct), or retry/escalate/abort (policy).
        """
        if fm_output in ["T1", "T2", "T3", "T4", "T5"]:
            return fm_output
        # Policy outputs don't map to a tier
        return None

    def _reconstruct_action(
        self, action: ActionCanonical, confidence: float
    ) -> ActionCanonical:
        """Reconstruct action with updated confidence.

        For now, return action as-is. In phase 5, may update confidence field.
        """
        return action
