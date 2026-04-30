---
phase: 02-translators-racing
plan: 07
subsystem: t3-applescript-translator-c4-channel
tags: [TRANS-03, ACT-01, ACT-04, T3, C4, py-applescript, NSAppleScript, OSAKit, ThreadPoolExecutor, D-04, D-14, D-15, D-22, P5, T-2-01, T-2-03, T-2-08]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: cua_overlay.state.graph.UIElement + Bbox + Source.APPLESCRIPT, cua_overlay.state.causal_dag.ActionCanonical, cua_overlay.persist.session_writer.SessionWriter
  - phase: 02-translators-racing
    provides: cua_overlay.translators.base (Translator Protocol, TranslatorTarget with as_target_spec field, TargetSpec.as_verb from Plan 02-04), cua_overlay.actions.channels.base (Channel Protocol, ChannelOutcome from Plan 02-04), cua_overlay.actions.idempotency.IdempotencyTokenStore (Plan 02-02)
  - external: py-applescript==1.0.3 (D-04; verified PyPI 2022-01-23 / API frozen; pulls pyobjc-framework-OSAKit transitively)
provides:
  - cua_overlay.translators.t3_applescript.T3AppleScriptTranslator — concrete T3 translator (tier='T3') wrapping py-applescript 1.0.3 NSAppleScript on a dedicated ThreadPoolExecutor(max_workers=2, thread_name_prefix='cua-as')
  - cua_overlay.translators.t3_applescript._compiled_cache — module-level dict[source_string, applescript.AppleScript] (Pitfall E mitigation)
  - cua_overlay.actions.channels.c4_applescript.C4AppleScriptChannel — concrete C4 channel (name='C4') that delegates to T3.execute (NOT a new ThreadPoolExecutor — reuses T3's pool)
  - 7 unit tests for T3 (mocked applescript module via patch.dict + thread isolation assertion)
  - 8 unit tests for C4 (fake T3 test double + idempotency + cancel + missing-spec + raise-containment)
affects:
  - phase-02 plan 02-10 (race orchestrator wires T3+C4 alongside T1+C2 and T2+C5 as third default tier-channel pair per D-14; D-15 500ms stagger applied at orchestrator level, NOT inside C4)
  - phase-02 plan 02-12 (Pages T3-wins integration test calls T3AppleScriptTranslator.execute end-to-end against running Pages.app per D-26)
  - plans 02-08..02-09 (T4/T5 follow same Translator+Channel implementation shape; T3+C4 is the third canonical reference pair after T1+C2 and T2+C5)

# Tech tracking
tech-stack:
  added: []  # py-applescript==1.0.3 already pinned in pyproject.toml from Phase 1
  patterns:
    - "Translator Protocol implementation #3 — T3AppleScriptTranslator implements Translator without nominal subclassing (duck-typed @runtime_checkable Protocol from Plan 02-04). Same shape as T1AXTranslator + T2CDPTranslator."
    - "Channel Protocol implementation #3 — C4AppleScriptChannel implements Channel similarly. Same shape as C2AXPressChannel + C5CDPInputChannel."
    - "Cross-thread isolation pattern (T-2-03) — translator owns the dedicated ThreadPoolExecutor; channel reuses it via a typed protocol (_T3Like) rather than spinning up its own pool. Keeps the 'AS calls never run on the main asyncio loop thread' property uniformly enforced. Reusable for any future translator-channel pair where the underlying syscall has its own thread-affinity requirements."
    - "Module-level compiled-script cache (Pitfall E) — a module-scoped dict[source_string, applescript.AppleScript] guarded by threading.Lock. Re-instantiating the translator (e.g. across tests) does NOT invalidate compiled scripts. Cache key is the raw source string (not parsed; parser overhead is what we're avoiding)."
    - "Mocked-applescript unit test pattern — patch.dict('sys.modules', {'applescript': SimpleNamespace(AppleScript=Fake, ScriptError=Exception)}) lets unit tests run on any host without py-applescript actually compiling. Reusable for any future PyObjC framework wrapper."
    - "TDD strict per task — RED commit (failing tests) → GREEN commit (implementation). Same shape as Plan 02-05 / 02-06 (4 commits total: 2 RED + 2 GREEN)."

key-files:
  created:
    - "cua_overlay/translators/t3_applescript.py — T3AppleScriptTranslator + module-level _compiled_cache dict + threading.Lock + _APP_NAMES bundle→AS-name table"
    - "cua_overlay/actions/channels/c4_applescript.py — C4AppleScriptChannel (try_claim → cancel-check → spec-validate → translator.execute on shared cua-as pool)"
    - "tests/unit/actions/channels/test_c4_applescript.py — 8 unit tests with _FakeT3 test double"
  modified:
    - "cua_overlay/translators/__init__.py — re-exports T3AppleScriptTranslator alongside T1/T2"
    - "cua_overlay/actions/channels/__init__.py — re-exports C4AppleScriptChannel alongside C2/C5"
    - "tests/unit/translators/test_t3_applescript.py — replaced Wave-0 importorskip stub with 7 mocked-applescript tests"

key-decisions:
  - "Module-level _compiled_cache (rather than instance-level) — per CONTEXT.md Pitfall E, recompile costs 50-200ms and must be amortized across the lifetime of a session. Instance-level caching would lose the cache when the translator is re-instantiated (e.g. between tests, or if Plan 02-10 re-creates the registry). Module-level survives re-instantiation; the threading.Lock makes it safe under concurrent T3 instances (none expected in production but defensive)."
  - "C4 reuses T3's executor via _T3Like protocol (rather than constructing its own ThreadPoolExecutor) — per CONTEXT.md D-04 the executor MUST be dedicated AND shared between resolution and fire. If C4 had its own pool, T-2-03 isolation would be split across two pools (which is fine for thread isolation but doubles the worker thread count and breaks the max_workers=2 bound). Sharing also means tests that exercise resolve+fire don't need to coordinate two pools."
  - "C4's _T3Like is a structural Protocol (not a nominal type) — lets unit tests inject _FakeT3 without subclassing T3AppleScriptTranslator. Matches the duck-typed Protocol pattern Plan 02-04 established for Translator and Channel."
  - "execute() returns (result, error) tuple rather than raising — channels MUST NOT propagate exceptions (Channel Protocol contract). Forcing the translator to flatten errors into a value-typed return makes the channel implementation simpler and the contract grep-checkable."
  - "8 unit tests for C4 (Rule 2 deviation: matches Plans 02-05 / 02-06 pattern) — the plan only specified a 1-liner smoke test as <verify>. CI without macOS apps would have zero coverage for C4's fire-path contract. Added the same shape as C2 (5 tests) + C5 (9 tests): name='C4', fired/skipped/cancelled/errored mapping, missing-as_target_spec defense, unexpected-raise containment, default-translator construction. Verifies fake_t3.calls == [] when claim is lost AND when cancel_event is set — proving the no-execute-on-skip property."
  - "validate() returns True iff as_target_spec is non-empty — per Pitfall P5, AS calls are slow (50-200ms baseline), so we don't pre-probe. The verifier's L1 AX subtree re-read post-fire is the analogous validity check; a pre-probe would double the AS call cost for marginal benefit."
  - "Default channel translator construction (`C4AppleScriptChannel()` with no args creates its own T3) — convenient for unit tests, but production uses the shared registry instance. The local T3 spins its own ThreadPoolExecutor, which violates T-2-03 isolation IF combined with the registry T3 in the same process. Documented in C4.__init__ docstring; Plan 02-10 race orchestrator MUST pass the shared registry T3 explicitly."

patterns-established:
  - "Wave-2 plan shape continues from 02-05 / 02-06: replace Wave-0 importorskip stub with TDD RED → GREEN per task. Plans 02-08 (T4 Vision) and 02-09 (T5 Pixel + C1 + C3) follow this exact shape."
  - "Cross-thread isolation via shared executor — when a translator owns a dedicated thread pool for its underlying syscalls, the matching channel takes the translator (not a new pool) and delegates. Plan 02-09 (T5 Pixel + CGEvent.postToPid) may follow if CGEvent post needs similar thread affinity."
  - "Module-level cache dict + threading.Lock pattern — when amortizing compile/init costs across instance recreations, use a module-level dict and explicit threading.Lock. The lock guards mutation only; reads are lock-free (intentional — readers see at-rest snapshot, writers serialize)."

requirements-completed:
  - TRANS-03
  - ACT-01
  - ACT-04

# Threats mitigated
threats_mitigated:
  - "T-2-01 race ordering — C4.fire calls store.try_claim(action.id, 'C4') BEFORE submitting to T3.execute. Second fire on same action_id returns ChannelOutcome(status='skipped', skipped_reason='idempotency_lost'). Verified by tests/unit/actions/channels/test_c4_applescript.py::test_fire_skipped_on_idempotency_lost (asserts fake_t3.calls == [] when claim lost — translator NOT invoked)."
  - "T-2-03 AS thread isolation — T3 owns concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix='cua-as'); execute() submits via loop.run_in_executor(self._exec, ...). C4 reuses T3's pool — does NOT spin its own. The dedicated-executor property is grep-enforced (max_workers=2, thread_name_prefix='cua-as' in t3_applescript.py) AND runtime-asserted (test_executor_is_dedicated_pool checks _max_workers == 2 and submitted task thread name carries 'cua-as'; test_execute_runs_on_dedicated_executor checks the same property end-to-end via the AS execution path)."
  - "T-2-08 race-cancel correctness — C4.fire checks cancel_event.is_set() AFTER try_claim and BEFORE the AS call. When set, returns ChannelOutcome(status='cancelled') without invoking T3.execute (verified via fake_t3.calls == []). The claim is HELD (action_id stays burned) so the orchestrator's race winner stays canonical. The AppleEvent itself is uncancellable mid-flight; D-15 stagger 500ms (Plan 02-10) is the larger mitigation that pushes execution past most race windows so this pre-call check usually wins. Verified by tests/unit/actions/channels/test_c4_applescript.py::test_fire_cancelled_when_cancel_event_set."
  - "Pitfall E (compile-cost amortization) — module-level _compiled_cache dict caches applescript.AppleScript instances per source string. Verified by tests/unit/translators/test_t3_applescript.py::test_execute_caches_compiled_script (asserts _FakeScript.__init__ called exactly once across two execute() calls with the same source)."
  - "Pitfall P5 (AS call cost) — validate() returns True iff as_target_spec is non-empty (no pre-probe). The 50-200ms AS baseline is incurred only at execute time, never on the validate path. Plan 02-10 race orchestrator's D-15 500ms stagger gives faster channels first crack; T3+C4 typically lose to T1+C2 / T2+C5 except where AS is the only tier that addresses the target (D-26 Pages paragraph styles)."
  - "D-04 hard rule (no fork+exec CLI tool) — both t3_applescript.py and c4_applescript.py contain ZERO occurrences of the literal `osascript` substring AND zero `subprocess.` calls. Grep-enforced as success criterion: `grep -c 'osascript' cua_overlay/translators/t3_applescript.py cua_overlay/actions/channels/c4_applescript.py` returns 0 + 0."

# Metrics
duration: 4min
completed: 2026-04-30
---

# Phase 2 Plan 07: T3 AppleScript Translator + C4 AppleScript Channel Summary

**T3 AppleScript translator + C4 AppleScript channel ship together as the canonical D-14 default tier-channel pair for AS-addressable apps (iWork, Mail, Notes, Calendar, Reminders, Safari, Terminal, Music). T3 wraps py-applescript 1.0.3 (in-process NSAppleScript via PyObjC OSAKit) on a dedicated ThreadPoolExecutor(max_workers=2, thread_name_prefix='cua-as') with a module-level compiled-script cache for Pitfall E recompile-cost amortization. C4 delegates to T3's pool (does NOT spin its own) — keeping the T-2-03 isolation property uniformly enforced. The D-04 hard rule (no fork+exec CLI tool) is grep-enforced: zero `osascript` / `subprocess.` literals across both modules.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-30T07:28:27Z
- **Completed:** 2026-04-30T07:32:54Z
- **Tasks:** 2 (both `type=auto tdd=true`)
- **Files created:** 3 (cua_overlay/translators/t3_applescript.py, cua_overlay/actions/channels/c4_applescript.py, tests/unit/actions/channels/test_c4_applescript.py)
- **Files modified:** 3 (cua_overlay/translators/__init__.py, cua_overlay/actions/channels/__init__.py, tests/unit/translators/test_t3_applescript.py — replaced Wave-0 stub)

## Task Commits

1. **Task 1 RED — failing T3AppleScriptTranslator unit tests:** `dac9fa8` (test) — 7 tests; ModuleNotFoundError on import.
2. **Task 1 GREEN — T3AppleScriptTranslator implementation:** `e7ab2e1` (feat) — 7/7 unit tests pass; full unit suite 206 passed (was 199 after 02-06).
3. **Task 2 RED — failing C4AppleScriptChannel tests:** `5a3392e` (test) — 8 unit tests; ModuleNotFoundError on import.
4. **Task 2 GREEN — C4AppleScriptChannel implementation:** `637c96a` (feat) — 8/8 unit tests pass; full unit suite 214 passed.

## D-14 T3→C4 Default Binding Verified

Per CONTEXT.md D-14 the canonical Phase 2 default tier-channel mapping is:

| Tier | Channel | Method | Plan / Test |
|------|---------|--------|-------------|
| T1 (AX) | C2 (kAXPress) | `AXUIElementPerformAction(elem, "AXPress")` | 02-05 (shipped, Calculator integ) |
| T2 (CDP) | C5 (Input.dispatchMouseEvent) | `cdp.send.Input.dispatchMouseEvent(mousePressed/mouseReleased)` | 02-06 (shipped, mocked unit; Slack integ in 02-12) |
| **T3 (AS)** | **C4 (AppleScript)** | `applescript.AppleScript(source).run()` on cua-as ThreadPool | **02-07 (this plan, mocked unit; Pages integ in 02-12)** |
| T4 (Vision) | C1 (CGEvent public) | (Plans 02-08, 02-09) | (Plan 02-08) |
| T5 (Pixel) | C3 (CGEvent postToPid) | (Plan 02-09) | (Plan 02-09) |

This plan ships the THIRD default-binding pair end-to-end at the unit-test level. The remaining 2 pairs follow in 02-08..02-09; the Pages T3-wins live integration test (D-26) lands in 02-12.

## T3 Resolution Flow

```
TargetSpec(as_verb='make new paragraph style with properties {name:"BoldTest"}', label='Pages')
   ↓
T3.resolve(bundle_id="com.apple.iWork.Pages", pid, target_spec)
   ↓
1. _build_target_spec(bundle_id, target_spec):
     app_name = _APP_NAMES["com.apple.iWork.Pages"]  # "Pages"
     return f'tell application "{app_name}" to {target_spec.as_verb}'
     # → 'tell application "Pages" to make new paragraph style with properties {name:"BoldTest"}'
   ↓ spec
2. Build synthetic UIElement(role="AXUnknown", role_path="AppleScript[com.apple.iWork.Pages]",
                              source=[Source.APPLESCRIPT], ...)
   ↓
3. TranslatorTarget(element=synthetic_element, as_target_spec=spec)
   ↓
   (note: T3 does NOT walk an AX tree — AS addresses targets by name.
    The verifier's post-fire AX subtree re-read or push-notification
    populates the actual element.)
```

## T3 Execute Flow (Pitfall E + T-2-03)

```
T3.execute(source: str, args: tuple = ()) -> tuple[str, Optional[str]]:
   ↓
1. loop = asyncio.get_running_loop()
   ↓
2. def _sync():
     import applescript                    ← lazy import (test-friendly)
     with _compiled_lock:                  ← module-level threading.Lock
       scpt = _compiled_cache.get(source)
       if scpt is None:
         scpt = applescript.AppleScript(source=source)  ← compile (50-200ms, Pitfall E)
         _compiled_cache[source] = scpt    ← cache for next call
     try:
       result = scpt.run(*args)            ← AppleEvent dispatch (50-200ms baseline)
       return (str(result), None)
     except Exception as exc:
       return ("", f"runtime_error: {exc}")  ← errors NEVER escape
   ↓
3. return await loop.run_in_executor(self._exec, _sync)
   ↓
   self._exec = ThreadPoolExecutor(max_workers=2, thread_name_prefix='cua-as')
   ← T-2-03: NOT asyncio's default executor; the dedicated cua-as pool
```

## C4 Fire Flow

```
C4.fire(action, target, store, cancel_event):
   ↓
1. claim = await store.try_claim(action.id, "C4")
   if claim is None: return ChannelOutcome(status="skipped", skipped_reason="idempotency_lost")
   ↓ T-2-01: claim BEFORE T3.execute (translator NOT invoked when claim lost)
2. if cancel_event.is_set(): return ChannelOutcome(status="cancelled")
   ↓ T-2-08: AppleEvent uncancellable mid-flight; this is the only kill-switch.
       D-15 500ms stagger (Plan 02-10) makes this check likely to fire when
       a faster channel (C2/C5) has already won.
3. if not target.as_target_spec: return ChannelOutcome(status="errored", error="missing as_target_spec")
   ↓ defensive against orchestrator routing bugs
4. try:
     result, err = await self._t3.execute(target.as_target_spec)
   except Exception as exc:
     return ChannelOutcome(status="errored", error=str(exc))
   ↓ runs on T3's dedicated cua-as ThreadPoolExecutor (T-2-03 reused, NOT new pool)
5. if err is not None: return ChannelOutcome(status="errored", error=err)
   ↓
6. return ChannelOutcome(status="fired", fired_at_ns=time.monotonic_ns())
```

## Files Created/Modified

### Created
- `cua_overlay/translators/t3_applescript.py` (~190 lines) — T3AppleScriptTranslator
  - tier='T3' Literal Protocol field
  - Module-level `_compiled_cache: dict[str, Any]` + `_compiled_lock: threading.Lock` (Pitfall E)
  - `_APP_NAMES` table (10 bundles: iWork x3, Mail, Calendar, Notes, Reminders, Safari, Terminal, Music)
  - `__init__` constructs ThreadPoolExecutor(max_workers=2, thread_name_prefix='cua-as')
  - `shutdown()` + `__del__` for lifecycle
  - `executor` property — public accessor so C4 can reuse the pool (T-2-03)
  - `_build_target_spec(bundle_id, target_spec)` — wraps as_verb in `tell application "..." to ...`
  - `resolve(bundle_id, pid, target_spec)` — synthetic TranslatorTarget with as_target_spec
  - `validate(target)` — non-empty as_target_spec check
  - `execute(source, args)` — submits to dedicated cua-as pool via `loop.run_in_executor(self._exec, ...)`
- `cua_overlay/actions/channels/c4_applescript.py` (~140 lines) — C4AppleScriptChannel
  - name='C4' Literal Protocol field
  - `_T3Like` Protocol (structural duck-typing for the translator dependency)
  - `__init__(translator=None)` — defaults to local T3 (test-friendly); production passes shared registry instance
  - `fire(action, target, store, cancel_event)` — try_claim → cancel-check → spec-validate → translator.execute on shared cua-as pool
- `tests/unit/actions/channels/test_c4_applescript.py` (~240 lines) — 8 unit tests with _FakeT3

### Modified
- `cua_overlay/translators/__init__.py` — adds `T3AppleScriptTranslator` export
- `cua_overlay/actions/channels/__init__.py` — adds `C4AppleScriptChannel` export
- `tests/unit/translators/test_t3_applescript.py` — replaced Wave-0 importorskip stub with 7 mocked-applescript tests

## D-15 500ms Stagger Note (deferred to Plan 02-10)

Per CONTEXT.md D-15 the AppleScript stagger window is **500ms default, tunable per-recipe** (`as_class: "fast"` = 0ms, `as_class: "slow"` = 500ms). This is enforced **at the race orchestrator** (Plan 02-10), NOT inside C4. C4.fire returns immediately when invoked; the orchestrator decides when to invoke it relative to other channels.

The rationale (per Pitfall P5 + macOS26-Agent AppleEvent hang documentation):
- AS calls cost 50-200ms baseline; staggering them 500ms behind faster channels (C2/C5) means T3+C4 typically loses cleanly to a faster winner before its AppleEvent commits.
- The pre-call cancel_event check in C4.fire then short-circuits the AS dispatch — confirmed by `test_fire_cancelled_when_cancel_event_set` (asserts `fake_t3.calls == []` when cancelled).
- For apps where AS is the only tier that addresses the target (D-26 Pages paragraph styles), the orchestrator skips the stagger and lets T3+C4 race normally — no other channel can win, so the 500ms penalty would be wasted latency.

This split (stagger at orchestrator, kill-switch in channel) is the **canonical pattern for any future channel with an uncancellable mid-flight syscall** — Plans 02-08 / 02-09 may follow if their underlying primitives have similar hang-risk surface.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] D-04 grep-enforced 'osascript' literal in module docstring**
- **Found during:** Task 1 GREEN (acceptance criteria check)
- **Issue:** Module docstring contained the literal `osascript` substring in prose ("NEVER `osascript` subprocess") which the strict acceptance criterion `grep -c 'osascript' cua_overlay/translators/t3_applescript.py` correctly flagged as 1 (must be 0). Same pattern as Plan 02-06's D-03 grep deviation.
- **Fix:** Rephrased docstring to "NEVER the fork+exec CLI tool path"; preserved the D-04 reference for human readers.
- **Files modified:** `cua_overlay/translators/t3_applescript.py` (docstring only)
- **Commit:** `e7ab2e1` (rolled into Task 1 GREEN since the file hadn't been committed yet between bug discovery and fix)

**2. [Rule 2 - Missing critical functionality] Added 8 unit tests for C4 (plan specified only a 1-liner smoke test)**
- **Found during:** Task 2 planning
- **Issue:** Plan's `<verify>` was just `python -c "from cua_overlay.actions.channels import C4AppleScriptChannel; ch = C4AppleScriptChannel(); assert ch.name == 'C4'; print('ok')"`. CI without macOS apps would have zero coverage for C4's fire-path contract — the same gap C2 had in Plan 02-05 and C5 had in Plan 02-06 (both also added unit tests as a Rule 2 deviation; this is now an established pattern).
- **Fix:** 8 unit tests with `_FakeT3` test double covering: name='C4', fired-on-success, skipped-on-idempotency-lost (asserts `fake_t3.calls == []` — translator NOT invoked when claim lost), cancelled-on-cancel-event (asserts `fake_t3.calls == []` — translator NOT invoked when cancelled), errored-on-missing-as_target_spec, errored-on-translator-runtime-error, errored-on-translator-unexpected-raise (channel boundary contract — never raises across), default-translator-construction.
- **Files modified:** `tests/unit/actions/channels/test_c4_applescript.py`
- **Commit:** `5a3392e` (RED) + `637c96a` (GREEN — no impl change needed for unit tests beyond what's already specified)

## Issues Encountered

- **Multiple PreToolUse:Edit / PreToolUse:Write hook re-prompts** — runtime asks the agent to re-read files between edits. All files had been read or written in this session; edits succeeded as confirmed by post-edit `pytest` and `grep` runs. No content changes lost.
- **No real Pages integration test in this plan** — per the plan's success criteria + Phase 2 wave structure, real-app integration tests live in Plan 02-12 (Pages T3-wins per D-26). This plan ships the unit-tested T3+C4; 02-12 will exercise it against a running Pages.app with a real `make new paragraph style with properties {...}` verb.

## User Setup Required

None for unit tests — they run on any host with `py-applescript==1.0.3` (already in `pyproject.toml` from Phase 1). The applescript module is mocked via `patch.dict('sys.modules', {'applescript': fake_module})` so the real PyObjC OSAKit bridge isn't touched in tests.

For Plan 02-12's eventual Pages integration test (D-26):
- macOS Automation TCC granted to the Python interpreter for Pages.app (system prompt fires once on first AS call from this binary)
- Pages.app installed (iWork bundle from Mac App Store)
- The test creates a paragraph style; cleanup deletes test styles to keep the doc clean

## Next Plan Readiness

- **Plan 02-08 (T4 Vision via uitag + ocrmac):** can `from cua_overlay.translators.base import Translator, TranslatorTarget, TargetSpec` + `from cua_overlay.actions.channels.base import Channel, ChannelOutcome` and follow the same TDD RED→GREEN shape as 02-05 / 02-06 / 02-07. Will use `uitag==0.6.0` + `ocrmac==1.0.1` per CONTEXT.md D-05; binds to C1 by default per D-14. Per RESEARCH Pitfall C uitag is sync — use `await asyncio.to_thread(run_pipeline, ...)` (note: this CAN use the default executor since uitag is CPU-bound MLX inference, not AppleEvent dispatch).
- **Plan 02-09 (T5 Pixel + C1 + C3):** CGWindowList screen reads + ImageHash dHash + CGEvent.postToPid wiring. C3 may follow C4's "reuse-translator-pool" pattern if CGEvent post needs thread affinity (likely not — postToPid is synchronous and short).
- **Plan 02-10 (race orchestrator):** wires `TranslatorRegistry.select_for_priority(profile.translator_priority)` against `ChannelRegistry.select(priority, race_policy)` with `IdempotencyTokenStore` + `cancel_event`. Three default-binding pairs are now ready to race: T1+C2, T2+C5, T3+C4. D-15 500ms stagger applied here, NOT inside C4.
- **Plan 02-12 (Pages T3-wins integration test, D-26):** real AS verb against running Pages.app; depends on Plan 02-10 (race orchestrator) and the user's Pages installation + Automation TCC grant.
- **No blockers.** All 15 unit tests pass (7 T3 + 8 C4). Full unit suite 214 passed.

## Self-Check: PASSED

Files created (verified via `[ -f path ]`):
- FOUND: `cua_overlay/translators/t3_applescript.py`
- FOUND: `cua_overlay/actions/channels/c4_applescript.py`
- FOUND: `tests/unit/actions/channels/test_c4_applescript.py`

Files modified (verified):
- FOUND: `cua_overlay/translators/__init__.py` (re-exports T3AppleScriptTranslator)
- FOUND: `cua_overlay/actions/channels/__init__.py` (re-exports C4AppleScriptChannel)
- FOUND: `tests/unit/translators/test_t3_applescript.py` (replaced Wave-0 stub with 7 mocked tests)

Commits verified (all in `git log --oneline`):
- FOUND: `dac9fa8` test(02-07): RED T3AppleScriptTranslator
- FOUND: `e7ab2e1` feat(02-07): GREEN T3AppleScriptTranslator
- FOUND: `5a3392e` test(02-07): RED C4AppleScriptChannel
- FOUND: `637c96a` feat(02-07): GREEN C4AppleScriptChannel

Acceptance criteria literals (all greppable, verified):
- FOUND: `class T3AppleScriptTranslator`, `concurrent.futures.ThreadPoolExecutor`, `max_workers=2`, `thread_name_prefix="cua-as"`, `_compiled_cache` in `cua_overlay/translators/t3_applescript.py`
- VERIFIED: `grep -c 'osascript' cua_overlay/translators/t3_applescript.py` returns 0 (D-04 hard rule)
- VERIFIED: `grep -c 'subprocess\.' cua_overlay/translators/t3_applescript.py` returns 0 (D-04 hard rule)
- FOUND: `T3AppleScriptTranslator` in `cua_overlay/translators/__init__.py`
- FOUND: `class C4AppleScriptChannel`, `name: Literal["C1", "C2", "C3", "C4", "C5"] = "C4"`, `try_claim(action.id, "C4")`, `self._t3.execute` in `cua_overlay/actions/channels/c4_applescript.py`
- VERIFIED: `grep -c 'osascript' cua_overlay/actions/channels/c4_applescript.py` returns 0
- VERIFIED: `grep -c 'subprocess\.' cua_overlay/actions/channels/c4_applescript.py` returns 0
- FOUND: `C4AppleScriptChannel` in `cua_overlay/actions/channels/__init__.py`

Verification commands (all pass):
- `uv run pytest -q tests/unit/translators/test_t3_applescript.py` → 7 passed in 0.07s
- `uv run pytest -q tests/unit/actions/channels/test_c4_applescript.py` → 8 passed in 0.08s
- `uv run pytest -q tests/unit/translators/test_t3_applescript.py tests/unit/actions/channels/test_c4_applescript.py` → 15 passed in 0.08s
- `grep -c "osascript" cua_overlay/translators/t3_applescript.py cua_overlay/actions/channels/c4_applescript.py` → 0 + 0
- `uv run python -c "from cua_overlay.translators import T3AppleScriptTranslator; from cua_overlay.actions.channels import C4AppleScriptChannel; print('ok')"` → `ok`
- `SKIP_INTEGRATION=1 uv run pytest -q tests/ -m "not integration and not manual"` → 214 passed, 9 skipped, 29 deselected in 1.08s (was 199 after 02-06; +15 from this plan's 7 T3 + 8 C4 unit tests)

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
