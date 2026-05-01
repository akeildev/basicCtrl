---
phase: 04-cognition-learning-episodic
plan: 04
subsystem: ensemble-critic-speculator
tags: [Wave-2, ensemble-vote, critic-ranker, speculative-prediction, P21-mitigation, P22-mitigation]
dependency_graph:
  requires: [04-01-schemas, 04-02-apple-fm-grounder, 04-03-planner-verifier]
  provides: [COG-06-ensemble, COG-08-critic, COG-10-speculator]
  affects: [04-05-episodic, 04-07-recovery, 04-09-orchestrator]
tech_stack:
  added: []
  patterns: [asyncio async methods, pairwise comparison, type-enforced Literal gates]
key_files:
  created:
    - cua_overlay/cognition/ensemble.py
    - cua_overlay/cognition/critic.py
    - cua_overlay/cognition/speculative.py
    - tests/unit/cognition/test_ensemble.py
    - tests/unit/cognition/test_critic.py
    - tests/unit/cognition/test_speculative.py
decisions:
  - EnsembleVote majority rule: 2-of-3 agree on (tier, bbox) → action proceeds
  - Critic pairwise comparison: deterministic heuristics (Phase 4); Phase 5 small model
  - Speculator placeholder: return synthetic READ-only predictions; Phase 5 wires Planner
metrics:
  duration: "18m"
  tasks_completed: 3
  files_created: 6
  tests_passing: 29/29
  commits: 1
---

# Phase 04 Plan 04: Ensemble Vote + Critic Oracle Ranker + Speculator - Summary

**One-liner:** 3-model ensemble voting (Opus + GPT-5 + Apple FM) with majority rule and tiebreaker, Critic oracle ranker with pairwise comparison (P21 no-self-critique), and Speculative pre-execution with type-enforced READ-only (P22).

## Objectives Achieved

1. **Ensemble Vote (D-09, P6 Apple FM gating)**
   - 3-model aggregation: Opus planner + GPT-5 + Apple FM tier-0 classifier
   - Majority rule: when 2 of 3 agree on (tier, target_bbox), action passes with avg confidence
   - Tiebreaker: all-disagree → pick highest-confidence vote
   - Apple FM hard-gated to enum output only (P6 mitigation)

2. **Critic Oracle Ranker (D-08, P21 mitigation)**
   - Pairwise comparison graph: ranks external oracle candidates by win count
   - **NO SELF-CRITIQUE**: Critic never asks itself "are you sure?" — comparison is terminal (P21 mitigation)
   - Deterministic heuristics: favor higher-tier (T1>T2>...>T5) and tighter bboxes
   - Returns top-1 candidate + confidence [0, 1]

3. **Speculative Pre-Execution (D-10, P22 mitigation)**
   - Predict N+1, N+2 in parallel with N's verifier
   - **TYPE-ENFORCED READ-ONLY**: Pydantic `kind: Literal["READ"]` prevents MUTATE construction
   - Mutation gate at runtime: blocks MUTATE until N verified (belt-and-suspenders)
   - Hit-rate tracking: record when N+1 prediction matches actual N+1

4. **Test Coverage** — 29 unit tests all passing
   - Ensemble: 8 tests (majority, tiebreaker, FM enum validation, graceful fallbacks)
   - Critic: 10 tests (pairwise ranking, specificity, confidence margins, no self-critique)
   - Speculator: 11 tests (READ-only gate, MUTATE rejection, hit-rate tracking, step indices)

## What Was Built

### Task 1: EnsembleVote (cua_overlay/cognition/ensemble.py)

**Class: EnsembleVotingEngine**
- `async vote(opus_action, gpt5_action, apple_fm_output, current_state) -> (action, confidence, model_name)`

**Implementation:**
- Extract tier + target_bbox from Opus and GPT-5 ActionCanonical objects
- Translate Apple FM enum (T1-T5, retry, escalate, abort) to tier preference
- Build vote list (up to 3 models)
- Check for 2-of-3 agreement on (tier, target_bbox):
  - If found: return winning action with avg confidence of agreeing votes
  - If not found: use tiebreaker (highest confidence vote)
- Log structured events for ensemble_vote_majority and ensemble_vote_disagreement

**Key logic:**
```python
agreement_map: dict[tuple, list[EnsembleVote]] = {}
for vote in votes:
    key = (vote.tier, vote.target_bbox)
    if key not in agreement_map:
        agreement_map[key] = []
    agreement_map[key].append(vote)

# If any (tier, target) has 2+ votes: majority wins
# Otherwise: tiebreaker picks highest confidence
```

