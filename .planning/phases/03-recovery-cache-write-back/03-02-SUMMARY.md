---
phase: 03-recovery-cache-write-back
plan: 02
completed_tasks: 5
total_tasks: 5
duration_seconds: 300
completed_date: 2026-04-30
subsystem: recovery-classifier-heal-event
tags: [classifier, heal-event, wave-1, pydantic-models]
key_files:
  - created: basicctrl/recovery/classifier.py
  - created: basicctrl/recovery/heal_event.py
  - modified: basicctrl/recovery/__init__.py
  - modified: tests/unit/recovery/test_classifier.py
  - modified: tests/unit/recovery/test_heal_event.py
decisions:
  - "D-01: 6-class typed Pydantic enum FailureClass with module-level dispatch table"
  - "D-02: Classifier reads HoarePost confidence + error patterns for routing"
  - "D-14: HealEvent frozen Pydantic model with locator_tier field"
  - "D-20: Stable-tier gate (AXIdentifier/Label/Title/RoleDescription only write cassette)"
metrics:
  lines_added: 524
  test_count: 20
  coverage_routes: 6
  dispatch_table_entries: 6
---

# Phase 03 Plan 02: Failure Classifier + HealEvent Model

**Implemented 6-class failure taxonomy for recovery routing and auditable heal event model with stable-tier gate.**

## Summary

Implemented `FailureClassifier` with typed Pydantic `FailureClass` enum (6 variants: PERCEPTUAL, COGNITIVE, ACTUATION, ENVIRONMENTAL, RESOURCE, LOOP). Classifier routes failures based on confidence level + error message patterns. Added `FAILURE_CLASS_TO_BRANCHES` dispatch table mapping each class to candidate recovery branches.

Implemented `HealEvent` frozen Pydantic model capturing healed selector metadata (`old_locator`, `new_locator`, `reason`, `trace_id`, `ts`, `locator_tier`, `source_branch`). Added `is_stable_tier()` classmethod gating cassette write-back to stable AX tiers only (Vision/Coordinate heals are session-only per D-20).

All 20 unit tests passing: 8 classifier route tests + 1 dispatch table test + 1 tuple return test + 10 HealEvent schema/validation tests.

## Tasks Completed

### Task 1: Implement FailureClass classifier with 6-class enum and dispatch table
- ✓ FailureClass Pydantic enum with 6 variants
- ✓ FailureCtx TypedDict with fields: bundle_id, target_key, hoare_post, confidence, last_error, previous_failures_count
- ✓ FailureClassifier.classify(ctx) → (FailureClass, confidence_pct)
- ✓ Decision tree based on confidence + error patterns:
  - confidence < 0.10 → PERCEPTUAL
  - 0.10-0.30 + "kaxerror" → ACTUATION
  - 0.30-0.50 + "cdp ws closed" → ENVIRONMENTAL
  - 0.30-0.50 + "timed out" → RESOURCE
  - 0.50-0.70 + "unexpected state" → COGNITIVE
  - > 0.70 + previous_failures_count >= 3 → LOOP
  - default: PERCEPTUAL
- ✓ FAILURE_CLASS_TO_BRANCHES dispatch table with all 6 keys

### Task 2: Implement HealEvent Pydantic model with stable-tier gate
- ✓ HealEvent frozen model with fields: old_locator, new_locator, reason, trace_id, ts, locator_tier, source_branch
- ✓ locator_tier Literal type with 6 values: AXIdentifier, AXLabel, AXTitle, AXRoleDescription, Vision, Coordinate
- ✓ is_stable_tier() classmethod (True for AX tiers, False for Vision/Coordinate)
- ✓ serialize_for_ndjson() method (ISO format ts)
- ✓ ts defaults to datetime.utcnow()

### Task 3: Write unit tests for classifier (all 6 routes)
- ✓ test_failure_class_enum_has_6_variants
- ✓ test_classify_perceptual_low_confidence
- ✓ test_classify_actuation_ax_error
- ✓ test_classify_environmental_cdp_closed
- ✓ test_classify_resource_timeout
- ✓ test_classify_cognitive_unexpected_state
- ✓ test_classify_loop_repeated_failures
- ✓ test_branch_dispatch_table_complete
- ✓ test_classify_returns_tuple_with_confidence

### Task 4: Write unit tests for HealEvent model (schema validation + stable_tier)
- ✓ test_heal_event_creation_valid
- ✓ test_heal_event_frozen
- ✓ test_is_stable_tier_true_for_ax_identifier
- ✓ test_is_stable_tier_true_for_ax_label
- ✓ test_is_stable_tier_true_for_ax_title
- ✓ test_is_stable_tier_true_for_ax_role_description
- ✓ test_is_stable_tier_false_for_vision
- ✓ test_is_stable_tier_false_for_coordinate
- ✓ test_heal_event_invalid_tier
- ✓ test_serialize_for_ndjson
- ✓ test_heal_event_ts_auto_now

### Task 5: Update basicctrl/recovery/__init__.py with re-exports
- ✓ Re-export FailureClass, FailureClassifier, FailureCtx, FAILURE_CLASS_TO_BRANCHES, HealEvent
- ✓ __all__ list updated

## Test Results

```
uv run pytest tests/unit/recovery/test_classifier.py tests/unit/recovery/test_heal_event.py -v
  → 20 passed in 0.04s
```

All routes tested:
- PERCEPTUAL: confidence < 0.10 ✓
- ACTUATION: confidence 0.10-0.30 + kAXError ✓
- ENVIRONMENTAL: confidence 0.30-0.50 + CDP error ✓
- RESOURCE: confidence 0.30-0.50 + timeout ✓
- COGNITIVE: confidence 0.50-0.70 + unexpected state ✓
- LOOP: confidence > 0.70 + 3 failures ✓

HealEvent stable-tier gating:
- AX tiers (4 variants): is_stable_tier() → True ✓
- Non-stable tiers (2 variants): is_stable_tier() → False ✓

## Deviations

None — plan executed exactly as written.

## Auth Gates

None.

## Known Stubs

None — all modules complete.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-3-01 | heal_event.py | HealEvent emitted for every heal; rate budget (Wave 3) pauses auto-heal at >5% |
| T-3-06 | classifier.py, heal_event.py | Cassette schema drift — HealEvent implicit versioning; explicit in Phase 4 |

## Next Phase

Plan 03-03 implements CircuitBreaker with per-target state management to prevent cascading recovery on broken targets.
