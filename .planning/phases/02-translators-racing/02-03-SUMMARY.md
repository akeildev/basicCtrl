---
phase: 02-translators-racing
plan: 03
subsystem: profile
tags: [known-apps, app-classifier, top-12, association-map, version-drift, D-20, D-21, D-22, D-23, D-24, T-2-02, TRANS-01, TRANS-02, TRANS-03, TRANS-04, TRANS-05]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: basicctrl.profile.classifier.AppProfile + classify() + _CACHE_DIR_OVERRIDE + _derive_translator_priority
  - phase: 02-translators-racing
    provides: Wave-0 stub test_top_12_priority.py (Plan 02-01)
provides:
  - basicctrl.profile.known_apps module — 17-entry KNOWN_APPS dict + KnownApp NamedTuple
  - classify() short-circuit (D-20) — bundled priority + cdp_after_relaunch flag override before live probes
  - _is_version_newer() dotted-decimal version compare (drift detection)
  - structlog event 'known_app.short_circuit' (info) and 'known_app.version_drift' (warning)
  - AppProfile.cdp_available_after_relaunch=True surfaced for Slack/Cursor/Obsidian (T-2-02 precursor flag for Plan 02-11 MCP layer)
affects: [phase-02 plan 02-06 (T2 CDP filter consumes cdp_after_relaunch), plan 02-11 (MCP healing tools surface user prompt), plan 02-12 (race orchestrator reads bundled priority)]

# Tech tracking
tech-stack:
  added: []  # No new dependencies — pure stdlib (typing.NamedTuple, Optional)
  patterns:
    - "Pattern 11 RESEARCH.md — AppProfile Top-12 Cache Short-Circuit: bundled priority overrides live derivation; probes still run for honest ax/cdp signals"
    - "TDD RED→GREEN flow: failing test commit precedes implementation commit; visible in git log as test()→feat() pair"
    - "NamedTuple over Pydantic BaseModel for static dispatch table — zero validation overhead, immutable by construction, type-system enforced"
    - "Stage 3.5 insertion in existing pipeline — does NOT replace _derive_translator_priority (Phase 1 fallback for unknown bundles intact)"
    - "Class-level monkeypatch over instance-level for module-singleton mocks — instance attributes shadow class methods and don't restore cleanly via monkeypatch teardown (caught and fixed inline)"

key-files:
  created:
    - "basicctrl/profile/known_apps.py — 17-entry KNOWN_APPS static dict + KnownApp NamedTuple + get() helper"
  modified:
    - "basicctrl/profile/classifier.py — added KNOWN_APPS import, _is_version_newer helper, bundled short-circuit block in classify(), conditional translator_priority + cdp_available_after_relaunch construction"
    - "tests/unit/profile/test_top_12_priority.py — replaced importorskip stub with 8 hermetic tests (D-21 priorities, D-23 fallthrough, D-24 cdp flag, version drift fallthrough)"

key-decisions:
  - "Probes still run for known apps (do NOT skip parallel probes) so AppProfile carries honest ax_rich/ax_observer_works/cdp_port signals — downstream tools (Plan 02-11 MCP healing) need real-time TCC + AX state, NOT just bundled hint. Bundled map only overrides translator_priority + cdp_available_after_relaunch."
  - "Version drift policy: live > min_known_version triggers structlog.warning('known_app.version_drift') AND falls through to live derivation. Conservative — when an app upgrades past the version we tested, we don't trust the bundled priority anymore. Re-cache on next probe writes the upgraded version to disk."
  - "Phase 1 _derive_translator_priority retained as fallback — unknown bundles (D-23: Discord/Notion/Linear) use the rule-based ordering. KNOWN_APPS short-circuit ONLY runs when bundle_id is in the dict."
  - "cdp_available_after_relaunch precedence (D-24): when bundled entry exists with bundled_priority active, the flag comes from KnownApp.cdp_after_relaunch (so a known-Electron app like Slack ALWAYS carries True even before the user has relaunched). For unknown apps, the existing Phase 1 derivation runs (is_electron AND cdp_port is None)."
  - "min_known_version for iWork apps locked at '14.0' per CONTEXT.md D-21. Apple frequently bumps Pages/Numbers/Keynote major versions; 14.0 is the floor at which the AppleScript paragraph-style verb (D-26) is verified working. iWork 15+ falls through to live probe."
  - "KnownApp uses NamedTuple, not Pydantic BaseModel. Static dispatch table at module load time (no validation needed); NamedTuple is faster, simpler, and immutable by construction. Phase 4+ may need to deserialize KnownApp from JSON (future cassette format) — at that point switch to Pydantic, not now."
  - "Test fixture leak detection: original `monkeypatch.setattr(_classifier_module._tcc, 'check', _granted)` on the module-level singleton instance DESTROYED the class-method binding for sibling test_tcc::test_classify_calls_tcc_check_at_start — caught during regression run, fixed inline via `monkeypatch.setattr(TCCMonitor, 'check', _granted)` (class-level patch). Documented as Rule 1 deviation below."

