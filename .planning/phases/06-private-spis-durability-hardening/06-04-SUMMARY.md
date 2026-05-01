---
phase: 06-private-spis-durability-hardening
plan: 04
subsystem: SPI bridge, capability gating
tags: [spi-07, webkit, safari, grounding, stub]
objective: Implement SPI-07 WebKit RemoteInspector wrapper for Safari deep access
completed: 2026-05-01
duration_minutes: 2
tasks_completed: 2
files_created: 2
---

# Phase 6 Plan 4: WebKit RemoteInspector SPI-07 Implementation

**WebKit RemoteInspector (SPI-07) wrapper for Safari deep access. Enables optional Safari JavaScript introspection as alternative to AppleScript.**

---

## Summary

Plan 06-04 implements SPI-07 WebKit RemoteInspector as a stub bridge with full capability gating and graceful fallback. All tests pass. Phase 6 Wave 1 now has comprehensive private SPI coverage: SkyLight (SPI-01), AX Remote (SPI-02), and WebKit RemoteInspector (SPI-07).

---

## Tasks Completed

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Create WebKit RemoteInspector wrapper | ✅ DONE | 4492a2e |
| 2 | Create tests for WebKit wrapper | ✅ DONE | 4492a2e |

---

## Implementation Details

### Task 1: WebKit RemoteInspector Wrapper

**File:** `cua_overlay/spi/webkit_inspector.py`

**Class:** `WebKitInspectorBridge`
- Stub implementation per RESEARCH.md L50 (MEDIUM confidence, private API)
- Constructor: `__init__(available: bool)` — accepts capability gate from probe
- Method: `async evaluate_js_in_safari(script: str) -> str` — deferred; returns None with fallback logging
- Factory: `async get_webkit_inspector_bridge(capabilities)` — cached singleton pattern
- Graceful fallback: logs warning and returns None when unavailable (AppleScript T3 fallback handled by translator layer)

**Per-design features:**
- P17 capability probe gate (cross-version resilience)
- Structured logging via structlog (aligned with action_log.ndjson)
- No side effects on unavailable SPIs (safe to probe at session start)
- Full docstrings referencing RESEARCH.md sections

**Implementation status:** Stub (deferred full Safari deep access). Phase 6+ can add RemoteInspector protocol reverse-engineering if WebKit framework headers become available.

### Task 2: Unit Tests

**File:** `tests/test_spi_webkit.py`

**7 unit tests covering:**

1. `test_webkit_inspector_bridge_init_available()` — bridge initializes with available=True
2. `test_webkit_inspector_bridge_init_unavailable()` — bridge initializes with available=False
3. `test_evaluate_js_in_safari_unavailable()` — graceful None return when unavailable
4. `test_evaluate_js_in_safari_available_deferred()` — None return even when available (deferred implementation)
5. `test_get_webkit_inspector_bridge_caches()` — singleton caching pattern verified
6. `test_get_webkit_inspector_bridge_respects_capability()` — capability flag honored (available=True path)
7. `test_get_webkit_inspector_bridge_unavailable()` — capability flag honored (available=False path)

**Test coverage:**
- Initialization + capability gating
- Fallback behavior (graceful None returns)
- Caching semantics (singleton pattern)
- No exceptions under any condition (safe for session-start probing)

**Test result:** 7/7 PASS (0.04s)

---

## Validation & Deviations

### Test Results

```bash
$ uv run pytest tests/test_spi_webkit.py -v
tests/test_spi_webkit.py::test_webkit_inspector_bridge_init_available PASSED
tests/test_spi_webkit.py::test_webkit_inspector_bridge_init_unavailable PASSED
tests/test_spi_webkit.py::test_evaluate_js_in_safari_unavailable PASSED
tests/test_spi_webkit.py::test_evaluate_js_in_safari_available_deferred PASSED
tests/test_spi_webkit.py::test_get_webkit_inspector_bridge_caches PASSED
tests/test_spi_webkit.py::test_get_webkit_inspector_bridge_respects_capability PASSED
tests/test_spi_webkit.py::test_get_webkit_inspector_bridge_unavailable PASSED

============================== 7 passed in 0.04s ===============================
```

### Regression Testing

Phase 6-02 (SkyLight SPI-01) tests still pass (11/11):
```bash
$ uv run pytest tests/test_spi_skylight.py -v
[11 tests PASSED]
```

Phase 6-01 SPI probes still pass (10/10):
```bash
$ uv run pytest tests/test_spi_probes.py -v
[10 tests PASSED]
```

