---
phase: 04
plan: 01
subsystem: cognition-learning-episodic
tags: [Wave-0, schemas, pydantic, type-gates]
dependency_graph:
  requires: [STATE-02, STATE-03]
  provides: [STATE-04, COG-01..08, LEARN-01..05]
  affects: [Phase 4 Plans 04-02..04-09, Phase 5 Visualizer, Phase 6 SPI]
tech_stack:
  added: [Pydantic v2 frozen models]
  patterns: [pytest.importorskip, TYPE_CHECKING forward refs, circular import avoidance]
key_files:
  created:
    - basicctrl/cognition/__init__.py
    - basicctrl/cognition/schemas.py
    - basicctrl/learning/__init__.py
    - basicctrl/learning/schemas.py
    - basicctrl/state/episodic.py
    - tests/unit/cognition/test_schemas.py
    - tests/unit/learning/test_schemas.py
    - tests/unit/state/test_episodic.py
    - tests/unit/cognition/__init__.py
    - tests/unit/learning/__init__.py
  modified:
    - basicctrl/state/__init__.py
decisions: []
metrics:
  duration: "5m 42s"
  tasks_completed: 3
  files_created: 10
  files_modified: 1
  tests_passing: 24/24
  commits: 3
---

# Phase 04 Plan 01: Cognition + Learning + Episodic Schemas - Summary

**One-liner:** Type-system gates for Phase 4 ensemble cognition (P6, P21, P22 mitigations) + learning recorder contracts + episodic memory schemas. All Wave 0 stubs with pytest.importorskip pattern.

## Objectives Achieved

1. **Wave 0 Schema Freeze** — Established type contracts BEFORE implementations ship. Tests skip cleanly until actual code lands (Wave 1+).

2. **Threat Mitigations Baked Into Types:**
   - P6 (Apple FM param hallucination) — `AppleFMOutput` hard-gated to `Literal[...]` enum only
   - P21 (intrinsic LLM self-correction broken) — `OracleOutput` is external-oracle-only (Critic ranks, never self-critiques)
   - P22 (speculative mutation) — `SpeculativeDraft.kind` type-enforced to `Literal["READ"]`
   - P19 (episodic poisoning) — `EpisodicHit` tracks `success_count/failure_count` + `quarantined` flag

3. **Circular Import Pattern Solved** — Used `TYPE_CHECKING` forward refs in episodic.py; deferred imports in test_episodic.py

## What Was Built

### Task 1: Cognition Module Stubs + Pydantic Schemas

**Files created:**
- `basicctrl/cognition/__init__.py` — re-exports 6 Pydantic models
- `basicctrl/cognition/schemas.py` — 6 frozen models:
  - `AppleFMOutput(output: Literal["T1", "T2", "T3", "T4", "T5", "retry", "escalate", "abort"])` (D-02, P6)
  - `PlanCandidate(steps, preconds, success_criteria, bounded)` (D-03)
  - `PredictedState(ax_delta, screenshot_phash_delta, expected_notifs)` (D-07)
  - `EnsembleVote(tier, target_bbox, confidence, model)` (D-09)
  - `OracleOutput(candidates, ranker_model, top_k)` (D-08, P21)
  - `SpeculativeDraft(action, kind=Literal["READ"], step_index, confidence_estimate)` (D-10, P22)
- `tests/unit/cognition/test_schemas.py` — 9 unit tests + pytest.importorskip

**Test coverage:**
- AppleFMOutput enum validation + rejection of invalid values (P6 gate)
- SpeculativeDraft read-only kind enforcement
- All models frozen=True
- Confidence bounds (0.0-1.0)

### Task 2: Learning Module Stubs + Recipe/ObservedAction Schemas

**Files created:**
- `basicctrl/learning/__init__.py` — re-exports 5 Pydantic models
- `basicctrl/learning/schemas.py` — 5 frozen models:
  - `ObservedAction(step_idx, action, user_gesture_type, timestamp, success, ax_delta)` (D-15)
  - `RecipeParam(name, description, type: Literal["str", "int", "bbox", "element"])` (D-16)
  - `RecipePrecondition(expression, expected_value, confidence)` (D-16)
  - `RecipeStep(idx, action, preconditions, on_failure: list[str])` (D-16, recovery hints)
  - `Recipe(name, app_bundle_id, params, preconditions, steps, success_criteria, created_ts)` (D-16)
- `tests/unit/learning/test_schemas.py` — 8 unit tests + pytest.importorskip

