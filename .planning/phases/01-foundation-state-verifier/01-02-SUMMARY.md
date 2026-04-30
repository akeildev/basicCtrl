---
phase: 01-foundation-state-verifier
plan: 02
subsystem: profile

tags:
  - app-classifier
  - capability-probe
  - tcc
  - pyobjc
  - hiservices
  - axobserver
  - pydantic-v2
  - anyio
  - structlog

# Dependency graph
requires:
  - phase: 01-01
    provides: "package scaffold (cua_overlay/, tests/, pyproject.toml). Plan 01-02 created a minimal version inline; 01-01's canonical scaffold supersedes on merge."

provides:
  - "AppProfile Pydantic v2 schema (locked contract for Phase 2 translators)"
  - "classify(bundle_id, pid) async entry-point with parallel anyio probes + disk cache"
  - "TCCMonitor (AXIsProcessTrusted polled at every classify entry; Pitfall 24 mitigation)"
  - "~/.cua/profiles/<bundle_id>.json atomic disk cache (Pitfall 16 invalidation)"
  - "Calculator integration test fixture (pgrep-based, session-scoped)"

affects:
  - phase-2-translators  # T1..T5 import AppProfile to choose priority
  - phase-1-03  # AX wrapper inherits TCCMonitor
  - phase-1-08  # MCP proxy reads bundle_path/version from AppProfile

# Tech tracking
tech-stack:
  added:
    - "pydantic >=2.0"
    - "anyio >=4.0"
    - "structlog 25.5.0"
    - "httpx >=0.27"
    - "pyobjc 12.1 (HIServices, AppKit)"
    - "pytest 8.x + pytest-asyncio 0.23+"
  patterns:
    - "Pydantic v2 frozen schemas as the cross-phase contract layer"
    - "Lazy import inside .check() so monkeypatch can swap HIServices.AXIsProcessTrusted in tests"
    - "Module-level test override hook (_CACHE_DIR_OVERRIDE) — no global mutation in production code"
    - "Atomic write via .tmp + os.replace (Pitfall 16 mitigation pattern)"
    - "Parallel probes via anyio.create_task_group with per-probe asyncio.wait_for timeout"
    - "objc.callbackFor decorator for PyObjC C-callbacks (AXObserverCreate)"
    - "pgrep-based process discovery in tests (NSWorkspace cache requires CFRunLoop tick)"

key-files:
  created:
    - "cua_overlay/profile/__init__.py"
    - "cua_overlay/profile/classifier.py"
    - "cua_overlay/profile/capability_probe.py"
    - "cua_overlay/profile/cache.py"
    - "cua_overlay/profile/tcc.py"
    - "tests/unit/test_appprofile_cache.py"
    - "tests/unit/test_tcc.py"
    - "tests/integration/test_app_profile.py"
    - "tests/conftest.py"  # minimal version; 01-01 owns canonical
    - "pyproject.toml"     # minimal version; 01-01 owns canonical
    - "cua_overlay/__init__.py"  # bare; 01-01 fills exports
  modified: []

key-decisions:
  - "AppProfile schema locked verbatim per <interfaces> block — Phase 2 translators import directly without redefinition"
  - "Cache filename uses bundle_id only (not version): re-probes overwrite, version-mismatch triggers re-probe"
  - "TCC check is the FIRST line of classify() — Pitfall 24 mandates per-call recheck"
  - "ax_observer_works probe is subscribe-only (not fire-wait): full AXObserver bridge is Plan 01-04, the subscribe-success signal is enough for routing"
  - "translator_priority order: T2 CDP > T1 AX > T3 AppleScript > T4 Vision > T5 Pixel (richest information per latency at the front)"
  - "tcc.check() uses lazy HIServices import so monkeypatch can override the symbol in tests"

