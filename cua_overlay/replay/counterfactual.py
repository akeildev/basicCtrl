"""Counterfactual replay — alternate branch state reconstruction."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from cua_overlay.replay.engine import ReplayEngine


@dataclass
class CounterfactualEvent:
    """Single candidate branch outcome that lost in a race or recovery step."""

    step_idx: int
    tier: str  # T1-T5
    channel: str  # C1-C5
    why_lost: str  # "cancelled", "timeout", "verifier_rejected", "never_started"
    hypothetical_state: Optional[dict] = None  # Reconstructed state if branch had won (None if only cancelled)


class CounterfactualRenderer:
    """Renders alternate recovery branch outcomes.

    This module reconstructs what state WOULD have been if a losing
    recovery branch (B1-B5 from Phase 3) or race loser (channels from Phase 2)
    had won instead of the actual winner.

    Current implementation:
    - Phase 3 recovery branches (B1-B5): Track which branches existed at each step,
      record when they were cancelled (why + when)
    - Phase 2 race losers: Track losing channels, record outcome (never implemented yet)

    For now, we capture EXISTENCE + CANCELLATION; hypothetical state is None
    (would require re-running the action in a sandbox, which is out of scope).
    Counterfactual VIEW shows these as dashed-purple "ghost branches" off
    the main timeline at the step where they were cancelled.
    """

    def __init__(self, engine: ReplayEngine):
        """Initialize counterfactual renderer with a replay engine.

        Args:
            engine: ReplayEngine instance pre-loaded with action_log.ndjson
        """
        self.engine = engine

    def get_alternate_state(self, step_idx: int, alternate_branch: str) -> dict:
        """Reconstruct state if branch B had won instead of actual winner.

        Args:
            step_idx: Action step to reconstruct
            alternate_branch: Branch name (e.g., "B1", "B2", "T1/C5" for race loser)

        Returns:
            StateNode dict with branch B actions applied post-divergence.
            Empty dict if branch was never started.

        Note: Current implementation returns {} (stub) — requires recording
        hypothetical state at cancellation time or re-running branch in sandbox.
        """
        # TODO(Phase 5 Wave 6): Implement via:
        # 1. Load recovery_log.ndjson, find which branches were tried
        # 2. For alternate_branch, get its action sequence (if any)
        # 3. Replay from divergence_point() applying alternate_branch actions
        # 4. Return reconstructed state
        return {}

    def get_divergence_point(self) -> int:
        """Find first step where multiple branches existed (recovery or race).

        Returns:
            Step index of first action with multiple branches.
            Returns 0 if no divergence found (single-channel path).

        Checks:
        - recovery_branches field in action log (Phase 3 recovery)
        - candidate_channels field in action log (Phase 2 race losers)
        """
        for i, action in enumerate(self.engine.actions):
            # Phase 3 recovery: multiple branches attempted
            if action.get("recovery_branches") and len(action.get("recovery_branches", [])) > 1:
                return i

            # Phase 2 race: multiple channels raced (captured in candidates ledger)
            if action.get("candidates") and len(action.get("candidates", [])) > 0:
                return i

        return 0

    def get_candidate_branches(self, step_idx: int) -> list[CounterfactualEvent]:
        """Extract all candidate branches that were cancelled at this step.

        Args:
            step_idx: Index into engine.actions

        Returns:
            List of CounterfactualEvent objects representing losers.
        """
        if step_idx < 0 or step_idx >= len(self.engine.actions):
            return []

        action = self.engine.actions[step_idx]
        candidates: list[CounterfactualEvent] = []

        # Phase 3 recovery branches that were cancelled
        recovery_branches = action.get("recovery_branches", [])
        winner_branch = action.get("winner_branch")

        for branch_info in recovery_branches:
            branch_name = branch_info.get("name") if isinstance(branch_info, dict) else branch_info
            if branch_name != winner_branch and branch_name:
                candidates.append(
                    CounterfactualEvent(
                        step_idx=step_idx,
                        tier="RECOVERY",  # Special tier for Phase 3 branches
                        channel=branch_name,
                        why_lost="cancelled",  # Phase 3 losers are always cancelled (not started past winner)
                        hypothetical_state=None,
                    )
                )

        # Phase 2 race losers (losing channels that were cancelled)
        # These are logged in a "candidates" ledger (to be implemented in race.py)
        race_candidates = action.get("candidates", [])
        winner_channel = action.get("winner", {}).get("channel")

        for candidate in race_candidates:
            channel = candidate.get("channel")
            tier = candidate.get("tier")
            why_lost = candidate.get("why_lost", "cancelled")

            if channel != winner_channel and channel:
                candidates.append(
                    CounterfactualEvent(
                        step_idx=step_idx,
                        tier=tier or "UNKNOWN",
                        channel=channel,
                        why_lost=why_lost,
                        hypothetical_state=None,
                    )
                )

        return candidates

    def render_dashed_path(self, branch: CounterfactualEvent) -> list[tuple[float, float]]:
        """Generate dashed timeline path for alternate branch.

        Args:
            branch: CounterfactualEvent to render

        Returns:
            List of (x, y) screen coordinates for the dashed line.
            Will be consumed by Swift Canvas to draw dashed-purple path.

        Note: Stub implementation returns empty list.
        Actual implementation will project the branch timeline onto 3D coords.
        """
        # TODO(Phase 5 Wave 5): Implement via Timeline3D integration:
        # 1. Create TimelineNode for this branch at step_idx with is_branch=True
        # 2. Create path from divergence_point() to this step
        # 3. Project each point via Timeline3D.project_to_2d()
        # 4. Return as [(x1, y1), (x2, y2), ...]
        return []

    def all_counterfactuals(self) -> list[CounterfactualEvent]:
        """Extract all counterfactual branches across entire action_log.

        Returns:
            Flat list of all CounterfactualEvent objects from all steps.

        Useful for building the complete set of "what-if" branches for
        the counterfactual view.
        """
        all_events: list[CounterfactualEvent] = []
        for step_idx in range(len(self.engine.actions)):
            all_events.extend(self.get_candidate_branches(step_idx))
        return all_events
