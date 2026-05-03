---
phase: 6
plan: 01
subsystem: private-spis-durability-hardening
tags: [spi-probes, capability-detection, graceful-degradation]
dependency_graph:
  requires: []
  provides: [SPI-01, SPI-02, SPI-03, SPI-04, SPI-05, SPI-06, SPI-07, SPI-08]
  affects: [Phase-6-Wave-1-SPI-channels, AppProfile-caching]
tech_stack:
  added: [basicctrl/spi/probe.py, basicctrl/spi/__init__.py, SPICapabilities dataclass]
  patterns: [capability-probe, graceful-degradation, dlsym, try-catch, IOKit enumeration]
key_files:
  created:
    - basicctrl/spi/__init__.py (module entry point + pytest.importorskip gate)
    - basicctrl/spi/probe.py (8 SPI capability probes + SPICapabilities dataclass)
    - tests/test_spi_probes.py (10 unit tests for all 8 SPIs)
    - tests/test_profile_spi.py (3 unit tests for AppProfile SPI fields)
  modified:
    - basicctrl/profile/classifier.py (added 8 spi_*_available fields, probe_spi_capabilities() call)
    - .planning/phases/06-private-spis-durability-hardening/06-VALIDATION.md (populated with Wave 0 test plan)
decisions:
  - "All 8 SPIs have graceful fallback to False (unavailable) — no hard gates"
  - "Capability probes run in parallel via asyncio.run_in_executor for speed"
  - "SPICapabilities is immutable @dataclass, cached per session in AppProfile"
  - "probe_endpoint_security() and probe_dtrace() gated by SIP tier; log SIP status"
  - "probe_dyld_inject() returns False until Wave 3 spike validates arm64e signing"
  - "probe_webkit_inspector() checks Xcode SDK path; graceful skip if header missing"
  - "probe_imu() uses ioreg enumeration; graceful skip on Intel Macs"
metrics:
  duration_minutes: ~15
  tasks_completed: 3
  files_created: 4
  files_modified: 2
  tests_passing: 13
  coverage: 8 SPIs probed, 100% of Wave 0 test references covered
completed_date: 2026-05-01
completion_status: success
---

# Phase 6 Plan 01 — SPI Module Skeleton + Capability Probes

**One-liner:** Capability probe pattern for 8 private SPIs (SkyLight, AX remote, ES, DTrace, DYLD, WebKit, IMU) with graceful degradation to public API fallbacks.

## Summary

Wave 0 establishes the foundation for Phase 6 SPI integration:

1. **SPI Module Skeleton** (Task 1)
   - `basicctrl/spi/__init__.py` with macOS-only pytest.importorskip gate
   - `basicctrl/spi/probe.py` with 8 capability probe functions
   - `SPICapabilities` immutable dataclass with all 8 bool fields
   - `probe_spi_capabilities()` async function runs all probes in parallel
   - All probes log results to structlog at INFO level

2. **AppProfile Extended** (Task 2)
   - Added 8 spi_*_available fields (default False)
   - classify() calls probe_spi_capabilities() at session start
   - SPI capability flags cached in AppProfile + persisted to disk
   - Tests verify field existence, type, and defaults

3. **Validation Infrastructure** (Task 3)
   - VALIDATION.md populated with Wave 0 test plan
   - 13 unit tests covering all 8 SPIs + AppProfile integration
   - Per-task verification map + manual-only verifications for Wave 1+

## Task Execution

### Task 1: SPI Module Skeleton + Capability Probe Pattern

**Status:** ✅ COMPLETE

**Files created:**
- `basicctrl/spi/__init__.py` (15 LOC)
- `basicctrl/spi/probe.py` (220 LOC)
- `tests/test_spi_probes.py` (110 LOC)