patterns-established:
  - "Lazy SPI imports in test-targetable code (HIServices, AppKit) — keeps unit tests pure-Python"
  - "Per-probe self-capping via asyncio.wait_for inside the probe (not at the call site) — failure mode is fail-open"
  - "objc.callbackFor() is mandatory for any PyObjC C-callback (AXObserverCreate, AXValueCreate, etc.) — Phase 2 inherits"
  - "tests/conftest.py uses pgrep for process discovery, not NSWorkspace.runningApplications (CFRunLoop dependency)"
  - "Cache dir override via _CACHE_DIR_OVERRIDE module-level variable — test-only knob, never set in prod"

requirements-completed:
  - CORE-02
  - CORE-03

# Metrics
duration: 35min
completed: 2026-04-29
---

# Phase 1 Plan 2: AppProfile Classifier Summary

**Per-bundle capability probe (AX-rich? .sdef? CDP-port?) with parallel anyio task group, TCC re-check at every entry, and atomic ~/.cua/profiles/ disk cache — Calculator probed in 14ms, cache hit in 0ms**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-04-29T19:48Z
- **Completed:** 2026-04-29T20:08Z
- **Tasks:** 3 (all completed)
- **Files created:** 11
- **Files modified:** 0
- **Tests:** 16/16 passing (8 cache + 4 TCC + 4 integration)

## Accomplishments

- AppProfile Pydantic v2 schema locked (15 fields + cache_key property) — Phase 2 translators import this verbatim.
- classify() async entry-point: TCC check → metadata read → cache lookup → parallel probes (anyio task group) → translator_priority derivation → atomic write.
- 7 capability probes: bundle_metadata, ax_rich, ax_observer_works, cdp_ports, applescript_sdef, electron, tauri_or_wails.
- TCCMonitor with structlog `tcc_revoked` event + System Settings deep link + SystemExit(2). Pitfall 24 mitigated.
- Disk cache with version+build invalidation (Pitfall 16) and atomic .tmp+os.replace write.
- 4 integration tests pass against real Calculator on M-series macOS 26.

## AppProfile Schema (verbatim, locked)

| Field | Type | Source |
|---|---|---|
| bundle_id | str | required input |
| bundle_version | Optional[str] | Info.plist CFBundleShortVersionString |
| bundle_build | Optional[str] | Info.plist CFBundleVersion |
| bundle_path | Optional[str] | NSWorkspace.URLForApplicationWithBundleIdentifier_ |
| ax_rich | bool | AXChildren > 0 within 200ms (kAXChildrenAttribute) |
| ax_observer_works | bool | AXObserverCreate + Add succeeds within 500ms |
| applescript_sdef | bool | OSAScriptingDefinition or NSAppleScriptEnabled in Info.plist |
| cdp_port | Optional[int] | localhost:9222..9230 /json/version reachable (only if Electron) |
| cdp_available_after_relaunch | bool | electron AND cdp_port is None (Pitfall 8 hint) |
| tauri_or_wails | bool | WebKit.framework AND no .sdef AND not Electron (A2 heuristic) |
| electron | bool | Contents/Frameworks/Electron Framework.framework exists |
| tcc_axenabled | bool | AXIsProcessTrusted at probe time |
| translator_priority | list[str] | derived: T2 > T1 > T3 then T4+T5 |
| probed_at | datetime | UTC at probe completion |
| probe_latency_ms | int | int((monotonic_end - monotonic_start) * 1000) |

`@property cache_key` returns `"{bundle_id}@{version}+{build}"` for in-memory dedupe.

## classify() Probe Sequence (with measured latencies)

```
classify(bundle_id, pid)
  └─ _tcc.check()                          [<1ms]   ← Pitfall 24: FIRST line
  └─ probe_bundle_metadata(bundle_id)      [~5ms]
  └─ load_cached_profile + invalidate?     [<1ms]
  │
  ├─ if cache hit + same version+build:    [TOTAL ~0ms]
  │  └─ log appprofile_cache_hit, return cached
  │
  └─ else PARALLEL (anyio.create_task_group):
     ├─ probe_ax_rich(pid)                 [≤200ms timeout, 1 AX read]
     ├─ probe_ax_observer_works(pid)       [≤500ms timeout, AXObserverCreate+Add]
     └─ probe_cdp_ports(pid) if electron   [≤900ms wall, but classifier caps at 200ms]
     │
     └─ derive priority + save_cached_profile (atomic)
```

