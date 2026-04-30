"""Deterministic verifier ensemble (L0 push + L1 cheap diff + WeightedVote).

Phase 1 wires L0 and L1; Phase 2 (Plan 06) adds L2 medium-cost AX subtree
walk + L3 LLM fallback. The aggregator's confidence threshold contract:
``confidence >= 0.50`` -> VERIFIED, ``confidence < 0.30`` -> escalate to L3.
"""
from __future__ import annotations

from cua_overlay.verifier.ensemble.l1_cheap import L1Cheap, L1Snapshot

__all__ = ["L1Cheap", "L1Snapshot"]