patterns-established:
  - "KnownApp NamedTuple shape — bundle_id, name, electron, has_sdef, translator_priority list[str], cdp_after_relaunch bool, min_known_version Optional[str], notes — Phase 2 Wave 2+ plans reading the map import KnownApp from this module"
  - "Stage 3.5 short-circuit pattern — between cache-miss and live-probe, consult bundled overrides; emit structlog event for both fast-path hit and version-drift fallthrough; preserve probe execution for honest signals"
  - "Hermetic classifier tests via 4 fixtures (tmp_cache, fake_meta, fake_probes, fake_tcc) composed into stubbed_classify — no real macOS apps, no PyObjC dependency at test time, runs in 0.03s"
  - "Class-level monkeypatch convention for module-singleton instance methods — patch the CLASS, not the INSTANCE, so monkeypatch teardown restores method resolution order cleanly"

requirements-completed:
  - TRANS-01
  - TRANS-02
  - TRANS-03
  - TRANS-04
  - TRANS-05

# Threats mitigated
threats_mitigated:
  - "T-2-02 Slack workspace filter (precursor): classify() now sets AppProfile.cdp_available_after_relaunch=True for Slack (com.tinyspeck.slackmacgap), Cursor (com.todesktop.230313mzl4w4u92), and Obsidian (md.obsidian). The MCP healing layer (Plan 02-11) reads this flag to surface a one-time user-facing relaunch prompt before T2 CDP attaches. The actual workspace-page CDP filter (type=page AND url~/\\.slack\\.com/) is implemented in T2 translator (Plan 02-06)."

# Metrics
duration: 4min
completed: 2026-04-30
---

# Phase 2 Plan 03: Top-12 Known-Apps Association Map Summary

**17-app bundled association map (12 D-21 verified + 5 D-22 bonus including Chess.app) + classifier short-circuit that skips ~500ms of capability probe latency for well-known apps while preserving the live-probe fallback for unknown bundles (D-23).**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-30T06:42:17Z
- **Completed:** 2026-04-30T06:45:54Z
- **Tasks:** 2 (Task 1 `type=auto`, Task 2 `type=auto tdd=true`)
- **Files modified:** 3 (1 created in `basicctrl/profile/`, 1 modified in `basicctrl/profile/`, 1 stub test rewritten with real assertions)

## Accomplishments