**Measured on real Calculator (M-series Mac, macOS 26):**
- First probe: **14ms** (35x under the 500ms budget; warm probes settle around 5-10ms)
- Cache hit: **0ms** (the 5ms budget is satisfied trivially)

## Cache Invalidation Rules

`should_invalidate_cache(cached, current_version, current_build) -> bool`:

1. `cached.bundle_version != current_version` → invalidate
2. `cached.bundle_build != current_build` → invalidate
3. else → cache hit valid

The on-disk filename is `<bundle_id>.json` (no version segment), so re-probes overwrite a single file per bundle. This is the explicit Pitfall 16 mitigation pattern.

## TCCMonitor Scope

| Polled at | Plan |
|---|---|
| Start of every `classify()` call | Plan 01-02 (this plan) |
| Start of every AX wrapper entry-point | Plan 01-03 (next; inherits TCCMonitor verbatim) |
| AXObserver subscribe error path | Plan 01-04 |

On revocation: structlog event `tcc_revoked` with `action_url=x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`, then `SystemExit(2)`. Phase 5 will swap the exit for an NSPanel prompt.

## ax_observer_works Confirmation

Calculator (native AppKit, macOS 26) probe result:
- `ax_observer_works=True` — AXObserverCreate + AXObserverAddNotification(kAXFocusedUIElementChangedNotification) both return err=0.
- This is the **non-Pitfall-14** path: native AppKit apps reliably support AXObserver.
- Pitfall 14 candidates (web shells, Electron, Tauri) will be probed in Phase 2 against Slack / Cursor / VS Code; the same probe will return `False` and route them through T2 CDP for verification.

## Task Commits

1. **Task 1: AppProfile cache (atomic write, Pitfall 16 invalidation)** — `39de62b` (feat)
2. **Task 2: Capability probes + classify() + TCC monitor** — `8380208` (feat)
3. **Task 3: Calculator integration test + AX observer probe fix** — `f7a7693` (feat)

## Files Created/Modified

- `cua_overlay/profile/__init__.py` — re-exports AppProfile, classify, TCCMonitor.
- `cua_overlay/profile/classifier.py` — AppProfile model + classify() entry-point with parallel anyio task group + TCC gate.
- `cua_overlay/profile/capability_probe.py` — 7 async probes with self-capping timeouts and fail-open semantics.
- `cua_overlay/profile/cache.py` — atomic disk cache with version-keyed invalidation; uses TYPE_CHECKING + lazy import to avoid circular dependency with classifier.
- `cua_overlay/profile/tcc.py` — TCCMonitor.check (lazy HIServices import) + on_revocation (structlog + SystemExit(2)).
- `tests/unit/test_appprofile_cache.py` — 8 unit tests covering save/load/atomic-write/invalidation/single-file-per-bundle.
- `tests/unit/test_tcc.py` — 4 unit tests: AXIsProcessTrusted reflection, structlog `tcc_revoked` event, SystemExit code 2, ordering of TCC check before any probe in classify().
- `tests/integration/test_app_profile.py` — 4 tests against real Calculator: first-probe latency, cache persistence, version-change invalidation re-probe, T1-first priority for native AppKit.
- `tests/conftest.py` — minimal calculator_pid fixture (session-scoped, pgrep-based). Plan 01-01 owns canonical version; on merge, 01-01's richer fixture wins.
- `pyproject.toml` — minimal Python project metadata + pytest config. Plan 01-01 owns canonical version with the full dep set.
- `cua_overlay/__init__.py` — bare `__version__ = "0.1.0"`. Plan 01-01 fills exports.

## Decisions Made