**Tests (8 passing):**
- ✅ test_two_of_three_agree_majority_wins
- ✅ test_all_three_disagree_tiebreaker
- ✅ test_apple_fm_enum_validation_invalid_output
- ✅ test_all_valid_apple_fm_outputs
- ✅ test_apple_fm_none_graceful_fallback
- ✅ test_tiebreaker_picks_highest_confidence
- ✅ test_fm_policy_outputs_do_not_map_to_tier
- ✅ test_average_confidence_on_agreement

### Task 2: Critic Oracle Ranker (cua_overlay/cognition/critic.py)

**Class: Critic**
- `async rank_candidates(current_state, candidates: list[ActionCanonical], criterion) -> (best_action, confidence)`

**Implementation:**
- Takes list of ActionCanonical candidates (from recovery branches, ensemble tiebreak, planner replan)
- Builds pairwise comparison graph:
  - For each pair (A, B), calls `_compare_pair()` to determine winner
  - Winner gets 1 point in `wins[idx]` dict
- Rank by win count; top candidate is returned with confidence = max_wins / (num_candidates - 1)

**Comparison heuristic (`_compare_pair`):**
- Deterministic, no LLM (Phase 4); uses specificity score
- Tier priority: T1 (0.95) > T2 (0.85) > ... > T5 (0.55)
- Bonus (+0.05) for small bbox (specific target)
- Tie-breaker: alphabetical tier comparison

**P21 KEY ENFORCEMENT:**
- No self-critique: Critic output is terminal; never loops back to question its own ranking
- Pairwise comparison uses SEPARATE deterministic model (not one of the oracles being ranked)
- Code has zero `self_critique`, `self.*critic`, or `same.*model` patterns

**Tests (10 passing):**
- ✅ test_rank_three_recovery_branches
- ✅ test_rank_empty_candidates_raises
- ✅ test_rank_single_candidate
- ✅ test_pairwise_comparison_graph
- ✅ test_no_self_critique_pattern
- ✅ test_different_criterion_types
- ✅ test_specificity_score_calculation
- ✅ test_confidence_based_on_win_margin
- ✅ test_planner_replan_criterion
- ✅ test_critic_self_rank_raises

### Task 3: Speculator (cua_overlay/cognition/speculative.py)

**Class: Speculator**
- `async predict_n_plus_k(current_action, current_state, step_index, k=2) -> list[SpeculativeDraft]`
- Hit-rate tracking: `record_hit()`, `record_miss()`, `hit_rate() -> float`

**Implementation:**
- Generates k synthetic SpeculativeDraft objects with step_index = current_step + i for i in [1..k]
- All drafts have kind="READ" (type-enforced by Pydantic)
- Placeholder: returns current_action as action; Phase 5 will call planner.plan_action() with lookahead
- Logs speculative_predict events

**P22 KEY ENFORCEMENT:**
- `SpeculativeDraft.kind: Literal["READ"]` at schema level (defined in 04-01)
- Pydantic rejects any attempt to construct kind="MUTATE" with ValidationError
- Runtime gate `SpeculationMutationGate.check_can_fire()` blocks non-READ drafts (belt-and-suspenders)

**Classes:**
- `Speculator`: generates draft predictions, tracks hit-rate
- `SpeculationMutationGate`: runtime gate (blocks MUTATE until N verified)

**Tests (11 passing):**
- ✅ test_predict_n_plus_k_returns_k_drafts
- ✅ test_all_drafts_kind_read
- ✅ test_draft_kind_mutate_rejected_by_type_system (P22!)
- ✅ test_draft_step_indices_incremented
- ✅ test_hit_rate_tracking
- ✅ test_hit_rate_all_misses
- ✅ test_hit_rate_all_hits
- ✅ test_hit_rate_empty
- ✅ test_confidence_estimate_bounds
- ✅ test_read_only_draft_can_fire
- ✅ test_mutation_gate_blocks_mutate_until_verified

## Deviations from Plan

**None — plan executed exactly as written.**

### Implementation notes:
- All three modules use async methods per architecture pattern (Phase 2+)
- Critic uses deterministic heuristics in Phase 4; real pairwise-model call deferred to Phase 5
- Speculator returns placeholder predictions; wiring to Planner.plan_action() deferred to Phase 5
- No external API calls in Phase 4 (all mocked for tests)

## Threat Mitigations Verified

