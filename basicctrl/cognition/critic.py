"""Critic oracle ranker — ranks external oracle outputs, NEVER self-critiques (P21).

Per D-08: Critic ranks recovery branch candidates, ensemble tiebreaks, and planner
replans via pairwise comparison. Uses a small fast model (Apple FM or Haiku 3.5).

P21 MITIGATION: Intrinsic LLM self-correction is 16-27% accurate. Critic NEVER asks
itself "are you sure?" Instead, it uses pairwise comparison of EXTERNAL oracle outputs
as the terminal decision. Pairwise result is final; no second-order critique.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

import structlog

if TYPE_CHECKING:
    from cua_overlay.state.causal_dag import ActionCanonical, StateGraph

logger = structlog.get_logger(__name__)


class Critic:
    """Rank external oracle outputs via pairwise comparison (P21 mitigation)."""

    async def rank_candidates(
        self,
        current_state: StateGraph,
        candidates: list[ActionCanonical],
        criterion: Literal["recovery_branch", "ensemble_tiebreak", "planner_replan"] = "recovery_branch",
    ) -> tuple[ActionCanonical, float]:
        """
        D-08: Rank external oracle outputs. NEVER self-critique.

        Per P21: intrinsic self-correction is 16-27% accurate. Instead, use
        pairwise comparison to rank candidates. Output is final (no self-critique loop).

        Args:
            current_state: Current state for context
            candidates: List of ActionCanonical to rank
            criterion: What we're ranking for (recovery_branch, ensemble_tiebreak, planner_replan)

        Returns:
            (best_candidate, confidence): Top-ranked candidate + confidence [0, 1]
        """
        if not candidates:
            raise ValueError("candidates list cannot be empty")

        if len(candidates) == 1:
            return candidates[0], 0.85

        # Build pairwise comparison graph
        wins: dict[int, int] = {i: 0 for i in range(len(candidates))}

        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                # Pairwise comparison: "Which action is better for state S?"
                winner_idx = await self._compare_pair(
                    current_state, candidates[i], candidates[j], criterion
                )
                wins[winner_idx] += 1

        # Rank by wins
        ranked_indices = sorted(wins.keys(), key=lambda idx: wins[idx], reverse=True)
        best_idx = ranked_indices[0]
        best_candidate = candidates[best_idx]

        # Confidence based on win margin
        max_wins = wins[best_idx]
        total_matches = len(candidates) - 1
        confidence = max_wins / total_matches if total_matches > 0 else 0.85

        logger.info(
            "critic_ranked_candidates",
            criterion=criterion,
            num_candidates=len(candidates),
            winner_idx=best_idx,
            wins=max_wins,
            confidence=confidence,
        )

        return best_candidate, confidence

    async def _compare_pair(
        self,
        state: StateGraph,
        candidate_a: ActionCanonical,
        candidate_b: ActionCanonical,
        criterion: str,
    ) -> int:
        """
        Pairwise comparison of two candidates.

        Returns: 0 if candidate_a wins, 1 if candidate_b wins.

        P21 KEY: This comparison uses a SEPARATE model (not one of the oracles being ranked).
        We never ask a model "are you sure about your own output?" — that's intrinsic
        self-correction which is 16-27% accurate.

        For now, use deterministic heuristics (Phase 4). Phase 5 will use small fast model.
        """
        # Phase 4 heuristic: prefer higher-specificity actions
        a_specificity = self._compute_specificity(candidate_a)
        b_specificity = self._compute_specificity(candidate_b)

        if a_specificity > b_specificity:
            return 0  # A wins
        elif b_specificity > a_specificity:
            return 1  # B wins
        else:
            # Tie: prefer by alphabetical order (deterministic).
            # F13 fix: ActionCanonical.tier defaults to None (set by race winner),
            # not "T1" — so getattr-with-default returned None and `None <= None`
            # raised TypeError. Coerce missing tier to "T1" explicitly.
            a_tier = getattr(candidate_a, "tier", None) or "T1"
            b_tier = getattr(candidate_b, "tier", None) or "T1"
            return 0 if a_tier <= b_tier else 1

    def _compute_specificity(self, action: ActionCanonical) -> float:
        """Compute action specificity score [0, 1].

        Higher = more specific (e.g., click with tight bbox > generic scroll).
        """
        specificity = 0.5  # Baseline

        # Prefer T1 (specific AX target) over T5 (pixel fallback).
        # F13 fix: ActionCanonical.tier is None until race winner sets it; the
        # `or "T1"` guard makes this resilient to that.
        tier = getattr(action, "tier", None) or "T1"
        tier_priority = {"T1": 0.95, "T2": 0.85, "T3": 0.75, "T4": 0.65, "T5": 0.55}
        specificity = tier_priority.get(tier, 0.5)

        # Bonus if action has a narrow bbox (specific target)
        bbox = getattr(action, "target_bbox", (0, 0, 0, 0))
        if isinstance(bbox, (tuple, list)) and len(bbox) == 4:
            x0, y0, x1, y1 = bbox
            width = abs(x1 - x0)
            height = abs(y1 - y0)
            area = width * height
            if area > 0 and area < 10000:  # Small target = specific
                specificity += 0.05

        return min(specificity, 1.0)
