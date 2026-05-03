"""Deterministic verifier ensemble (L0 push + L1 cheap diff + L2 medium + L3 stub).

Phase 1 plan 05 wires L0 and L1; plan 06 adds L2 medium-cost AX subtree
walk (Vision OCR + walker reuse) + L3 LLM contract stub. The aggregator's
confidence threshold contract:
``confidence >= 0.50`` -> VERIFIED, ``confidence < 0.30`` -> escalate to L3.
"""
from __future__ import annotations

from basicctrl.verifier.ensemble.l0_push import L0Push
from basicctrl.verifier.ensemble.l1_cheap import L1Cheap, L1Snapshot
from basicctrl.verifier.ensemble.l2_medium import L2Medium, L2Snapshot
from basicctrl.verifier.ensemble.l3_llm import L3Contract, L3Stub
from basicctrl.verifier.ensemble.weighted_vote import (
    L3_ESCALATE_THRESHOLD,
    VERIFIED_THRESHOLD,
    WeightedVote,
)

__all__ = [
    "L0Push",
    "L1Cheap",
    "L1Snapshot",
    "L2Medium",
    "L2Snapshot",
    "L3Contract",
    "L3Stub",
    "L3_ESCALATE_THRESHOLD",
    "VERIFIED_THRESHOLD",
    "WeightedVote",
]