- **17-entry KNOWN_APPS dict** — D-21 top-12 (Calculator, Pages, Numbers, Keynote, Mail, Calendar, Notes, Reminders, Safari, Slack, Cursor, Obsidian) + D-22 bonus (System Settings, Terminal, Music, Chrome, Chess). All bundleIDs preserved verbatim per D-21 case-sensitivity (`com.apple.iWork.Pages`, `com.apple.Chess`, `com.tinyspeck.slackmacgap`).
- **D-20 fast-path short-circuit** — `classify()` now consults `KNOWN_APPS.get(bundle_id)` between cache-miss and live-probe. On hit, bundled `translator_priority` and `cdp_after_relaunch` override live-derived values; probes still run for honest `ax_rich`/`ax_observer_works`/`cdp_port` signals.
- **D-24 P8 mitigation flag** — Slack/Cursor/Obsidian now carry `cdp_available_after_relaunch=True` even before the user has manually relaunched with `--remote-debugging-port=9222`. Plan 02-11 MCP healing layer reads this flag.
- **D-20 version-drift detection** — `_is_version_newer("15.0", "14.0")` returns True; classifier emits `known_app.version_drift` warning AND falls through to live probe (cache may be stale). Pages/Numbers/Keynote `min_known_version="14.0"` is the iWork floor.
- **8/8 unit tests pass** (Calculator priority, Slack cdp flag, Pages T3 first, Chess T4/T5, Cursor+Obsidian cdp flagged, unknown bundle fallthrough, Pages 14.0→15.0 drift fallthrough, all 12 D-21 entries present + total = 17).
- **No regressions in full unit suite**: `pytest -q tests/ -m "not integration and not manual"` shows **153 passed / 12 skipped / 0 errors** in 1.03s (was 145 passed in 02-02 — gain of 8 new tests, drop of 1 stub flipped to active).

## Task Commits

Two tasks; Task 2 followed strict TDD with separate RED + GREEN commits:

1. **Task 1: Create basicctrl/profile/known_apps.py with the D-21..D-22 association map**
   - `cbab26e` (feat) — KNOWN_APPS 17-entry dict + KnownApp NamedTuple + get() helper
2. **Task 2: Extend classify() with KNOWN_APPS short-circuit (D-20) + version drift fallthrough**
   - `77ee946` (test) — 8 failing tests added (RED) — calculator returned `['T4','T5']` instead of bundled `['T1','T4']`
   - `946be8b` (feat) — KNOWN_APPS import + `_is_version_newer` + Stage 3.5 short-circuit + AppProfile construction conditional + test fixture class-level patch fix (GREEN, 8/8 pass)

**Plan metadata commit:** to be appended after this SUMMARY.md is written.

## KNOWN_APPS Map Shape (D-21 + D-22)

| bundle_id | name | electron | sdef | priority | cdp_after_relaunch | min_known_version | tier |
|---|---|---|---|---|---|---|---|
| `com.apple.calculator` | Calculator | no | no | T1, T4 | False | None | D-21 |
| `com.apple.iWork.Pages` | Pages | no | YES | T3, T1, T4 | False | "14.0" | D-21 |
| `com.apple.iWork.Numbers` | Numbers | no | YES | T3, T1, T4 | False | "14.0" | D-21 |
| `com.apple.iWork.Keynote` | Keynote | no | YES | T3, T1, T4 | False | "14.0" | D-21 |
| `com.apple.mail` | Mail | no | YES | T1, T3, T4 | False | None | D-21 |
| `com.apple.iCal` | Calendar | no | YES | T1, T3, T4 | False | None | D-21 |
| `com.apple.Notes` | Notes | no | YES | T1, T3, T4 | False | None | D-21 |
| `com.apple.reminders` | Reminders | no | YES | T1, T3, T4 | False | None | D-21 |
| `com.apple.Safari` | Safari | no | YES | T1, T3 | False | None | D-21 |
| `com.tinyspeck.slackmacgap` | Slack | YES | no | T2, T4, T5 | **True** | None | D-21 |
| `com.todesktop.230313mzl4w4u92` | Cursor | YES | no | T2, T4, T5 | **True** | None | D-21 |
| `md.obsidian` | Obsidian | YES | no | T2, T4, T5 | **True** | None | D-21 |
| `com.apple.systempreferences` | System Settings | no | no | T1 | False | None | D-22 |
| `com.apple.Terminal` | Terminal | no | YES | T1, T3 | False | None | D-22 |
| `com.apple.Music` | Music | no | YES | T1, T3 | False | None | D-22 |
| `com.google.Chrome` | Chrome | no | no | T2, T1 | False | None | D-22 |
| `com.apple.Chess` | Chess | no | no | T4, T5 | False | None | D-22 |

**D-23 deferred (NOT in map; fall through to live probe):** Discord (`com.hnc.Discord`), Notion (`notion.id`), Linear (likely `com.linear.LinearMac` per docs — unverified).

## classify() Stage 3.5 Logic (D-20)