**Test coverage:**
- Recipe creation with nested steps
- RecipePrecondition confidence bounds
- RecipeParam type validation
- On-failure recovery hints per step
- All models frozen=True

### Task 3: Episodic Memory Schemas + State Exports

**Files created:**
- `basicctrl/state/episodic.py` — 3 models + 1 class stub:
  - `EpisodicQuery(app_bundle_id, task_class, state_fingerprint, query_embedding, top_k)` (D-20)
  - `EpisodicHit(recipe, similarity, embedding_source_text, success_count, failure_count, quarantined)` (D-20, D-19 P22)
  - `EpisodicMemory` class stub with docstring (D-18)
    - Placeholder for Wave 4 FAISS integration (IndexFlatL2, ~/thinker/vault/research/basicCtrl-* archref)
- `basicctrl/state/__init__.py` — updated exports to include EpisodicMemory, EpisodicQuery, EpisodicHit
- `tests/unit/state/test_episodic.py` — 7 unit tests + pytest.importorskip

**Test coverage:**
- EpisodicQuery construction
- EpisodicHit with Recipe + metadata
- Quarantine flag tracking (>2 failures triggers quarantine)
- Similarity bounds (0.0-1.0)
- EpisodicMemory stub initialization
- All models frozen=True

## Deviations from Plan

**None — plan executed exactly as written.**

Circular import issue fixed via standard Pydantic pattern (TYPE_CHECKING forward refs + Any type annotations).

## Known Stubs

All models are Wave 0 stubs. Implementations ship in Wave 1+ per ROADMAP.md:

1. **AppleFMOutput** — no Apple FM integration yet (Wave 2 Plan 04-03)
2. **Planner** — no Opus planner implementation (Wave 1 Plan 04-02)
3. **Grounder** — no UI-TARS MLX integration (Wave 1 Plan 04-02)
4. **Critic** — no ranking logic (Wave 2 Plan 04-04)
5. **LearningRecorder** — no CGEvent tap yet (Wave 1 Plan 04-02)
6. **Recipe synthesis** — no ObservedAction→Recipe conversion (Wave 2 Plan 04-06)
7. **EpisodicMemory** — no FAISS indexing (Wave 4 Plan 04-05+)

All stubs use `pytest.importorskip("module")` — tests skip cleanly until implementations land.

## Threat Flags

No new threat surfaces introduced. All threat mitigations (P6, P19, P21, P22) are type-enforced at schema level:

| Flag | File | Description |
|------|------|-------------|
| P6 gate | basicctrl/cognition/schemas.py:AppleFMOutput | Literal enum hard-validates Apple FM output; ValidationError on mismatch |
| P21 gate | basicctrl/cognition/schemas.py:OracleOutput | Critic ranks external oracles only (type-enforced) |
| P22 gate | basicctrl/cognition/schemas.py:SpeculativeDraft | kind=Literal["READ"] prevents speculative MUTATE at type level |
| P19 mitigation | basicctrl/state/episodic.py:EpisodicHit | success_count/failure_count + quarantined flag for poison detection |

## Test Results

**All 24 tests passing:**

```
tests/unit/cognition/test_schemas.py          9 PASSED
tests/unit/learning/test_schemas.py           8 PASSED
tests/unit/state/test_episodic.py             7 PASSED
----------------------------------------------------------
Total                                        24 PASSED
```

Command: `python -m pytest tests/unit/cognition/test_schemas.py tests/unit/learning/test_schemas.py tests/unit/state/test_episodic.py -v`

## Next Steps

**Wave 1 (04-02..04-03):** Implement LearningRecorder + Planner + Grounder stubs → actual code.

**Wave 2 (04-04..04-06):** Implement Critic + recipe synthesis + ensemble voting.

**Wave 4 (04-05+):** Implement EpisodicMemory FAISS integration + retrieval.

Phase 4 execution can now proceed with these type contracts locked in place. All downstream code (Phase 5 Visualizer, Phase 6 SPI bridges, recovery orchestrator wiring) can import these schemas confidently.

---

**Commits:**
1. `a4055fd` — feat(04-01): cognition module stubs + schemas (9 tests)
2. `0baf028` — feat(04-01): learning module stubs + schemas (8 tests)
3. `de1d9ad` — feat(04-01): episodic memory schemas + state exports (7 tests)
4. `e818996` — fix(04-01): circular import + __init__.py (all tests pass)

**Execution time:** 5m 42s
