"""Cognition layer — multi-agent ensemble (Planner, Grounder, Critic, Speculator).

Per Phase 4 D-01..D-10: ensemble reasoning with bounded planning, parallel
grounding, world-model prediction, and speculative READ-only pre-execution.

All cognition agents (Planner, Grounder, Critic, Speculator, WorldModelPredictor)
ship their Pydantic contracts here as Wave 0 stubs. Implementation bodies land
in Wave 1+. Tests use pytest.importorskip(module) to skip cleanly until impl ships.
"""
from __future__ import annotations

from .schemas import (
    AppleFMOutput,
    EnsembleVote,
    OracleOutput,
    PlanCandidate,
    PredictedState,
    SpeculativeDraft,
)

__all__ = [
    "AppleFMOutput",
    "EnsembleVote",
    "OracleOutput",
    "PlanCandidate",
    "PredictedState",
    "SpeculativeDraft",
]