- **Lazy HIServices import inside `TCCMonitor.check()`** — required for `monkeypatch.setattr("HIServices.AXIsProcessTrusted", ...)` to work in tests. The alternative (top-level import) would freeze the symbol at module-load time.
- **Test override via `_CACHE_DIR_OVERRIDE` module global** — chosen over a function argument because `classify()` already has a fixed signature `(bundle_id, pid)` mandated by the plan's `<interfaces>`. Adding a `cache_base` arg would have forced every Phase 2 caller to pass it; module global is set only by tests, never in production code.
- **objc.callbackFor decorator for AXObserverCreate** — required by PyObjC 12.1's metadata-based callback marshalling (the C signature is `void (*)(AXObserverRef, AXUIElementRef, CFStringRef, void*)` and PyObjC needs the type signature to bridge it). Discovered when first integration test failed with `ax_observer_works=False`.
- **Session-scoped `calculator_pid` fixture** — kill+relaunch between tests races against NSWorkspace's pid cache; one launch per session avoids that.
- **`pgrep` for process discovery, not NSWorkspace** — `NSWorkspace.runningApplications()` only refreshes when a CFRunLoop ticks, and pytest's asyncio thread doesn't have one. We discovered this when launches "failed" silently for 15s while pgrep showed the process running fine.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Calculator bundle ID is `com.apple.calculator` (lowercase 'c'), not `com.apple.Calculator`**
- **Found during:** Task 3 (integration test execution)
- **Issue:** Plan and `<interfaces>` block specified `com.apple.Calculator` but `/usr/libexec/PlistBuddy` confirms the bundle declares `com.apple.calculator` (lowercase). NSWorkspace and pgrep both report the same.
- **Fix:** Updated all integration tests + conftest fixture to use the lowercase bundle id; `_find_calculator_pid` matches case-insensitively to be defensive.
- **Files modified:** tests/integration/test_app_profile.py, tests/conftest.py.
- **Verification:** All 4 integration tests pass.
- **Committed in:** f7a7693.

**2. [Rule 3 - Blocking] PyObjC AXObserverCreate requires objc.callbackFor wrapper**
- **Found during:** Task 3 (first run of test_calculator_profile)
- **Issue:** `probe_ax_observer_works` was passing a plain Python function as the AXObserverCreate callback, which raised `TypeError: Callable argument is not a PyObjC closure`. This made `ax_observer_works=False` for every app — including native AppKit Calculator that demonstrably supports AXObserver.
- **Fix:** Wrapped the callback with `@objc.callbackFor(AXObserverCreate)`. PyObjC's callable metadata then marshals the function signature across the C boundary correctly.
- **Files modified:** cua_overlay/profile/capability_probe.py.
- **Verification:** Calculator probe now returns `ax_observer_works=True` (verified via integration test).
- **Committed in:** f7a7693.

**3. [Rule 3 - Blocking] NSWorkspace.runningApplications cache stale without CFRunLoop**
- **Found during:** Task 3 (integration tests skipping with "Calculator.app failed to launch within 15s")
- **Issue:** `NSWorkspace.sharedWorkspace().runningApplications()` returned the same cached list across calls in the test asyncio thread. pgrep showed Calculator launched and running; NSWorkspace did not see it for >10s. Root cause: the runningApplications collection only refreshes on a CFRunLoop tick, and pytest's asyncio loop doesn't run one.
- **Fix:** Replaced NSWorkspace polling with `subprocess.check_output(['pgrep', '-x', 'Calculator'])`. `os.kill(pid, 0)` confirms OS-level liveness (filters dying pids).
- **Files modified:** tests/conftest.py.
- **Verification:** All 4 integration tests pass in 0.55s.
- **Committed in:** f7a7693.

