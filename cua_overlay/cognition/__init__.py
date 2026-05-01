"""Cognition layer — multi-agent ensemble (Planner, Grounder, Critic, Speculator).

Per Phase 4 D-01..D-10: ensemble reasoning with bounded planning, parallel
grounding, world-model prediction, and speculative READ-only pre-execution.

All cognition agents (Planner, Grounder, Critic, Speculator, WorldModelPredictor)
ship their Pydantic contracts here as Wave 0 stubs. Implementation bodies land
in Wave 1+. Tests use pytest.importorskip(module) to skip cleanly until impl ships.
"""
from __future__ import annotations

from .apple_fm import AppleFMClassifier
from .critic import Critic
from .ensemble import EnsembleVotingEngine
from .grounder import Grounder
from .planner import Planner, WorldModelPredictor
from .schemas import (
    AppleFMOutput,
    EnsembleVote,
    OracleOutput,
    PlanCandidate,
    PredictedState,
    SpeculativeDraft,
)
from .speculative import Speculator, SpeculationMutationGate
from .verifier_llm import VerifierLLM

__all__ = [
    "AppleFMClassifier",
    "AppleFMOutput",
    "Critic",
    "EnsembleVotingEngine",
    "EnsembleVote",
    "Grounder",
    "OracleOutput",
    "PlanCandidate",
    "Planner",
    "PredictedState",
    "Speculator",
    "SpeculationMutationGate",
    "SpeculativeDraft",
    "VerifierLLM",
    "WorldModelPredictor",
]