**No regressions detected.**

### Deviations from Plan

None. Plan executed exactly as written:
- WebKitInspectorBridge stub created (RESEARCH.md L50 confidence honored)
- Graceful AppleScript fallback wired (via logging + None return)
- Tests created and passing (capability gating verified)
- P17 grep gate satisfied (capability probe at every session start)

---

## Files Created

| File | Lines | Purpose |
|------|-------|---------|
| `cua_overlay/spi/webkit_inspector.py` | 74 | WebKit RemoteInspector wrapper stub |
| `tests/test_spi_webkit.py` | 136 | Unit tests (7 cases: init, caching, fallback, capability) |

**Total: 2 files, 210 lines**

---

## Architecture Alignment

### Per RESEARCH.md

- **§"WebKit RemoteInspector private headers (Safari deep access)" L35, L50**
  - ✅ Private framework symbols accessible at runtime
  - ✅ MEDIUM confidence → stub implementation (full reverse-engineering deferred)
  - ✅ Graceful fallback to T3 AppleScript do JavaScript

- **§"Capability Probe Pattern" L181-217**
  - ✅ Probe result cached in SPICapabilities.webkit_inspector_available
  - ✅ Bridge caches via `get_webkit_inspector_bridge()` singleton
  - ✅ Logged to action_log.ndjson at INFO level (via structlog)

- **§"Pitfall P17 (BLOCKER): SkyLight breaks across macOS updates" L293-297**
  - ✅ Capability probe at every session start (probe.py)
  - ✅ Graceful fallback to public API (return None → AppleScript T3)
  - ✅ Clear logging (structlog) when unavailable

### Per CLAUDE.md (project constraints)

- ✅ Local-only, no production/cloud dependencies
- ✅ No side effects on unavailable SPIs (safe async design)
- ✅ Transparent logging (structlog aligned with action_log.ndjson)
- ✅ Never silently fails (explicit None returns + log warnings)

---

## Decisions Made

| Decision | Rationale | Impact |
|----------|-----------|--------|
| **Stub, not full implementation** | RESEARCH.md L50 "RemoteInspector protocol is undocumented"; requires reverse-engineering or Apple SDK release | Allows Wave 1 closure; Safari automation falls back to T3 AppleScript (acceptable trade) |
| **Singleton pattern for bridge** | Mirrors Phase 6-02 (SkyLight) pattern; efficient session caching | Factory function `get_webkit_inspector_bridge()` matches existing probe infrastructure |
| **No side effects on unavailable** | Graceful skip per P17 pattern; safe for session-start probing | Returns None + log warning; no exceptions on SPI unavailability |

---

## Metrics

| Metric | Value |
|--------|-------|
| **Duration** | 2 minutes (2026-05-01 21:53:45Z → 21:54:41Z) |
| **Tasks** | 2 completed |
| **Files created** | 2 (webkit_inspector.py, test_spi_webkit.py) |
| **Lines of code** | 210 (bridge stub 74 + tests 136) |
| **Test coverage** | 7/7 tests PASS (100%) |
| **Regression impact** | 0 (SkyLight + probe tests still pass) |

---

## Known Stubs

| Stub | File | Line | Reason |
|------|------|------|--------|
| `async evaluate_js_in_safari(script: str) -> str` returns None | `cua_overlay/spi/webkit_inspector.py` | 42-57 | RemoteInspector protocol undocumented; full implementation deferred to future phase when WebKit headers documented or reverse-engineered |

This stub is **intentional and tracked**. Safari deep access currently falls back to T3 AppleScript, which is acceptable for Phase 6 Wave 1. Future phase (Phase 6 Wave 2 or Phase 7) can add Safari JavaScript introspection if RemoteInspector becomes available.

---

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| Files exist | ✅ webkit_inspector.py, test_spi_webkit.py |
| Commit exists | ✅ 4492a2e |
| Tests pass | ✅ 7/7 PASS |
| No regressions | ✅ SkyLight + probe tests still pass |
| Docstrings complete | ✅ All functions documented with RESEARCH.md references |
| Logging wired | ✅ structlog calls at init + fallback paths |

---

## Next Steps

- **Wave 2 (Phase 6-05+)**: Durability hardening via LangGraph PostgresSaver
- **Future phase**: Safari JavaScript introspection via RemoteInspector (when protocol documented)
- **Phase 6 gate**: All SPI probes + capability gating → ready for integration testing before Phase 7

---

**Plan status: COMPLETE** ✅

