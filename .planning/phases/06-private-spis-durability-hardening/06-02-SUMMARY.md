---
phase: 06
plan: 02
subsystem: private-spis-durability-hardening
tags: [spi-channel, skylight, background-events, capability-gating]
dependency_graph:
  requires: [06-01]
  provides: [SPI-01-C1-channel]
  affects: [Phase-6-Wave-2-parallel-integration]
tech_stack:
  added: [basicctrl/spi/skylight.py, basicctrl/actions/channels/c1_skylight_spi.py]
  patterns: [ctypes-dlsym-bridge, singleton-pattern, capability-gating, graceful-fallback]
key_files:
  created:
    - basicctrl/spi/skylight.py (SkyLightBridge + get_skylight_bridge + is_skylight_available)
    - basicctrl/actions/channels/c1_skylight_spi.py (C1SkyLightSPI channel variant)
    - tests/test_spi_skylight.py (11 unit tests covering bridge + channel + registration)
  modified:
    - basicctrl/actions/channel_registry.py (added register_with_capabilities method)
decisions:
  - "SkyLight bridge uses ctypes.CDLL(None) + dlsym pattern for symbol lookup (live at runtime, per RESEARCH.md)"
  - "Singleton pattern via global _bridge variable cached at first get_skylight_bridge() call"
  - "Graceful fallback to public CGEvent.postToPid when SkyLight unavailable (PITFALL P17 mitigation)"
  - "C1SkyLightSPI channel registered ONLY when capabilities.skylight_available=True (capability gating)"
  - "Channel protocol maintained stable (async fire signature from base.py) — Phase 2 channels unaffected"
  - "Fallback returns bool to distinguish SkyLight vs fallback path for observability (via_spi flag)"
metrics:
  duration_minutes: ~20
  tasks_completed: 3
  files_created: 3
  files_modified: 1
  tests_passing: 11
  tests_unit_regression: 39 (Phase 2 channels still pass)
  coverage: SPI-01 (SkyLight) fully implemented with capability probe gating
completed_date: 2026-05-01
completion_status: success
---

# Phase 6 Plan 02 — SkyLight SPI Bridge + C1 Channel Variant

**One-liner:** SkyLight SLEventPostToPid ctypes bridge with graceful public-API fallback, registered as C1_SPI when available.

## Summary

Wave 1 formalizes SkyLight integration from Phase 2, adding proper capability gating per PITFALL-17 (SkyLight version-fragility):

### Task 1: SkyLight SPI Wrapper + ctypes Bridge

**Status:** ✅ COMPLETE

**File:** `basicctrl/spi/skylight.py` (108 LOC)

**Implementation:**
- `SkyLightBridge` class wraps `SLEventPostToPid` symbol via ctypes.CDLL(None) + dlsym
- Constructor takes `available: bool` from probe.py capability check; gates symbol lookup
- `post_to_pid(pid, event)` fires background event via SkyLight OR falls back to public CGEvent.postToPid
- Returns `bool`: True if delivered via SkyLight; False if fallback used (still succeeds, cursor visible)
- Async wrapper via `asyncio.to_thread()` — sync ctypes calls don't block event loop
- `get_skylight_bridge(capabilities)` singleton caches bridge at module level
- `is_skylight_available(capabilities)` exposed for channel_registry gating

**Key design:**
- Per PITFALL P17: capability probe runs at session start (probe.py); this module just uses the result
- Per ARCHITECTURE.md L8: every SPI has public-API fallback — no SPIs gate features (C3 always works)
- Graceful degradation: if symbol lookup fails, sets `available=False` and falls back silently
- Structured logging at INFO level for observability

**Tests:** ✅ 6 unit tests
- `test_skylight_bridge_init_when_available` — bridge initializes with available=True
- `test_skylight_bridge_init_when_unavailable` — gracefully handles unavailable=False
- `test_skylight_bridge_post_to_pid_fallback` — fallback path verified
- `test_get_skylight_bridge_caches` — singleton pattern verified
- `test_is_skylight_available` — public API works

### Task 2: C1 SPI Channel Variant + Channel Registry Integration

**Status:** ✅ COMPLETE

**Files:**
- `basicctrl/actions/channels/c1_skylight_spi.py` (132 LOC)
- `basicctrl/actions/channel_registry.py` (modified +15 LOC)

**Implementation:**
- `C1SkyLightSPI` class implements Channel protocol (async fire signature from base.py)
- Inherits idempotency pattern: try_claim() before fire, pre-syscall kill-switch (cancel_event.is_set())
- Delegates to SkyLightBridge for actual event delivery
- Returns ChannelOutcome with status='fired' on success (or 'skipped'/'cancelled'/'errored')
- Metadata: name="C1", spi_name="C1_SPI", description="SkyLight SLEventPostToPid (SPI)"

**Channel Registry Integration:**
- New method `register_with_capabilities(capabilities)` async
- Checks `capabilities.skylight_available` and registers C1SkyLightSPI IFF True
- Graceful: if SkyLight unavailable, channel simply not registered; Phase 2 C1 (public CGEvent) still works
- Logs registration at INFO level

**Key design:**
- Channel signature stable (async fire) — Phase 2 channels unaffected by this SPI variant
- Capability gating at registry level — orchestrator never sees unavailable channels
- C1SkyLightSPI delegates CGEvent construction to Phase 2 C1 pattern (reuses logic)
- Per ARCHITECTURE.md L91-92 default binding: T4 → C1 (background, no cursor warp)