**Probes implemented:**
1. **SPI-01 (SkyLight)** — `probe_skylight()` via dlsym(RTLD_DEFAULT, "SLEventPostToPid")
2. **SPI-02 (AX Remote)** — `probe_ax_remote()` via PyObjC HIServices binding check
3. **SPI-03 (CGS Display Space)** — `probe_cgs_display_space()` via dlsym symbol lookup
4. **SPI-04 (Endpoint Security)** — `probe_endpoint_security()` checks es_new_client + SIP status
5. **SPI-05 (DTrace)** — `probe_dtrace()` spawns test probe, handles EPERM gracefully
6. **SPI-06 (DYLD Inject)** — `probe_dyld_inject()` returns False (spike deferred to Wave 3)
7. **SPI-07 (WebKit RemoteInspector)** — `probe_webkit_inspector()` checks Xcode SDK header
8. **SPI-08 (IMU)** — `probe_imu()` enumerates IOKit for AppleSPUHIDDevice

**Key features:**
- All probes gracefully return False on unavailable (Rule 1: auto-fixed bug)
- `probe_endpoint_security()` and `probe_dtrace()` now check subprocess at module level (fixed UnboundLocalError)
- `probe_spi_capabilities()` runs all 8 probes in parallel via asyncio executor threads
- Results logged to structlog as structured event `spi_capabilities_probed`

**Tests passing:** 10/10
- `test_probe_skylight`, `test_probe_ax_remote`, `test_probe_cgs_display_space`
- `test_probe_endpoint_security`, `test_probe_dtrace`, `test_probe_dyld_inject`
- `test_probe_webkit_inspector`, `test_probe_imu`
- `test_probe_spi_capabilities_returns_dataclass`, `test_probe_spi_capabilities_all_bool`

### Task 2: Extend AppProfile with SPI Availability Fields

**Status:** ✅ COMPLETE

**Files modified:**
- `basicctrl/profile/classifier.py` (added 8 fields, updated classify())
- Created `tests/test_profile_spi.py` (60 LOC, 3 unit tests)

**Changes:**
- Added 8 new bool fields to AppProfile dataclass (all default False)
- Updated `classify()` to call `probe_spi_capabilities()` and populate SPI fields
- SPI flags now cached in-memory and persisted to disk via existing profile cache

**Tests passing:** 3/3
- `test_app_profile_has_spi_fields` — verifies all 8 fields exist
- `test_app_profile_spi_fields_are_bool` — verifies type hints are bool
- `test_app_profile_spi_defaults_to_false` — verifies defaults are False

**Grep verification:**
```bash
$ grep -c "spi_.*_available" basicctrl/profile/classifier.py
16  # (>= 8 required ✓)
```

### Task 3: Populate VALIDATION.md + Create Unit Tests

**Status:** ✅ COMPLETE

**Files created/modified:**
- `.planning/phases/06-private-spis-durability-hardening/06-VALIDATION.md` (populated from plan template)

**Content:**
- Test framework: pytest 7.x + pytest-asyncio 0.23+
- Quick run: `pytest tests/test_spi_probes.py -x` (~5s)
- Full suite: `pytest tests/test_spi_*.py -x` (~30s)
- Per-task verification map: 3 rows (6-01-01, 6-01-02, 6-02-01)
- Manual-only verifications: SPI-01/02/06 integration tests (Wave 1+)
- Wave 0 requirements fully satisfied

**Tests passing:** All 13 unit tests across both test files

## Deviations from Plan

**1. [Rule 1 - Bug] Fixed UnboundLocalError in probe_endpoint_security()**
- **Found during:** Task 1 test execution
- **Issue:** `subprocess` imported inside try block but referenced in except clause
- **Fix:** Moved `import subprocess` to module level (line 16)
- **Files modified:** basicctrl/spi/probe.py
- **Applied to:** probe_endpoint_security, probe_dtrace, probe_imu

## Validation Results

**All acceptance criteria met:**

