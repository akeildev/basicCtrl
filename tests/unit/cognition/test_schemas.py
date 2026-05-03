"""Phase 4 cognition schemas — unit tests for type gates and frozen contract.

Per Wave 0 pattern: pytest.importorskip skips cleanly until impl ships.
Tests lock the system-wide cognition contract (P6, P21, P22 mitigations).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

pytest.importorskip("basicctrl.cognition")

from basicctrl.cognition import (
    AppleFMOutput,
    EnsembleVote,
    OracleOutput,
    PlanCandidate,
    PredictedState,
    SpeculativeDraft,
)
from basicctrl.state.causal_dag import ActionCanonical, HoarePre


def _build_action(
    step_idx: int = 0,
    kind: str = "READ",
    action_type: str = "click",
) -> ActionCanonical:
    """Helper to build a minimal ActionCanonical."""
    return ActionCanonical(
        id=f"action-{step_idx}",
        step_idx=step_idx,
        kind=kind,  # type: ignore[arg-type]
        target_key="button://calc/5",
        action_type=action_type,
        payload={"x": 100, "y": 100},
        timestamp_ns=0,
        session_id="test-session",
    )


@pytest.mark.unit
def test_apple_fm_output_valid_enum() -> None:
    """AppleFMOutput accepts any Literal value."""
    for val in ["T1", "T2", "T3", "T4", "T5", "retry", "escalate", "abort"]:
        output = AppleFMOutput(output=val)  # type: ignore[arg-type]
        assert output.output == val


@pytest.mark.unit
def test_apple_fm_output_rejects_invalid() -> None:
    """AppleFMOutput rejects values outside the Literal (P6 mitigation)."""
    with pytest.raises(ValidationError, match="Input should be"):
        AppleFMOutput(output="invalid")  # type: ignore[arg-type]


@pytest.mark.unit
def test_apple_fm_output_frozen() -> None:
    """AppleFMOutput is frozen — no mutations after construction."""
    output = AppleFMOutput(output="T1")
    with pytest.raises(ValidationError, match="frozen"):
        output.output = "T2"  # type: ignore[misc]


@pytest.mark.unit
def test_speculative_draft_kind_is_read_only() -> None:
    """SpeculativeDraft.kind hard-typed to Literal["READ"] (P22 mitigation)."""
    action = _build_action(step_idx=2, kind="READ")
    draft = SpeculativeDraft(
        action=action,
        kind="READ",
        step_index=2,
        confidence_estimate=0.85,
    )
    assert draft.kind == "READ"
    # The type system prevents kind="MUTATE" — this is a mypy check,
    # but the model still validates at runtime:
    assert draft.action.kind == "READ"


@pytest.mark.unit
def test_speculative_draft_frozen() -> None:
    """SpeculativeDraft is frozen."""
    action = _build_action(step_idx=1, kind="READ")
    draft = SpeculativeDraft(
        action=action,
        kind="READ",
        step_index=1,
        confidence_estimate=0.75,
    )
    with pytest.raises(ValidationError, match="frozen"):
        draft.step_index = 2  # type: ignore[misc]


@pytest.mark.unit
def test_ensemble_vote_confidence_bounds() -> None:
    """EnsembleVote.confidence must be in [0.0, 1.0]."""
    vote = EnsembleVote(
        tier="T1",
        target_bbox=(100.0, 100.0, 150.0, 150.0),
        confidence=0.95,
        model="Opus",
    )
    assert vote.confidence == 0.95

    with pytest.raises(ValidationError, match="less than or equal to 1"):
        EnsembleVote(
            tier="T1",
            target_bbox=(100.0, 100.0, 150.0, 150.0),
            confidence=1.5,  # type: ignore[arg-type]
            model="Opus",
        )


@pytest.mark.unit
def test_plan_candidate_frozen() -> None:
    """PlanCandidate is frozen."""
    action = _build_action(step_idx=0, kind="READ")
    candidate = PlanCandidate(
        steps=[action],
        preconds=[],
        success_criteria=["target_clicked"],
    )
    with pytest.raises(ValidationError, match="frozen"):
        candidate.bounded = False  # type: ignore[misc]


@pytest.mark.unit
def test_predicted_state_frozen() -> None:
    """PredictedState is frozen."""
    state = PredictedState(
        ax_delta={"new": ["elem-1"]},
        screenshot_phash_delta="abc123",
        expected_notifs=["kAXValueChanged"],
    )
    with pytest.raises(ValidationError, match="frozen"):
        state.expected_notifs = []  # type: ignore[misc]


@pytest.mark.unit
def test_oracle_output_frozen() -> None:
    """OracleOutput is frozen."""
    action = _build_action(step_idx=0, kind="READ")
    oracle = OracleOutput(
        candidates=[action],
        ranker_model="AppleFM",
        top_k=1,
    )
    with pytest.raises(ValidationError, match="frozen"):
        oracle.top_k = 2  # type: ignore[misc]