**Tests:** ✅ 5 unit tests
- `test_c1_spi_channel_fires` — fire() succeeds with mocked bridge
- `test_c1_spi_channel_rejects_idempotency_loss` — idempotency claim failure → skipped
- `test_c1_spi_channel_respects_cancel_event` — pre-syscall kill-switch honored
- `test_c1_spi_channel_missing_bbox` — validation of grounded_bbox
- `test_c1_spi_channel_name` / `test_c1_spi_channel_description` — metadata verified

### Task 3: Unit Tests

**Status:** ✅ COMPLETE

**File:** `tests/test_spi_skylight.py` (258 LOC)

**Coverage:**
- 11 tests total (all passing ✅)
- SkyLight bridge: initialization, fallback, singleton caching, availability check
- C1 channel: fire success, idempotency gating, cancel event handling, bbox validation, metadata
- Fixtures: mock_capabilities (SkyLight available) and mock_capabilities_unavailable

**Test framework:** pytest + pytest-asyncio per RESEARCH.md L310-342
**Command:** `uv run pytest tests/test_spi_skylight.py -x` → 11 PASSED

## Task Execution Summary

| Task | Name | Status | Files | Commit |
|------|------|--------|-------|--------|
| 1 | SkyLight SPI wrapper | ✅ | skylight.py | 90b7954 |
| 2 | C1 SPI channel + registry | ✅ | c1_skylight_spi.py, channel_registry.py | 90b7954 |
| 3 | Unit tests | ✅ | test_spi_skylight.py | 90b7954 |

## Deviations from Plan

None — plan executed exactly as written.

## Validation Results

**All acceptance criteria met:**

| Criterion | Status | Evidence |
|-----------|--------|----------|
| basicctrl/spi/skylight.py created (SkyLightBridge) | ✅ | File exists, 108 LOC |
| get_skylight_bridge() singleton working | ✅ | test_get_skylight_bridge_caches PASS |
| post_to_pid() fallback logic verified | ✅ | test_skylight_bridge_post_to_pid_fallback PASS |
| C1SkyLightSPI channel created | ✅ | 132 LOC, Channel protocol implemented |
| channel_registry.register_with_capabilities() | ✅ | Async method added, gates on skylight_available |
| C1_SPI registration conditional on capability | ✅ | grep skylight_available in registry => 1 |
| tests/test_spi_skylight.py (11 tests) | ✅ | All 11 tests PASS |
| Phase 2 regression tests still pass | ✅ | tests/unit/actions/channels/ => 39 PASS |
| Grep: `grep -c "SkyLightBridge"` >= 1 | ✅ | Count: 5 |
| Grep: `grep -c "post_to_pid"` >= 1 | ✅ | Count: 1 (async method) |

## Testing Summary

**Unit test output:**
```
tests/test_spi_skylight.py::test_skylight_bridge_init_when_available PASSED
tests/test_spi_skylight.py::test_skylight_bridge_init_when_unavailable PASSED
tests/test_spi_skylight.py::test_skylight_bridge_post_to_pid_fallback PASSED
tests/test_spi_skylight.py::test_get_skylight_bridge_caches PASSED
tests/test_spi_skylight.py::test_is_skylight_available PASSED
tests/test_spi_skylight.py::test_c1_spi_channel_fires PASSED
tests/test_spi_skylight.py::test_c1_spi_channel_rejects_idempotency_loss PASSED
tests/test_spi_skylight.py::test_c1_spi_channel_respects_cancel_event PASSED
tests/test_spi_skylight.py::test_c1_spi_channel_missing_bbox PASSED
tests/test_spi_skylight.py::test_c1_spi_channel_name PASSED
tests/test_spi_skylight.py::test_c1_spi_channel_description PASSED

==================== 11 passed in 0.11s ====================
```

**Regression tests (Phase 2 channels):**
```
tests/unit/actions/channels/ — 39 PASS
```

## Known Stubs / Deferred Items

None — Wave 1 is complete. Wave 2 will integrate AX remote (SPI-02) in parallel.

## Threat Model Mitigation

| Threat ID | Category | Mitigation |
|-----------|----------|-----------|
| T-6-01 | Spoofing (dlsym result untrusted) | Return False on dlsym failure; channel-registry gates behind capability flag |
| T-6-02 | Tampering (event construction) | Event constructed safely from ActionCanonical; no raw user input |
| T-6-03 | Information Disclosure | SPI status logged at INFO; status non-sensitive; aids observability |

## Phase 6 Readiness

**Wave 0 + Wave 1 complete.** SkyLight (SPI-01) fully integrated with capability gating and public-API fallback. Ready for Wave 2 parallel integration (AX remote SPI-02 + other channels).

**Next:** Wave 2 — AX remote `_AXObserverAddNotificationAndCheckRemote` integration (SPI-02)

## Self-Check: PASSED

- [x] basicctrl/spi/skylight.py exists
- [x] basicctrl/actions/channels/c1_skylight_spi.py exists
- [x] basicctrl/actions/channel_registry.py modified
- [x] tests/test_spi_skylight.py exists with 11 tests
- [x] All 11 unit tests passing
- [x] Phase 2 regression tests passing (39/39)
- [x] Commit 90b7954 recorded
- [x] Files match expected content from plan
