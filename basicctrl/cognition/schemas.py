"""Phase 4 Cognition Pydantic v2 schemas — type-system gates for P6, P21, P22.

Per D-02..D-10 (04-CONTEXT.md):

* AppleFMOutput: Hard-gated enum (P6 mitigation) — text classifier only
* SpeculativeDraft: kind=Literal["READ"] hard-typed (P22 mitigation)
* OracleOutput: What Critic ranks (external oracles only; P21 mitigation)
* EnsembleVote: Ranked action from one tier (Opus / GPT-5 / Apple FM)
* PlanCandidate: Planner output (steps, preconds, success criteria)
* PredictedState: World-model post-state before action fires

All frozen=True per Phase 1-3 Pydantic precedent for immutability.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from basicctrl.state.causal_dag import ActionCanonical, HoarePre


class AppleFMOutput(BaseModel):
    """Per D-02: Apple FoundationModels tier-0 classifier output.

    Strict enum-only validation (P6 mitigation). Apple FM must output ONE
    of these values; anything else is a runtime error. Never a complex
    JSON object, never multi-field params.

    Text-only API gate (P7): Apple FM sees text descriptions, not pixels.
    """

    model_config = ConfigDict(frozen=True)

    output: Literal[
        "T1",
        "T2",
        "T3",
        "T4",
        "T5",
        "retry",
        "escalate",
        "abort",
    ]


class PlanCandidate(BaseModel):
    """Per D-03: Planner output — bounded step sequence with contracts.

    Opus planner returns a sequence of ActionCanonical steps. Each step
    includes preconditions (must be true before fire) and success criteria
    (assertions that should hold after). `bounded=True` means the planner
    enforces max_steps (default 20).

    Phase 4: steps and preconds can be dicts or objects; will validate
    strictly in Phase 5+ when full Pydantic coercion is in place.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    steps: list[Any]  # Phase 4: dicts or ActionCanonical objects
    preconds: list[Any]  # Phase 4: dicts or HoarePre objects
    success_criteria: list[str]
    bounded: bool = True


class PredictedState(BaseModel):
    """Per D-07: World-model predictor output — post-state before action fires.

    Before the action is executed, the world-model predicts what state changes
    should occur. Used by Phase 3 B3 (world_replan) to detect if the world
    didn't match predictions (reason to replan).

    ax_delta: expected AX tree deltas (e.g., new elements, removed, changed roles)
    screenshot_phash_delta: perceptual hash of expected screenshot change
    expected_notifs: list of notification types (e.g., "kAXValueChanged", "focus_moved")
    """

    model_config = ConfigDict(frozen=True)

    ax_delta: dict[str, Any]
    screenshot_phash_delta: str
    expected_notifs: list[str]


class EnsembleVote(BaseModel):
    """Per D-09: One vote from the 3-model ensemble (Opus / GPT-5 / Apple FM).

    Ensemble voting races all 3 models in parallel. Each model votes on
    a target action + tier + confidence. Majority wins; on tie, highest
    confidence vote wins.

    target_bbox: (x0, y0, x1, y1) screen coordinates of the target
    confidence: 0.0-1.0 model's confidence
    model: which model cast this vote
    tier: which translator tier (T1-T5) is predicted to succeed
    """

    model_config = ConfigDict(frozen=True)

    tier: Literal["T1", "T2", "T3", "T4", "T5"]
    target_bbox: tuple[float, float, float, float]
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: Literal["Opus", "GPT-5", "AppleFM"]


class OracleOutput(BaseModel):
    """Per D-08: Critic's input — oracle outputs to rank.

    The Critic (recovery arbiter) NEVER self-critiques. Instead, it ranks
    external oracle outputs (planner candidates, grounder bboxes, verifier-LLM
    repairs). This is the type of data Critic.rank_candidates() consumes.

    P21 mitigation: explicit external oracle ranking only.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    candidates: list[ActionCanonical]
    ranker_model: str  # "AppleFM" or "Haiku 3.5" or similar
    top_k: int = 1


class SpeculativeDraft(BaseModel):
    """Per D-10: Speculative pre-execution candidate (READ-ONLY by type system).

    Apple FM predicts steps N+1, N+2 in parallel with N's verifier. The
    kind=Literal["READ"] hard-types to READ-only (P22 mitigation); mutation
    gate at orchestrator blocks any speculative MUTATE until N is VERIFIED.

    step_index: which step in the plan (N+1, N+2, etc.)
    confidence_estimate: planner's confidence in this candidate (0.0-1.0)
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    action: ActionCanonical
    kind: Literal["READ"]  # P22: hard-typed READ-only, never MUTATE
    step_index: int
    confidence_estimate: float = Field(..., ge=0.0, le=1.0)
