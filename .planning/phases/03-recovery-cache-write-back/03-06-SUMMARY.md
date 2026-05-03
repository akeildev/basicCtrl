---
phase: 03-recovery-cache-write-back
plan: 06
subsystem: cache
tags: [agent-cache, cassette, schema-versioning, persistence]
dependency_graph:
  requires: [03-02, 03-05]
  provides: [agent-cache-api, cassette-format, ndjson-serialization]
  affects: [03-07, 03-08]
tech_stack:
  added: [asyncio.Lock, Pydantic frozen models, NDJSON serialization]
  patterns: [per-feature sub-packages, atomic file I/O (.tmp+fsync+rename)]
key_files:
  created:
    - basicctrl/cache/__init__.py
    - basicctrl/cache/key.py
    - basicctrl/cache/cassette.py
    - basicctrl/cache/agent_cache.py
    - tests/unit/cache/conftest.py
    - tests/unit/cache/test_agent_cache.py
    - tests/unit/cache/test_cassette.py
  modified:
    - tests/unit/cache/__init__.py
metrics:
  tasks_completed: 7
  unit_tests: 20 (18 tests from plan + 2 edge cases)
  test_pass_rate: 100%
  execution_time_sec: ~0.03
completion_date: 2026-04-30
---

# Phase 3 Plan 6: AgentCache Port + Cassette Definition Summary

**SHA-256 keyed cache with NDJSON serialization + schema versioning for self-healing cassettes.**

## Objective Achieved

Ported Stagehand's AgentCache pattern to Python, storing cassettes on disk under `~/.cua/sessions/<id>/cassettes/` with SHA-256 keys derived from `(bundle_id, role_path, instruction)`. Defined Cassette NDJSON format capturing step-level action records (Hoare triples, visual state, healed selectors). Implemented schema versioning (P-06 mitigation) and thread-safe disk I/O via atomic file operations.

## Implementation Summary

### 1. Cache Key Computation (D-17)
- `compute_cache_key(bundle_id, role_path, instruction) -> str`: deterministic SHA-256 hashing
- 64-character hex digest for content-addressed storage
- Ensures cache hits across identical goals in different sessions

### 2. Cassette Data Model (D-18)
**CassetteStep Pydantic model** (frozen, immutable):
- `step_idx`: ordinal position in sequence
- `hoare_pre`: pre-condition (HoarePre from Phase 1 STATE-02)
- `action_canonical`: action record (ActionCanonical from Phase 1)
- `hoare_post`: post-condition with verifier confidence
- `screenshot_phash`: perceptual hash of resulting screenshot (for replay matching)
- `ax_subtree_hash`: structural hash of AX element (for verification)
- `healed_selectors`: list of selectors updated during recovery (initially empty, filled by Plan 03-08 write-back)

**Cassette container class**:
- `schema_version = "1.0"` (class constant, bumped on format changes)
- `steps`: list of CassetteStep objects
- `cache_key`: SHA-256 identifier
- `bundle_id`, `instruction`: metadata for traceability

### 3. NDJSON Serialization (D-18)
- First line: `{"_metadata": {"schema_version": "1.0", "cache_key": "...", ...}}`
- Subsequent lines: one JSON line per CassetteStep
- Full roundtrip via `to_ndjson()` / `from_ndjson()`
- Schema version validation on load (warns on mismatch, doesn't crash)

### 4. AgentCache Disk Persistence (D-17)
**AgentCache class**:
- In-memory dict `_cache` for fast lookups
- Disk storage under `_cassettes_dir / f"{cache_key}.jsonl"`
- `asyncio.Lock` protecting concurrent get/put/clear
- `async def get(bundle_id, role_path, instruction) -> Optional[Cassette]`
  - Returns from memory if present
  - Falls back to disk, deserializes, populates memory
  - Returns None on miss or parse error (graceful degradation)
- `async def put(cassette: Cassette) -> None`
  - Serializes cassette to NDJSON
  - Writes to `.tmp` file, calls `os.fsync()`, atomically `rename()` to final path
  - Updates in-memory cache
- `async def clear(cache_key: str) -> None`
  - Deletes disk file and removes from memory cache

**Error handling**:
- Corrupted files: log warning, treat as cache miss
- Disk write failures: log error, continue (degraded but functional)
- Missing directories: create automatically

## Test Coverage

**Unit tests (20 total)**:

### AgentCache (9 tests):
- ✅ `test_cache_put_get_roundtrip`: verify get() returns put() result
- ✅ `test_cache_miss_returns_none`: non-existent key returns None
- ✅ `test_cache_persists_to_disk`: file created at correct path
- ✅ `test_cache_loads_from_disk`: new instance loads from disk
- ✅ `test_cache_locking_prevents_race`: Lock exists and is acquired
- ✅ `test_cache_clear_removes_disk_file`: file deleted, memory cleared
- ✅ `test_cache_handles_corrupted_file`: graceful degradation on JSON error
- ✅ `test_compute_cache_key_deterministic`: same input → same key
- ✅ `test_compute_cache_key_differs_on_change`: different input → different key

### Cassette (11 tests):
- ✅ `test_cassette_creation`: empty cassette constructor
- ✅ `test_cassette_add_step`: append steps to list
- ✅ `test_cassette_to_ndjson`: serialize with metadata + step lines
- ✅ `test_cassette_from_ndjson`: deserialize, reconstruct steps
- ✅ `test_cassette_schema_version_metadata`: version in metadata line
- ✅ `test_cassette_validates_schema_version_on_load`: warns on mismatch
- ✅ `test_cassette_preserves_healed_selectors`: list survives roundtrip
- ✅ `test_cassette_phash_roundtrip`: pHash preserved
- ✅ `test_cassette_handles_empty_steps`: empty cassette serializes
- ✅ `test_cassette_malformed_json_raises`: invalid JSON → error
- ✅ `test_cassette_missing_metadata_raises`: no _metadata → error

## Deviations from Plan

**None — plan executed exactly as written.**

## Key Design Decisions

1. **Frozen Pydantic models**: CassetteStep immutable for safe serialization
2. **Asyncio.Lock**: Per Phase 2 pattern for concurrent access (not thread-safe, but event-loop safe)
3. **Graceful degradation**: Corrupted cassettes treated as cache misses, not errors
4. **.tmp + fsync + rename**: POSIX atomic file replacement ensures no partial/corrupted cassettes on disk
5. **Per-feature sub-packages**: `basicctrl/cache/` with re-exports in `__init__.py` for clean imports

## Success Criteria Met

✅ `uv run pytest tests/unit/cache/ -v` shows 20 PASSED, 0 FAILED
✅ `python -c "from basicctrl.cache import AgentCache, Cassette, compute_cache_key"` succeeds
✅ `grep -c "schema_version" basicctrl/cache/cassette.py` returns >=3
✅ `grep -c "asyncio.Lock" basicctrl/cache/agent_cache.py` returns >=1

## Threats Mitigated

**T-3-06 (Cassette schema drift)**: Cassettes include `schema_version` field; replay validates on load and warns on mismatch (P-06).

## Next Steps

- **Plan 03-07**: CassetteReplayEngine with pHash-based matching and fallthrough
- **Plan 03-08**: WriteBack with stable-tier gate (AX-only) and atomic updates

---

*Executed 2026-04-30 by Claude Opus 4.7 via /gsd-execute-phase*