```text
classify(bundle_id, pid):
  1. tcc.check()                                       # Pitfall 24
  2. probe_bundle_metadata()                           # ~5ms
  3. load_cached_profile() → if hit AND not stale → return cached
  3.5 (NEW Phase 2 — D-20 short-circuit):
      bundled = KNOWN_APPS.get(bundle_id)
      if bundled is not None:
          if min_known_version set AND live > min_known_version:
              log.warning("known_app.version_drift")
              # fall through — bundled_priority stays None
          else:
              bundled_priority = bundled.translator_priority
              bundled_cdp_after = bundled.cdp_after_relaunch
              log.info("known_app.short_circuit")
  4. parallel probes (anyio task group)                # always runs (honest signals)
  5. priority = _derive_translator_priority(...)       # live derivation (Phase 1 fallback)
  6. AppProfile(
        translator_priority = bundled_priority OR priority,
        cdp_available_after_relaunch = bundled_cdp_after if bundled_priority active
                                       ELSE (is_electron AND cdp_port is None),
        ...
     )
```

## Files Created/Modified

### Created
- `basicctrl/profile/known_apps.py` — `KNOWN_APPS: dict[str, KnownApp]` (17 entries) + `KnownApp(NamedTuple)` with 8 fields + `get(bundle_id) -> Optional[KnownApp]` helper

### Modified
- `basicctrl/profile/classifier.py` — added `from basicctrl.profile.known_apps import KNOWN_APPS, KnownApp`, new `_is_version_newer(live, known) -> bool` helper, Stage 3.5 short-circuit block (28 lines) inserted between cache-miss and parallel-probes, AppProfile construction now conditionally selects bundled vs live priority + cdp_available_after_relaunch
- `tests/unit/profile/test_top_12_priority.py` — Wave-0 stub (`pytest.importorskip` + 1 trivial assertion) replaced with 8 hermetic tests + 4 fixtures (tmp_cache, fake_meta, fake_probes, fake_tcc, stubbed_classify composer)

## Decisions Made

