---
phase: 6
plan: 05
subsystem: private-spis-durability-hardening
tags: [spi-imu, m-series-sensor, graceful-degradation, iokit]
dependency_graph:
  requires: [06-01]
  provides: [SPI-08-IMU]
  affects: [IMU-based-retry-backoff, motion-aware-features]
tech_stack:
  added: [cua_overlay/spi/imu.py, IMUBridge, IMUData, get_imu_bridge]
  patterns: [capability-aware-init, graceful-skip-on-unavailable, ioreg-enumeration]
key_files:
  created:
    - cua_overlay/spi/imu.py (108 LOC)
    - tests/test_spi_imu.py (116 LOC)
  modified: []
decisions:
  - "IOKit enumeration via ioreg(1) for safe non-blocking hardware detection"
  - "Graceful unavailability on Intel Macs — imu_available gated by SPICapabilities"
  - "IMUData placeholder (full HID report parsing deferred to Wave 2+)"
  - "Single global _bridge with caching per session"
  - "All probe errors logged at WARNING level with actionable context"
metrics:
  duration_minutes: ~5
  tasks_completed: 2
  files_created: 2
  files_modified: 0
  tests_passing: 9
  coverage: 100% of IMU read paths tested (unavailable, no-service, with-service)
completed_date: 2026-05-01
completion_status: success
---

# Phase 6 Plan 05 — SPI-08 AppleSPUHIDDevice IMU Reader

**One-liner:** IOKit HID wrapper for Bosch BMI286 motion sensor on M-series Macs (M1-M4), gracefully unavailable on Intel, ready for optional motion-aware features in Wave 2.

## Summary

Plan 05 completes the IMU sensor integration, enabling optional motion-aware features (lid-angle detection, vibration-triggered retry backoff, etc.):

1. **IMUBridge Wrapper** (Task 1)
   - Async-ready IMUBridge class with capability-aware initialization
   - IOKit enumeration via ioreg(1) at session start
   - Graceful downgrade to unavailable on Intel or probe failure
   - Placeholder IMUData read path for Wave 2+ HID report parsing
   - Structured logging via structlog with actionable error context

2. **Test Suite** (Task 2)
   - 9 unit tests covering initialization, probe success/failure, data flow
   - Mock SPICapabilities for isolated testing
   - Caching validation (global _bridge singleton)
   - All tests passing, ready for integration with Wave 1 verifier

## Task Execution

### Task 1: Create AppleSPUHIDDevice IMU Wrapper

**Status:** ✅ COMPLETE

**File created:** `cua_overlay/spi/imu.py` (108 LOC)

**Implementation details:**

- **IMUData dataclass** — 7 optional float fields (lid_angle, accel_x/y/z, gyro_x/y/z)
- **IMUBridge class**
  - Constructor accepts `available: bool` flag from SPICapabilities
  - `_discover_imu_service()` runs ioreg enumeration only if available=True
  - Gracefully handles all subprocess errors (FileNotFoundError, TimeoutExpired, generic Exception)
  - Logs at INFO on success, WARNING on failure
  - Sets `_service = True` on discovery, `available = False` on failure
  - `read_imu()` async method returns None if unavailable, IMUData (placeholder) if available
- **Caching via get_imu_bridge()** — module-level singleton _bridge, initialized once per session

**Probe behavior:**

- M-series with IMU present: `ioreg -r -d 1 -c AppleSPUHIDDevice` returns "AppleSPUHIDDevice" → available=True
- Intel Macs / no IMU: ioreg returns empty → available downgraded to False
- ioreg not in PATH: FileNotFoundError caught → available=False
- ioreg timeout (2s): subprocess.TimeoutExpired caught → available=False

**Graceful degradation:**
- If not available, all read functions return None (feature silently unavailable)
- No exception raised, no warning printed to user
- Actionable logs (device found / device not found / error type) to action_log.ndjson

**Verification:**
```bash
source .venv/bin/activate && python -m pytest tests/test_spi_imu.py -v
# Result: 9 passed in 0.08s
```

### Task 2: Create Unit Test Suite

**Status:** ✅ COMPLETE

**File created:** `tests/test_spi_imu.py` (116 LOC)

**Test coverage:**

| Test | Purpose | Result |
|------|---------|--------|
| `test_imu_bridge_init_unavailable` | Available=False stays unavailable | PASS |
| `test_imu_bridge_init_available` | Available=True triggers discovery | PASS |
| `test_read_imu_unavailable` | read_imu() returns None when unavailable | PASS |
| `test_read_imu_available_no_service` | read_imu() returns None when service not discovered | PASS |
| `test_read_imu_available_with_service` | read_imu() returns IMUData when service found | PASS |
| `test_imu_data_init_empty` | IMUData defaults to all None | PASS |
| `test_imu_data_partial_init` | IMUData accepts partial field init | PASS |
| `test_get_imu_bridge_caches` | Global _bridge singleton caching | PASS |
| `test_get_imu_bridge_unavailable` | Respects capabilities.imu_available flag | PASS |

**Design notes:**

- MockSPICapabilities dataclass for isolated testing
- Async tests use `@pytest.mark.asyncio` fixture
- Tests reset global _bridge per test (isolation)
- No integration with real ioreg (unit tests mock success/failure paths)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

**IMU data reading deferred:** `read_imu()` returns empty IMUData (all fields None) as placeholder. Raw IOKit HID report parsing (22-byte little-endian struct at fixed offsets) deferred to Wave 2+ when motion-aware features are integrated.

**Rationale:** Phase 6 Wave 1 focuses on availability probing and graceful fallback. Actual sensor data consumption depends on Wave 2 retry-backoff and motion-aware feature requirements.

## Threat Flags

None. IOKit enumeration via public ioreg(1) utility poses no new threat surface.

## Self-Check

**Files created verification:**
- `/Users/akeilsmith/dev/cua-maximalist/cua_overlay/spi/imu.py` — ✅ EXISTS (108 LOC)
- `/Users/akeilsmith/dev/cua-maximalist/tests/test_spi_imu.py` — ✅ EXISTS (116 LOC)

**Commit verification:**
- Commit hash: `32a2bec` ✅ EXISTS
- Log: `feat(06-05): implement SPI-08 AppleSPUHIDDevice IMU reader` ✅ FOUND

**Test execution:**
- All 9 tests passing ✅

## Self-Check: PASSED ✅

All files created, all commits verified, all tests passing. Ready for Wave 2 IMU data integration.
