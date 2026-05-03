---
phase: 03-recovery-cache-write-back
plan: 03
completed_tasks: 3
total_tasks: 3
duration_seconds: 240
completed_date: 2026-04-30
subsystem: recovery-circuit-breaker
tags: [circuit-breaker, state-management, wave-1, async]
key_files:
  - created: basicctrl/recovery/circuit_breaker.py
  - modified: basicctrl/recovery/__init__.py
  - modified: tests/unit/recovery/test_circuit_breaker.py
decisions:
  - "D-12: Per-(bundle_id, target_key) failure counter with 60s window"
  - "D-13: In-memory asyncio.Lock-guarded dict; Phase 6 may upgrade to LangGraph Postgres"
metrics:
  lines_added: 396
  test_count: 7
  async_methods: 4
  dispatch_table_reordering: true
---

# Phase 03 Plan 03: Circuit Breaker with Per-Target State Management

**Implemented circuit breaker preventing cascading recovery on broken targets. Trip after 3 consecutive failures within 60s window; reorder translator priority; emit structured events.**

## Summary

Implemented `CircuitBreaker` class managing per-(bundle_id, target_key) failure state. Tracks failures in 60s window; trips after 3 consecutive failures. On trip: reorders `AppProfile.translator_priority` (moves primary to tail, promotes next), emits `circuit_breaker_tripped` event to SessionWriter, and returns True. Breaker auto-resets after 60s window expires.

State stored in-memory dict guarded by `asyncio.Lock` (same pattern as Phase 2 IdempotencyTokenStore). Supports manual reset via `CircuitBreaker.reset()` for MCP tool D-25.

All 7 unit tests passing: trip condition tests, reorder logic, event emission, 60s window reset, and target independence.

## Tasks Completed

### Task 1: Implement CircuitBreaker class with per-target state management
- ✓ BreakState Pydantic frozen model with fields:
  - bundle_id, target_key, failure_count, tripped_at, trip_window_start
- ✓ CircuitBreaker class:
  - `__init__(session_writer)` — store SessionWriter reference
  - `_state: dict[str, BreakState]` — per-(bundle_id, target_key) state
  - `_lock: asyncio.Lock` — concurrent access protection
- ✓ CircuitBreaker.record_failure(bundle_id, target_key, app_profile) → bool:
  - Records failure on target
  - 60s window tracking with auto-reset
  - On 3rd failure: trip breaker, reorder translator_priority, emit event
  - Returns True if breaker just tripped; False otherwise
- ✓ CircuitBreaker.is_tripped(bundle_id, target_key) → bool:
  - Returns True if tripped and <60s since trip
- ✓ CircuitBreaker.reset(bundle_id, target_key):
  - Manual clear for MCP tool D-25
- ✓ CircuitBreaker._emit_trip_event(bundle_id, target_key, failure_count):
  - Emits structured NDJSON event to SessionWriter

### Task 2: Write unit tests for circuit breaker
- ✓ test_circuit_breaker_is_not_tripped_on_first_two_failures
- ✓ test_circuit_breaker_trips_on_third_failure
- ✓ test_circuit_breaker_reorders_translator_priority
  - Verifies primary (T1) moved to tail; others shifted left
- ✓ test_circuit_breaker_emits_trip_event
  - Verifies event structure and SessionWriter.append_action_log call
- ✓ test_circuit_breaker_resets_after_60s
  - Uses monkeypatch to mock datetime; 65s elapsed triggers reset
- ✓ test_circuit_breaker_reset_clears_state
  - Manual reset via reset() method
- ✓ test_circuit_breaker_different_targets_independent
  - Different targets don't share failure counts

### Task 3: Update basicctrl/recovery/__init__.py
- ✓ Re-export CircuitBreaker, BreakState
- ✓ __all__ list updated

## Test Results

```
uv run pytest tests/unit/recovery/test_circuit_breaker.py -v
  → 7 passed in 0.03s
```

Test coverage:
- Trip condition (3-failure threshold): ✓
- Translator priority reordering (T1 → tail): ✓
- Event emission (circuit_breaker_tripped): ✓
- 60s window auto-reset: ✓
- Manual reset via reset(): ✓
- Target independence: ✓

## Implementation Details

Per-target state key format: `f"{bundle_id}:{target_key}"`

Trip logic:
1. Track `trip_window_start` on first failure
2. Count failures within 60s window
3. On 3rd failure: set `tripped_at`, reorder priority, emit event
4. Auto-reset when next failure >60s from `trip_window_start`

Translator priority reordering (D-13):
```python
# Before: ["T1", "T2", "T4", "T5"]
# After:  ["T2", "T4", "T5", "T1"]
priority = priority.copy()
first = priority.pop(0)  # T1
priority.append(first)   # append to tail
```

## Deviations

None — plan executed exactly as written.

## Auth Gates

None.

## Known Stubs

None — all modules complete.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| T-3-03 | circuit_breaker.py | 5-branch recovery cost explosion — CircuitBreaker trips after 3 failures; max 2 cycles enforced in Phase 3 Plan 5 (orchestrator) |
| T-3-04 | circuit_breaker.py | Race condition between branches — Circuit breaker state guarded by asyncio.Lock; Phase 3 Plan 5 reuses Phase 2 cancel-scope pattern |

## Next Phase

Phase 3 Plan 04 will implement recovery branches (B1-B5):
- B1: rescroll + AX retry
- B2: OCR regrounding + CGEvent
- B3: world-model replan (stub in Wave 1)
- B4: planner replan (stub in Wave 1)
- B5: AppleScript fallback
