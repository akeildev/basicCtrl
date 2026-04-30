"""Per-action-class weighted vote with present-signal renormalization.

Per ARCHITECTURE.md L173:
    confidence >= 0.50 -> VERIFIED
    confidence <  0.30 -> escalate to L3 (Plan 06)

THE MATH (BLOCKER 1 from planning iter 1):
    aggregate() RENORMALIZES BY THE SUM OF WEIGHTS OF
    PRESENT-NON-ZERO SIGNALS — not by the total weight of all
    possible signals for the action class. Without this rule, a
    single-signal hit (e.g. ``ax.value_changed=1.0`` for a Calculator
    button click) would yield ``0.6 / 1.9 ≈ 0.32`` and fail to clear
    the 0.50 VERIFIED bar. With renormalization, absent signals are
    EXCLUDED (not averaged in as zero), so the ratio becomes
    ``0.6 / 0.6 = 1.0`` — well above 0.50.

    Per-signal weights are starting heuristics; aggregator renormalizes
    by present-signal weights, so single-signal hits resolve to weight=1.0
    in their own column. Phase 3 tunes weights against real failure data;
    Phase 1 demo passes deterministically because Calculator click reliably
    emits ax.value_changed.
"""
from __future__ import annotations

from typing import Mapping


# Confidence thresholds. Plan 01-06 imports L3_ESCALATE_THRESHOLD to gate the
# L3 LLM fallback escalation; plan 01-09 demo asserts a Calculator click
# crosses VERIFIED_THRESHOLD inside <50 ms.
VERIFIED_THRESHOLD: float = 0.50
L3_ESCALATE_THRESHOLD: float = 0.30


class WeightedVote:
    """Per-action-class weighted vote with present-signal renormalization.

    Per ARCHITECTURE.md L173: weighted vote → confidence ≥ 0.50 → VERIFIED;
    confidence < 0.30 → escalate to L3.

    Per-signal weights are starting heuristics; aggregator renormalizes by
    present-signal weights, so single-signal hits resolve to weight=1.0 in
    their own column. Phase 3 tunes weights against real failure data;
    Phase 1 demo passes deterministically because Calculator click reliably
    emits ax.value_changed (which alone clears the 0.50 VERIFIED bar under
    the renormalization rule).
    """

    # Per-action-class signal weights. The same signal name can appear under
    # different action classes with different weights — e.g. l1.pasteboard_changed
    # is a NEGATIVE-class signal under "type" (text typing should NOT change the
    # pasteboard) so its weight is small (0.1).
    WEIGHTS: dict[str, dict[str, float]] = {
        "click": {
            "ax.value_changed": 0.6,
            "ax.focused_changed": 0.4,
            "cdp.dom_modified": 0.6,
            "l1.window_diff": 0.3,
            "l1.dhash_changed": 0.3,
        },
        "type": {
            "ax.value_changed": 0.8,
            "ax.selected_text_changed": 0.5,
            "cdp.dom_attribute_modified": 0.7,
            "l1.pasteboard_changed": 0.1,  # negative class — should NOT change on type
        },
        "scroll": {
            "ax.layout_changed": 0.7,
            "l1.window_diff": 0.5,
            "l1.dhash_changed": 0.4,
        },
        "set_value": {
            "ax.value_changed": 0.9,
        },
    }

    def aggregate(self, action_class: str, signals: Mapping[str, float]) -> float:
        """Compute weighted-vote confidence in [0.0, 1.0] with renormalization.

        Algorithm:

        1. Look up ``self.WEIGHTS[action_class]``. If missing → return 0.0.
        2. Build ``active`` = {signal_id -> weight} for signals present in the
           input dict with a strictly-positive value.
        3. If no active signal → return 0.0.
        4. Compute ``weighted_sum = Σ signal_value * weight`` over actives.
        5. Compute ``active_total = Σ weight`` over actives.
        6. Return ``weighted_sum / active_total`` clamped to [0.0, 1.0].

        Step 5 is THE renormalization rule: missing signals are EXCLUDED from
        the denominator instead of being treated as zeros. That's what lets a
        single-signal hit resolve to 1.0 in its own column.
        """
        weights = self.WEIGHTS.get(action_class, {})
        if not weights:
            # Unknown action class — fail open at 0 (caller escalates to L3).
            return 0.0

        # active = signals present in this round with a strictly-positive value.
        active = {sid: w for sid, w in weights.items() if signals.get(sid, 0.0) > 0.0}
        if not active:
            return 0.0

        weighted_sum = sum(signals[sid] * w for sid, w in active.items())
        active_total = sum(active.values())
        result = weighted_sum / active_total

        # Defensive clamp — handles signal values >1.0 or floating drift.
        return max(0.0, min(1.0, result))
