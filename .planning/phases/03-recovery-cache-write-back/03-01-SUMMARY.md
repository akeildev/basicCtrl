---
phase: 03-recovery-cache-write-back
plan: 01
completed_tasks: 3
total_tasks: 3
duration_seconds: 180
completed_date: 2026-04-30
subsystem: recovery-scaffold
tags: [module-init, test-fixtures, wave-0]
key_files:
  - created: basicctrl/recovery/__init__.py
  - created: tests/unit/recovery/conftest.py
  - created: tests/unit/recovery/__init__.py
  - created: tests/unit/recovery/test_classifier.py
  - created: tests/unit/recovery/test_branches.py
  - created: tests/unit/recovery/test_orchestrator.py
  - created: tests/unit/recovery/test_circuit_breaker.py
  - created: tests/unit/recovery/test_heal_event.py
decisions: []
metrics:
  lines_added: 175
  test_count: 5
  skip_pattern_used: true
---

# Phase 03 Plan 01: Recovery Module Scaffold + Test Fixtures

**Established module structure for Phase 3 recovery subsystem with Wave-0 test stubs and shared pytest fixtures.**

## Summary

Created `basicctrl/recovery/` module with docstring describing subsystem architecture. Established test fixture pattern at `tests/unit/recovery/conftest.py` with 5 shared fixtures for mocking Phase 1/2 dependencies. Created Wave-0 test stub files with `pytest.importorskip()` pattern so tests collect gracefully until real modules ship in Wave 1.

Module structure ready for Wave 1 tasks:
- `classifier.py` — 6-class FailureClass enum + dispatch table
- `heal_event.py` — HealEvent Pydantic model
- `circuit_breaker.py` — per-target failure counter
- `branches/` — 5 recovery branch modules (B1-B5)
- `orchestrator.py` — parallel recovery fan-out

## Tasks Completed

### Task 1: Create recovery module scaffold
- ✓ `basicctrl/recovery/__init__.py` with subsystem docstring
- ✓ Module docstring describes 5 submodules and their roles

### Task 2: Create pytest fixtures for recovery unit tests
- ✓ `failure_ctx_factory` fixture (builds FailureCtx dicts)
- ✓ `verifier_mock` fixture (AsyncMock for Aggregator.verify)
- ✓ `session_writer_mock` fixture (AsyncMock for SessionWriter.append_action_log)
- ✓ `idempotency_store_mock` fixture (AsyncMock for Phase 2 IdempotencyTokenStore)
- ✓ `axmgr_mock` fixture (AsyncMock for Phase 1 AXObserverManager)

### Task 3: Create test package structure with Wave-0 stubs
- ✓ `tests/unit/recovery/__init__.py`
- ✓ 5 Wave-0 stub test files with importorskip pattern:
  - test_classifier.py
  - test_branches.py
  - test_orchestrator.py
  - test_circuit_breaker.py
  - test_heal_event.py

## Verification

All Wave-0 stubs use `pytest.importorskip()` pattern:
```
tests/unit/recovery/ --collect-only -q
  → 5 test files collected, 5 skipped (import guard)
```

Fixtures importable and used by placeholder tests:
```
python -c "import basicctrl.recovery; from tests.unit.recovery.conftest import failure_ctx_factory"
  → succeeds
```

## Deviations

None — plan executed exactly as written.

## Auth Gates

None.

## Known Stubs

None — all Wave-0 stubs are intentional (will be replaced by Wave 1).

## Threat Flags

None at scaffold stage.

## Next Phase

Plan 03-02 builds on this scaffold by implementing:
- FailureClass classifier with 6-class enum
- HealEvent model with stable-tier gate
- Unit tests replacing Wave-0 stubs