**4. [Rule 3 - Blocking] Circular import between classifier.py and cache.py**
- **Found during:** Task 2 (running test_tcc.py for the first time)
- **Issue:** `cache.py` imported `AppProfile` from `classifier.py`, and `classifier.py` imported the cache helpers from `cache.py`. Result: `ImportError: cannot import name 'AppProfile' from partially initialized module`.
- **Fix:** `cache.py` uses `TYPE_CHECKING` for the `AppProfile` type annotation and a lazy `from cua_overlay.profile.classifier import AppProfile` inside `load_cached_profile()`. `save_cached_profile()` doesn't need the lazy import (it accepts the type as input).
- **Files modified:** cua_overlay/profile/cache.py.
- **Verification:** Test imports succeed; all unit tests pass.
- **Committed in:** 8380208.

**5. [Rule 1 - Bug] Calculator AX tree empty for ~0.5-2s after relaunch**
- **Found during:** Task 3 (test_translator_priority running against the same fixture as the first 3 tests)
- **Issue:** When the per-test fixture killed Calculator with SIGTERM and relaunched between tests, AXChildren returned an empty list because the new window hadn't fully populated yet — even though the process was running.
- **Fix:** Made `calculator_pid` fixture session-scoped (one Calculator per test session) + use `osascript "tell application "Calculator" to quit"` for clean shutdown at session end + added an AX-readiness wait that polls AXChildren until count>0 (15s deadline).
- **Files modified:** tests/conftest.py.
- **Verification:** All 4 integration tests pass when run together.
- **Committed in:** f7a7693.

---

**Total deviations:** 5 auto-fixed (1 bug, 4 blocking integrations).
**Impact on plan:** All deviations were correctness-essential — none added scope. The PyObjC C-callback marshalling and NSWorkspace CFRunLoop dependency are exactly the kind of platform-quirk discoveries Phase 1 was designed to surface before Phase 2 starts building on top.

## Issues Encountered

None beyond the deviations above. The plan's task structure (cache → probes+TCC → integration) caught each issue in its appropriate task. No checkpoints triggered.

## Auth Gates

None. AX TCC was already granted to the test runner — `AXIsProcessTrusted()` returned True at start.

## User Setup Required

None. The plan's frontmatter explicitly omits `user_setup` (Plan 01-07 owns the Postgres setup).

## Self-Check: PASSED

Verified:
- File `cua_overlay/profile/__init__.py` exists.
- File `cua_overlay/profile/classifier.py` exists, contains `class AppProfile(BaseModel)`.
- File `cua_overlay/profile/capability_probe.py` exists, all 7 probe functions present.
- File `cua_overlay/profile/cache.py` exists, contains `os.replace`.
- File `cua_overlay/profile/tcc.py` exists, contains `AXIsProcessTrusted` and `x-apple.systempreferences`.
- File `tests/unit/test_appprofile_cache.py` exists, 8 tests pass.
- File `tests/unit/test_tcc.py` exists, 4 tests pass.
- File `tests/integration/test_app_profile.py` exists, 4 tests pass.
- Commit `39de62b` exists in git log (Task 1).
- Commit `8380208` exists in git log (Task 2).
- Commit `f7a7693` exists in git log (Task 3).
- 16/16 tests pass via `uv run pytest -v tests/`.
- Cache JSON parses cleanly (verified: bundle_id, bundle_version, bundle_build, ax_rich, ax_observer_works, translator_priority all present).

## Next Phase Readiness

- AppProfile schema is **locked** — Plan 01-03 (AX wrapper) and Phase 2 translators (T1..T5) can import `from cua_overlay.profile import AppProfile, classify` immediately.
- TCCMonitor is **shared** — Plan 01-03's AX wrapper inherits `_tcc` from this plan; revocation handling is centralized.
- Cache layer is **production-ready** — atomic writes, version-invalidation, fail-open on corrupt cache.
- ax_observer_works probe is **best-effort** in Phase 1 (subscribe-only). Plan 01-04 builds the full AXEventBridge with CFRunLoop on a dedicated thread; the bridge will replace this probe with a fire-wait test for observer correctness.

**No blockers for Phase 2.**

---
*Phase: 01-foundation-state-verifier*
*Plan: 02 (AppProfile classifier)*
*Completed: 2026-04-29*