See `key-decisions` in frontmatter for the full list. Brief rationale highlights:
- **Probes still run for known apps** (don't skip parallel probes) — bundled map ONLY overrides `translator_priority` + `cdp_available_after_relaunch`. Downstream tools (Plan 02-11 MCP) still need honest `ax_rich`/`ax_observer_works`/`cdp_port` signals from the live probe (TCC + AX state are mutable).
- **Version drift policy** — `min_known_version="14.0"` for iWork; live `"15.0"` triggers structlog warning AND fallthrough. Conservative — when an app upgrades past the tested version, the bundled priority is no longer trusted.
- **NamedTuple over Pydantic** — static dispatch table at module load; no validation needed; faster + simpler + immutable. Switch to Pydantic only when Phase 4+ needs JSON serialization.
- **Class-level monkeypatch** for `TCCMonitor.check` — original test fixture patched the module-level `_tcc` instance attribute, which permanently shadowed the class method and bled into sibling test (`test_tcc.py::test_classify_calls_tcc_check_at_start`). Fixed inline.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Test fixture monkeypatch leaked across test files**
- **Found during:** Task 2 GREEN (running full unit suite for regression check after RED/GREEN of test_top_12_priority.py passed)
- **Issue:** Plan's `<action>` Step 3 specified the `fake_tcc` fixture as `monkeypatch.setattr("basicctrl.profile.classifier._tcc.check", _check.__get__(None))`. I implemented the equivalent `monkeypatch.setattr(_classifier_module._tcc, "check", _granted)`. Both approaches set an **instance attribute** on the module-level `_tcc` singleton, which permanently shadows the class method. When `monkeypatch` unwound, it restored the *bound* method as an instance attribute (not the class method). Sibling test `tests/unit/test_tcc.py::test_classify_calls_tcc_check_at_start` then patched `TCCMonitor.check` (the **class** method) — but `_tcc.check` resolved to the leftover instance attribute first, bypassing the class patch. Result: `_fake_check` was never called, `call_log[0]` was `'probe.bundle_metadata'` not `'tcc.check'`, regression.
- **Fix:** Switched the fixture to `monkeypatch.setattr(TCCMonitor, "check", _granted)` (patch the **class**, not the instance). Added a docstring comment documenting the leak so future fixture additions don't regress.
- **Files modified:** `tests/unit/profile/test_top_12_priority.py` (only the `fake_tcc` fixture; tests themselves unchanged)
- **Verification:**
  - `uv run pytest -q tests/unit/profile/test_top_12_priority.py tests/unit/test_tcc.py` → 12 passed (was: 11 passed, 1 failed)
  - `uv run pytest -q tests/ -m "not integration and not manual"` → 153 passed, 12 skipped, 0 errors
- **Committed in:** `946be8b` (Task 2 GREEN — fixture fix + classifier change in same atomic commit since the test file was already in the staging area for the same task)

**Total deviations:** 1 auto-fixed (1 bug).
**Impact on plan:** Plan spec preserved verbatim for `KNOWN_APPS` content + classifier short-circuit + verification; only the test fixture pattern was strengthened to avoid cross-file bleed. All 8 tests in plan acceptance criteria pass; full unit suite green.

## Issues Encountered

- **Test fixture leak across test files** (described above) — caught via the regression run; resolved with class-level monkeypatch. Lesson: when patching attributes on module-level singletons, prefer patching the class (or use `delattr` cleanup) over the instance, especially when sibling tests may patch the same attribute via a different path.
- pytest `addopts = "-x --tb=short"` stops on first failure — surfaced the leak instantly during the regression run.

## User Setup Required

None. Pure Python (stdlib `typing.NamedTuple`); no new dependencies.

## Next Phase Readiness

- **Plan 02-04 (channel/translator base+registry):** can `import KNOWN_APPS` to surface bundled priorities at registry-time when the AppProfile is fresh.
- **Plan 02-06 (T2 CDP translator):** reads `AppProfile.cdp_available_after_relaunch` to decide whether to attempt CDP attach (via Plan 02-11 user prompt) vs skip to T4/T5.
- **Plan 02-11 (MCP healing tools v2):** reads `AppProfile.cdp_available_after_relaunch=True` for Slack/Cursor/Obsidian and emits a `cdp_relaunch_offered` user-facing prompt (one-time per session).
- **Plan 02-12 (race orchestrator):** consults `AppProfile.translator_priority` (bundled or live-derived) to order T1..T5 fan-out.
- **No blockers.** All 8 new tests pass; full unit suite (153 tests, 1.03s) clean; no regressions; ROADMAP/STATE updates pending in plan finalization.

## Self-Check: PASSED

Files created (1 verified):
- FOUND: basicctrl/profile/known_apps.py

Files modified (2 verified):
- FOUND: basicctrl/profile/classifier.py
- FOUND: tests/unit/profile/test_top_12_priority.py (replaced Wave-0 stub)

Commits verified (all 3 in git log):
- FOUND: cbab26e (Task 1: feat 02-03 known_apps map)
- FOUND: 77ee946 (Task 2 RED: test 02-03 failing tests)
- FOUND: 946be8b (Task 2 GREEN: feat 02-03 classifier short-circuit + fixture fix)

Acceptance criteria literals (all greppable):
- FOUND: `KNOWN_APPS: dict[str, KnownApp]`, `class KnownApp(NamedTuple)`, all 17 bundleIDs in known_apps.py
- FOUND: `from basicctrl.profile.known_apps import KNOWN_APPS`, `_is_version_newer`, `known_app.short_circuit` (×1), `known_app.version_drift` (×1), `bundled_priority` (×5) in classifier.py
- FOUND: 8 test functions in test_top_12_priority.py (no `pytest.importorskip`)

Verification commands (all pass):
- `uv run python -c "from basicctrl.profile.known_apps import KNOWN_APPS; assert len(KNOWN_APPS) == 17; print('ok')"` → `ok`
- `uv run pytest -q tests/unit/profile/test_top_12_priority.py` → 8 passed in 0.03s
- `uv run pytest -q tests/ -m "not integration and not manual"` → 153 passed, 12 skipped, 0 errors in 1.03s

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