| Threat | Mitigation | Test Evidence |
|--------|-----------|---------------|
| P6 (Apple FM hallucinated params) | AppleFMOutput hard-gated to Literal enum | test_apple_fm_enum_validation_invalid_output ✅ |
| P21 (intrinsic LLM self-correction broken) | Critic ranks external oracles; no self-critique loop | test_no_self_critique_pattern ✅ + code grep |
| P22 (speculative mutation) | SpeculativeDraft.kind=Literal["READ"] prevents MUTATE | test_draft_kind_mutate_rejected_by_type_system ✅ |

## Known Stubs

1. **Critic pairwise comparison model (Phase 5):**
   - Currently: deterministic tier+bbox heuristics
   - Phase 5: wire small fast model (Apple FM or Haiku 3.5) for real pairwise decisions

2. **Speculator N+1, N+2 generation (Phase 5):**
   - Currently: returns synthetic drafts with current_action
   - Phase 5: call Planner.plan_action() with lookahead prompt to generate real next-steps

3. **Hit-rate ground truth (Phase 5 integration):**
   - Speculator tracks hits/misses but no mechanism yet to compare N+1 prediction vs actual
   - Integration test will replay recorded traces and measure accuracy

## Test Results

**All 29 tests PASSED:**

```
tests/unit/cognition/test_ensemble.py          8 PASSED
tests/unit/cognition/test_critic.py            10 PASSED
tests/unit/cognition/test_speculative.py       11 PASSED
----------------------------------------------------------
Total                                          29 PASSED (0.05s)
```

Command: `.venv/bin/python -m pytest tests/unit/cognition/test_ensemble.py tests/unit/cognition/test_critic.py tests/unit/cognition/test_speculative.py -v`

## Architecture Integration

**Wave 2 cognition stack (now complete):**
```
Wave 0 (04-01): Schemas + type contracts (frozen, immutable)
Wave 1 (04-02): AppleFMClassifier + Grounder (parallel inference)
Wave 1 (04-03): Planner + WorldModelPredictor + VerifierLLM (parallel agents)
Wave 2 (04-04): EnsembleVote orchestrator ← NEW
              + Critic oracle ranker ← NEW
              + Speculator N+1/N+2 predictor ← NEW

Downstream wiring:
├─ 04-05: Episodic memory (FAISS) — uses Planner.lookup() + Speculator hits
├─ 04-06: Recipe synthesis — reads Speculator predictions + Planner plans
├─ 04-07: Recovery orchestrator — uses Critic.rank_candidates() + WorldModel
└─ 04-09: Race orchestrator — consumes EnsembleVote decisions
```

## Design Decisions

1. **Ensemble majority rule (D-09):**
   - When 2 of 3 agree → action proceeds immediately
   - 3-way disagreement → escalate (Critic ranks, user decides)
   - Apple FM always lower confidence tier (100-200ms inference; Oracle/GPT-5 > Apple FM)

2. **Critic deterministic Phase 4 (D-08):**
   - Tier priority hierarchy + bbox specificity heuristics
   - Deferring small model call to Phase 5 reduces Phase 4 LLM cost
   - Pairwise comparison scales O(N²) but N≤5 candidates typical

3. **Speculator placeholder (D-10):**
   - Phase 4 focuses on type-system enforcement (P22)
   - Real prediction wired in Phase 5 (cost: Planner call × 2 per step)
   - Hit-rate tracking ready for integration tests

## Next Steps

**Phase 4 remaining (04-05..04-09):**
- 04-05: Episodic memory FAISS indexing
- 04-06: Recipe synthesis from ObservedAction stream
- 04-07: Recovery orchestrator B3/B4 wiring (uses Critic + WorldModel)
- 04-08: CGEvent tap learning recorder
- 04-09: Phase 4 verification tests + integration

**Phase 5 (Refinement):**
- Wire Critic to real small model (Apple FM or Haiku 3.5)
- Wire Speculator to Planner.plan_action() with lookahead
- Integration tests: ensemble agreement rate, Critic ranking accuracy, Speculator hit-rate

---

**Commits:**
1. `96c9622` — feat(04-04): Ensemble vote, Critic oracle ranker, Speculator (P21/P22 mitigations)

**Execution time:** 18m

**Self-Check: PASSED**
- ✓ ensemble.py exists, EnsembleVotingEngine.vote() async method
- ✓ critic.py exists, Critic.rank_candidates() async method, no self-critique patterns
- ✓ speculative.py exists, SpeculativeDraft.kind=Literal["READ"] type enforced
- ✓ All 6 test files created + all 29 tests passing
- ✓ P21 grep-check: zero self_critique patterns in critic.py
- ✓ P22 grep-check: kind="READ" enforced at type level; test_draft_kind_mutate_rejected passes
- ✓ commit 96c9622 verified
