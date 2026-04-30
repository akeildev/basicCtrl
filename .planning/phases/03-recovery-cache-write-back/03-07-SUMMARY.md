---
phase: 03-recovery-cache-write-back
plan: 07
subsystem: cache
tags: [cassette-replay, phash-matching, mismatch-detection, fallthrough]
dependency_graph:
  requires: [03-05, 03-06]
  provides: [replay-engine, phash-diff-logic, fallthrough-pattern]
  affects: [03-08]
tech_stack:
  added: [Hamming distance (perceptual hash diff), pHash threshold (8 bits)]
  patterns: [step-by-step replay, early termination on mismatch]
key_files:
  created:
    - cua_overlay/cache/replay.py
    - tests/unit/cache/test_replay.py
  modified:
    - cua_overlay/cache/__init__.py (added CassetteReplayEngine re-export)
metrics:
  tasks_completed: 3
  unit_tests: 14 (hamming + replay + errors + edge cases)
  test_pass_rate: 100%
  execution_time_sec: ~0.03
completion_date: 2026-04-30
---

# Phase 3 Plan 7: Cassette Replay Engine Summary

**Deterministic replay with pHash-based step matching and fallthrough to live execution.**

## Objective Achieved

Implemented cassette replay that deterministically re-executes recorded action sequences. Detects step mismatches by comparing actual screenshot pHash to recorded pHash using Hamming distance (8-bit threshold per D-23). On first mismatch, halts replay and falls through to live RaceOrchestrator execution. This enables fast-path cache hits (skip planning) while gracefully degrading to live execution when cached recipes are stale.

## Implementation Summary

### 1. Hamming Distance Helper (D-23)
- `hamming_distance(h1: str, h2: str) -> int`: bit-level XOR comparison
- Converts hex pHash strings to binary and counts differing bits
- Returns 0-64 for 64-bit hashes (empirically, 8-bit threshold detects real drifts on Tahoe)
- Robust to unequal length hashes (pads with zeros)

### 2. CassetteReplayEngine (D-19, D-23)
**Initialization**:
- `cassette`: Cassette instance to replay
- `race_orchestrator`: RaceOrchestrator for fallthrough on mismatch
- `l1_cheap`: L1CheapDiff for screenshot pHash snapshot
- `session_writer`: SessionWriter for replay events
- `target_pid`, `bundle_id`: app context
- `_phash_threshold = 8` (D-23 empirically derived threshold)

**async def replay() → (success: bool, first_mismatch_step_idx: Optional[int], replay_events: List[dict])**

Core loop:
```python
for step_idx, step in enumerate(cassette.steps):
    # Replay: execute recorded action via race_orchestrator
    outcome = await race_orchestrator.execute(...)
    
    # Verify: take screenshot, compute pHash
    current_snapshot = await l1_cheap.snapshot(target_pid, bundle_id)
    current_phash = current_snapshot["phash"]
    
    # Match: Hamming distance
    hamming = hamming_distance(recorded_phash, current_phash)
    if hamming > phash_threshold:
        # Mismatch → stop replay, return
        return (False, step_idx, replay_events)
    
    # Match → continue to next step
    emit "cassette_step_replay_ok" event
```

**Error handling**:
- Missing or None pHash: treat as mismatch, don't crash
- Screenshot capture failure: log and fallthrough
- RaceOrchestrator.execute error: log and fallthrough
- All errors result in (False, step_idx, events) — graceful degradation

**Event emission**:
- `cassette_step_replay_ok`: includes step_idx, hamming distance
- `cassette_mismatch`: includes step_idx, hamming, threshold, phashes
- Events streamed to SessionWriter for observability

## Test Coverage

**Unit tests (14 total)**:

### Hamming Distance (4 tests):
- ✅ `test_hamming_distance_identical`: identical hashes → 0
- ✅ `test_hamming_distance_single_bit`: 1 bit difference → 1
- ✅ `test_hamming_distance_multiple_bits`: 4 bits (single hex digit)
- ✅ `test_hamming_distance_threshold_boundary`: exactly 8 bits

### Replay Matching (2 tests):
- ✅ `test_replay_all_steps_match`: all steps match, return (True, None, events)
- ✅ `test_replay_detects_mismatch_on_step_2`: step 0 ok, step 1 mismatch, halt early

### Threshold Boundaries (1 test):
- ✅ `test_replay_hamming_threshold_boundary`: verify 8-bit gate works

### Error Handling (3 tests):
- ✅ `test_replay_handles_missing_phash`: None pHash → mismatch
- ✅ `test_replay_handles_screenshot_capture_failure`: snapshot() raises → mismatch
- ✅ `test_replay_handles_race_orchestrator_failure`: execute() raises → mismatch

### Edge Cases (4 tests):
- ✅ `test_replay_empty_cassette`: 0 steps → (True, None, [])
- ✅ `test_replay_preserves_action_ordering`: execute called in step order
- ✅ `test_replay_mismatch_halts_early`: mismatch at step 2 halts, execute called only 3 times (not all 5)
- ✅ `test_replay_includes_hamming_distance_in_mismatch_event`: event has "hamming" field for debugging

## Deviations from Plan

**None — plan executed exactly as written.**

## Key Design Decisions

1. **pHash threshold = 8 bits**: Empirically derived per D-23 to balance drift detection vs. false positives
2. **Early termination**: First mismatch stops replay immediately (no partial execution)
3. **Errors → mismatches**: Any error during replay/verification triggers fallthrough (no crashing)
4. **Event streaming**: Every step generates an event for observability (enables metrics, RL training)
5. **Hamming distance**: Bit-level comparison more robust than string equality

## Success Criteria Met

✅ `uv run pytest tests/unit/cache/test_replay.py -v` shows 14 PASSED, 0 FAILED
✅ `python -c "from cua_overlay.cache import CassetteReplayEngine"` succeeds
✅ `grep -c "phash_threshold.*8" cua_overlay/cache/replay.py` returns >=1
✅ `grep -c "hamming_distance" cua_overlay/cache/replay.py` returns >=2

## Threats Mitigated

**T-3-02 (Cassette write-back loop)**: Replay detects mismatch → fallthrough to live execution prevents infinite replay of stale cache.

## Next Steps

- **Plan 03-08**: WriteBack with stable-tier gate (AX-only) and stream caching

---

*Executed 2026-04-30 by Claude Opus 4.7 via /gsd-execute-phase*