| Criterion | Status | Evidence |
|-----------|--------|----------|
| basicctrl/spi/__init__.py created + importable | ✅ | File exists, imports cleanly |
| basicctrl/spi/probe.py created + 8 probes | ✅ | 220 LOC, 8 probe functions + async wrapper |
| SPICapabilities dataclass with 8 bool fields | ✅ | @dataclass with 8 immutable fields |
| AppProfile.spi_*_available fields (8 total) | ✅ | grep -c => 16 (field definition + usage) |
| classify() calls probe_spi_capabilities() | ✅ | Line ~311 in classifier.py |
| tests/test_spi_probes.py (10+ unit tests) | ✅ | 10 tests, all PASS |
| 06-VALIDATION.md populated (test framework + map) | ✅ | Full VALIDATION.md with Wave 0 content |
| All Wave 0 tests passing | ✅ | 13/13 tests PASS |
| Grep: `grep -c "spi_.*_available"` >= 8 | ✅ | Count: 16 |
| Grep: `grep -c "def probe_"` >= 8 | ✅ | Count: 9 |

## Testing Summary

**Wave 0 test coverage:**
- SPI-01..08 capability probes: 8 unit tests ✅
- SPICapabilities dataclass: 2 integration tests ✅
- AppProfile SPI fields: 3 unit tests ✅
- **Total: 13 tests, all passing**

**Sample test output:**
```
tests/test_spi_probes.py::test_probe_skylight PASSED
tests/test_spi_probes.py::test_probe_ax_remote PASSED
tests/test_spi_probes.py::test_probe_cgs_display_space PASSED
tests/test_spi_probes.py::test_probe_endpoint_security PASSED
tests/test_spi_probes.py::test_probe_dtrace PASSED
tests/test_spi_probes.py::test_probe_dyld_inject PASSED
tests/test_spi_probes.py::test_probe_webkit_inspector PASSED
tests/test_spi_probes.py::test_probe_imu PASSED
tests/test_spi_probes.py::test_probe_spi_capabilities_returns_dataclass PASSED
tests/test_spi_probes.py::test_probe_spi_capabilities_all_bool PASSED
tests/test_profile_spi.py::test_app_profile_has_spi_fields PASSED
tests/test_profile_spi.py::test_app_profile_spi_fields_are_bool PASSED
tests/test_profile_spi.py::test_app_profile_spi_defaults_to_false PASSED

======================== 13 passed in 0.10s ========================
```

## Known Stubs / Deferred Items

- **probe_dyld_inject()** returns False — arm64e signing spike required before Wave 3 (RESEARCH.md L92-131)
- **probe_webkit_inspector()** checks SDK path only — private header import tested in Wave 1
- **SIP tier classification** (Tier A/B/C) documented in RESEARCH.md but not exposed in probe results yet

## Threat Model Mitigation

| Threat ID | Category | Mitigation |
|-----------|----------|-----------|
| T-6-01 | Spoofing (dlsym) | Return False if symbol missing; channel-registry gates behind flag |
| T-6-02 | Tampering (cached flags) | @dataclass frozen semantics; AppProfile read-only post-session-start |
| T-6-03 | Information Disclosure | SPI status logged but non-sensitive; aids observability |
| T-6-04 | DoS (probe timeout) | All probes <2s timeout; failures degrade gracefully |
| T-6-05 | Elevation (private SPIs) | Intentional for maximalist framework; local-only experimental system |

## Phase 6 Readiness

**Wave 0 complete.** Ready for Wave 1 SPI channel implementations:
- [ ] Wave 1 — SkyLight (C1) bridge + AX remote (C1) integration
- [ ] Wave 2 — CDP private APIs + ES kernel monitoring
- [ ] Wave 3 — arm64e DYLD injection spike + IMU lid-angle sensor

**Handoff artifacts:**
- SPICapabilities schema + probe_spi_capabilities() API locked for Wave 1
- AppProfile SPI fields cached and persisted
- VALIDATION.md ready for Wave 1 integration test expansion
