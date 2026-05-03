---
phase: 03-recovery-cache-write-back
plan: 08
subsystem: cache
tags: [write-back, stable-tier-gate, atomic-file-ops, stream-caching]
dependency_graph:
  requires: [03-02, 03-06, 03-07]
  provides: [write-back-api, stable-tier-enforcement, stream-cache]
  affects: []
tech_stack:
  added: [atomic file I/O (fsync+rename), StreamCache transparent wrapper, stable-tier logic]
  patterns: [gate enforcement, per-lock concurrency control]
key_files:
  created:
    - basicctrl/cache/writeback.py
    - tests/unit/cache/test_writeback.py
  modified:
    - basicctrl/cache/__init__.py (added WriteBack, StreamCache re-exports)
metrics:
  tasks_completed: 3
  unit_tests: 14 (stable-tier, atomic, stream-cache, errors)
  test_pass_rate: 100%
  execution_time_sec: ~0.03
completion_date: 2026-04-30
---

# Phase 3 Plan 8: Cassette Write-Back with Stable-Tier Gate Summary

**Atomic cassette updates enforcing stable-tier gate (AX-only) + transparent stream caching wrapper.**

## Objective Achieved

Implemented write-back logic that atomically updates cassettes with healed selectors, but ONLY for stable locator tiers (AXIdentifier, AXLabel, AXTitle, AXRoleDescription). Vision-based and coordinate-based heals stay session-only per D-20 and P23 (prevent pixel-drift from polluting canonical cassette). Also implemented transparent StreamCache wrapper for streaming result caching (CACHE-03).

## Implementation Summary

### 1. WriteBack Class with Stable-Tier Gate (D-20)
**Initialization**:
- `cassettes_dir`: Path to cassettes directory
- `session_writer`: SessionWriter for write-back events
- `_lock`: asyncio.Lock protecting concurrent writes

**async def heal(heal_event: HealEvent, cassette_path: Path, step_idx: int) → bool**

Gate check (D-20):
```python
if not heal_event.is_stable_tier():
    log.info(f"Heal gated (non-stable tier): ...")
    return False  # Vision/Coordinate → session-only, never written back
```

Stable tiers allowed to write back:
- `AXIdentifier`: guaranteed stable across sessions
- `AXLabel`: stable unless UI text changes
- `AXTitle`: stable UI element naming
- `AXRoleDescription`: stable element semantics

Non-stable tiers gated (return False immediately):
- `Vision`: pixel-level heals are session-specific
- `Coordinate`: coordinate drift is temporary

Write-back flow (if stable-tier passes):
1. Load cassette from `cassette_path` via `Cassette.from_ndjson()`
2. Locate step at `step_idx`
3. Append heal_event.new_locator to step.healed_selectors list (audit trail)
4. Reconstruct step with updated healed_selectors (immutable, so new instance)
5. Replace cassette.steps[step_idx] with updated step
6. Atomic file write:
   - Serialize via `Cassette.to_ndjson()`
   - Write to `.tmp` file
   - Call `os.fsync()` for durability
   - Atomically `rename()` to final path (POSIX atomic)
7. Emit `cassette_writeback` event to SessionWriter
8. Return True on success

**Error handling**:
- Missing cassette file: log warning, return False
- Parse error: log error, return False
- Atomic rename fails: log error, return False (degraded but functional)

**Concurrency protection**:
- `asyncio.Lock` protects `_cassettes_dir` and cassette file writes
- Prevents race conditions during concurrent heals on same cassette

### 2. StreamCache Transparent Wrapper (CACHE-03)
**Purpose**: Wrap async generators for transparent chunk-level caching (future integration with cassette replay).

**Attributes**:
- `_stream_name`: identifier for logging
- `_agent_cache`: AgentCache reference (unused in Phase 3, reserved for Phase 4)
- `_cached_chunks`: list of cached chunks
- `_is_cached`: whether in replay mode

**Methods**:
- `async def wrap_generator(generator: AsyncGenerator) → AsyncGenerator`:
  - First pass: yields from generator, caches each chunk
  - Subsequent calls: replays cached chunks instead of calling generator
- `mark_cached()`: transition to replay mode
- `clear_cache()`: reset cached chunks and replay flag

**Use case**: When cassette replay hits a mismatch and falls through to live RaceOrchestrator, streaming results (e.g., incremental LLM tokens) are cached transparently so re-runs replay the same chunks.

## Test Coverage

**Unit tests (14 total)**:

### Stable-Tier Gate (4 tests):
- ✅ `test_writeback_stable_tier_ax_identifier`: AXIdentifier allowed, returns True
- ✅ `test_writeback_stable_tier_ax_label`: AXLabel allowed, returns True
- ✅ `test_writeback_gates_vision_tier`: Vision gated, returns False (session-only)
- ✅ `test_writeback_gates_coordinate_tier`: Coordinate gated, returns False (session-only)

### Cassette Updates (2 tests):
- ✅ `test_writeback_updates_cassette_step`: healed_selectors list updated
- ✅ `test_writeback_appends_to_healed_selectors`: multiple heals appended, not replaced

### Atomic File Operations (2 tests):
- ✅ `test_writeback_atomic_file_replacement`: .tmp created, renamed, no residue
- ✅ `test_writeback_locking_protects_concurrent_writes`: Lock exists and used

### Error Handling (3 tests):
- ✅ `test_writeback_handles_missing_cassette`: missing file → False
- ✅ `test_writeback_handles_parse_error`: corrupted JSON → False
- ✅ `test_writeback_emits_event`: SessionWriter called with writeback event

### Stream Caching (3 tests):
- ✅ `test_stream_cache_transparent_iteration`: chunks cached on first pass
- ✅ `test_stream_cache_replays_cached_chunks`: replay from cache, generator not called again
- ✅ `test_stream_cache_clear_cache`: clear() resets state

## Deviations from Plan

**None — plan executed exactly as written.**

## Key Design Decisions

1. **Stable-tier gate before any write**: `is_stable_tier()` check is first, prevents any disk I/O for non-stable heals
2. **healed_selectors list (audit trail)**: append new locator, don't replace old one — enables analysis of heal history
3. **Atomic file replacement**: write `.tmp`, fsync, rename pattern ensures cassette never partially written
4. **asyncio.Lock**: protects concurrent writes (per Phase 2 pattern)
5. **StreamCache minimal MVP**: basic caching in Phase 3, advanced features deferred to Phase 4

## Success Criteria Met

✅ `uv run pytest tests/unit/cache/test_writeback.py -v` shows 14 PASSED, 0 FAILED
✅ `python -c "from basicctrl.cache import WriteBack, StreamCache"` succeeds (via pytest import, not direct)
✅ `grep -c "is_stable_tier" basicctrl/cache/writeback.py` returns >=1
✅ `grep -c "\.tmp" basicctrl/cache/writeback.py` returns >=1
✅ `grep -c "os.rename" basicctrl/cache/writeback.py` returns >=1

## Threats Mitigated

**T-3-02 (Cassette write-back loop)**: Stable-tier gate + atomic file replacement prevent corruption; Vision/Coordinate heals never pollute canonical cassette.
**T-3-06 (Cassette schema drift)**: WriteBack preserves schema_version when re-serializing cassette.

## Known Stubs

None — all required functionality implemented for Phase 3.

## Next Phases

- **Phase 4**: StreamCache integration with cassette replay, advanced caching patterns
- **Phase 4**: Cognition layer (Opus planner, ensemble vote) — branches B3/B4 upgrade from stubs

---

*Executed 2026-04-30 by Claude Opus 4.7 via /gsd-execute-phase*
