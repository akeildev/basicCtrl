---
phase: 02-translators-racing
plan: 10
subsystem: actions
tags: [race-orchestrator, anyio, idempotency, hoare-triple, ax-observer, applescript-stagger]

requires:
  - phase: 01-foundation
    provides: AXObserverManager.expect, Aggregator.verify, L1Cheap.snapshot, ActionCanonical, HoarePost, SessionWriter, AppProfile classifier
  - phase: 02-translators-racing
    provides: TranslatorRegistry (02-01), ChannelRegistry + tier_for_channel (02-04), IdempotencyTokenStore (02-02), DuplicateReceipt (02-02), resolve_race_policy (02-02), Translator + Channel Protocols, T1-T5 translators (02-05..02-09), C1-C5 channels (02-04..02-09)
provides:
  - "RaceOrchestrator.execute(bundle_id, pid, target_spec, action_type, payload, race_policy) -> tuple[ActionCanonical, HoarePost]"
  - "race_first_complete anyio FIRST_COMPLETED workaround per D-13"
  - "12-step orchestrator contract: policy gate -> classify -> resolve target -> build action -> subscribe AX -> capture HoarePre -> pick channels -> AS stagger -> race or single -> verify -> duplicate receipt -> fill tier+channel -> emit telemetry"
  - "T-2-09 server-side enforcement: D-11 destructive verbs forced to SINGLE_CHANNEL even when caller passes RACE"
  - "T-2-08 race-cancel correctness via tg.cancel_scope.cancel() + CancelScope(shield=False) propagation"
  - "D-15 AS stagger via _staggered_fire helper (500ms default; 0ms when as_class='fast')"
  - "race_winner / race_loser NDJSON events emitted to SessionWriter.append_action_log"
affects: [02-11 MCP healing tools surface, 03-recovery branches, 04-cognition speculation]

tech-stack:
  added: []
  patterns:
    - "anyio.create_task_group + tg.cancel_scope.cancel() as FIRST_COMPLETED equivalent (D-13)"
    - "Token claim ownership stays with WINNING channel; orchestrator never pre-claims (D-17)"
    - "Subscribe-before-fire + HoarePre-before-fan-out invariants preserved across race fan-out"
    - "Server-side override: caller-supplied policy is gated through resolve_race_policy BEFORE channel construction"

key-files:
  created:
    - "cua_overlay/actions/race_orchestrator.py - RaceOrchestrator + race_first_complete + NoTargetResolvable"
  modified:
    - "cua_overlay/actions/__init__.py - re-exports RaceOrchestrator, race_first_complete, NoTargetResolvable, AS_STAGGER_MS_DEFAULT"
    - "tests/integration/test_race_orchestrator.py - replaced Wave-0 stub with 11 integration tests"

key-decisions:
  - "race_first_complete uses tg.cancel_scope.cancel() not asyncio.wait(FIRST_COMPLETED) - anyio task group is the only way to get clean cancel propagation per RESEARCH Pattern 2"
  - "Loser placeholder ChannelOutcome uses channel='C1' sentinel; _log_race resolves the real channel from candidate index when status='cancelled' so race_loser events report the correct channel"
  - "axmgr.expect is wrapped in try/except to make orchestrator robust when AX subscription fails (e.g., target.ax_element is None or AX unavailable for this app); verifier degrades to L1 cheap diff per Phase 1 escalation ladder"
  - "_staggered_fire wraps the C4 channel coro in single-channel mode too; D-15 stagger applies whether C4 races or runs solo (only when as_class != 'fast')"
  - "Single-channel path picks first channel from registry.select(priority, SINGLE_CHANNEL); registry's select() already collapses to first channel under SINGLE_CHANNEL policy"

patterns-established:
  - "Pattern: async race_first_complete(coros, on_first_winner=callback) -> (winner_idx, outcome, all_results) — first ChannelOutcome with status='fired' wins; losers get tg.cancel_scope.cancel()"
  - "Pattern: orchestrator passes ONE shared anyio.Event(cancel_event) to all channel.fire calls; on_first_winner callback flips cancel_event.set() so D-18 OS-level kill-switch can short-circuit pre-syscall"
  - "Pattern: ActionCanonical.tier and .channel are filled AFTER race resolves via action.model_copy(update={'tier': ..., 'channel': ...}) - frozen Pydantic compatible"

requirements-completed:
  - ACT-02
  - ACT-04

duration: 4min 33s
completed: 2026-04-30
---

# Phase 02 Plan 10: RaceOrchestrator + race_first_complete + Pre/Post Hoare Wiring Summary

**RaceOrchestrator wires translators + channels + Phase 1 verifier + idempotency + race policy into a 12-step execute contract; anyio race_first_complete provides FIRST_COMPLETED via tg.cancel_scope.cancel(); 11 integration tests pass.**

## Performance

- **Duration:** 4 min 33 sec
- **Started:** 2026-04-30T15:37:37Z
- **Completed:** 2026-04-30T15:42:10Z
- **Tasks:** 2 (TDD: RED test commit + GREEN implementation commit)
- **Files modified:** 2 (race_orchestrator.py created, __init__.py extended, test_race_orchestrator.py replaced)

## Accomplishments

- **race_first_complete wrapper (D-13)** — anyio 4.13 has no built-in FIRST_COMPLETED. Custom wrapper spawns N coros in a task group, records results in a shared list, and on first ChannelOutcome(status='fired') invokes `on_first_winner` callback then calls `tg.cancel_scope.cancel()` to terminate losers. Returns `(winner_idx, winner_outcome, all_results)` with `winner_idx=-1` when no channel succeeds.
- **RaceOrchestrator.execute 12-step contract** — policy gate -> classify -> resolve target via translators in priority order -> build ActionCanonical -> subscribe AX (subscribe-before-fire) -> capture L1 HoarePre -> pick channels via D-14 default mapping -> apply D-15 AS stagger -> race or single-channel fan-out -> Phase 1 Aggregator.verify -> record DuplicateReceipt 2s ring buffer -> fill action.tier+.channel from winner -> emit race_winner/race_loser events.
- **T-2-09 server-side enforcement** — `resolve_race_policy(policy, action_type)` is called BEFORE any channel coros are constructed. D-11 destructive verbs (submit, send, delete, set_value, type, etc.) are downgraded to SINGLE_CHANNEL even when caller passes RACE. `race_policy.destructive_override_blocked` warning event surfaces the rejection.
- **T-2-08 race-cancel correctness** — orchestrator passes a shared `anyio.Event(cancel_event)` to all `channel.fire` calls. `on_first_winner` callback flips `cancel_event.set()` immediately, then `race_first_complete` calls `tg.cancel_scope.cancel()` so loser coroutines see CancelledError and clean up. Channel bodies stay in default `CancelScope(shield=False)` per Pitfall A.
- **D-15 AppleScript stagger** — `_staggered_fire` helper wraps the C4 channel coro in `anyio.sleep(stagger_ms / 1000.0)` when `target.extras['as_class'] != 'fast'`. Default 500ms (`AS_STAGGER_MS_DEFAULT`); 0ms when AS verb is fast (e.g., `tell to activate`). Stagger pushes the uncancellable AppleEvent past most race windows.
- **D-19 duplicate-receipt** — orchestrator calls `self._duplicate.record(target.element.composite_key, action_type, time.monotonic_ns())` AFTER `aggregator.verify` completes. The 2s ring buffer detects near-miss duplicates from the ~50µs uncancellable C1/C3 syscall window.
- **ActionCanonical.tier + .channel filling** — Phase 1 left these `Optional[Literal[...]]`. After race resolves, orchestrator calls `action.model_copy(update={'tier': winning_tier, 'channel': winning_channel})` to fill them from the winner's `ChannelOutcome.channel` + registry's `tier_for_channel` reverse lookup.
- **race_winner / race_loser NDJSON events** — `_log_race` iterates all channel outcomes and writes one event per channel with `{event, action_id, channel, status, fired_at_ns, error, skipped_reason, verifier_confidence, verifier_verified}`. Cancelled losers get the real channel name resolved from the candidate index.

## Task Commits

1. **Task 1 (TDD): RED race orchestrator integration tests** - `8051a08` (test) — 11 failing tests for `race_first_complete` + `RaceOrchestrator.execute` covering policy gate, ordering invariants, AS stagger, race winner/loser events.
2. **Task 1 (TDD): GREEN RaceOrchestrator + race_first_complete (ACT-02)** - `6a18eda` (feat) — `cua_overlay/actions/race_orchestrator.py` (386 lines) plus `__init__.py` re-exports.

_Note: Per the plan, Task 1 (skeleton) and Task 2 (tests) are the same TDD cycle; the test file was the RED commit, the implementation was the GREEN commit._

## Files Created/Modified

- `cua_overlay/actions/race_orchestrator.py` — **created** — RaceOrchestrator class, race_first_complete wrapper, NoTargetResolvable exception, AS_STAGGER_MS_DEFAULT constant, _staggered_fire helper, _log_race telemetry emitter
- `cua_overlay/actions/__init__.py` — **modified** — added re-exports for `AS_STAGGER_MS_DEFAULT`, `NoTargetResolvable`, `RaceOrchestrator`, `race_first_complete`
- `tests/integration/test_race_orchestrator.py` — **replaced Wave-0 stub** — 11 tests: race_first_complete winner/no-winner, RACE/AUTO/destructive policy gate, subscribe-before-fire ordering, HoarePre before fire, verify after fire, action.tier/.channel filled from winner, duplicate receipt after verify, race_winner/race_loser events, AS stagger applied

## Decisions Made

- **race_first_complete uses tg.cancel_scope.cancel() not asyncio.wait(FIRST_COMPLETED)** — anyio task group is the only way to get clean cancel propagation across awaiting coroutines per RESEARCH Pattern 2 + Pitfall A. Plain `asyncio.wait` botches cancellation; loser tasks leak.
- **Loser placeholder ChannelOutcome uses channel='C1' sentinel** — `race_first_complete` doesn't know the real channel name from inside `_runner`. `_log_race` resolves the real channel from `candidate_channels[idx].name` when `status='cancelled'` so race_loser events report the correct channel.
- **axmgr.expect wrapped in try/except** — when target.ax_element is None or AX unavailable for the app (e.g., Electron renderer pre-CDP), AX subscription failure is non-fatal. Verifier ladder degrades to L1 cheap diff per Phase 1's L0+L1+L2+L3 escalation. Logged as `race.axmgr_expect_failed` debug event.
- **_staggered_fire applies in single-channel mode too** — D-15 stagger isn't conditional on race vs single. When C4 is the lone channel (e.g., AS-only verbs on Pages), the 500ms stagger still applies unless `as_class='fast'`. Caller can opt out via `extras={'as_class': 'fast'}`.
- **Single-channel path uses registry.select(priority, SINGLE_CHANNEL)** — ChannelRegistry already collapses to first channel under SINGLE_CHANNEL policy (Plan 02-04). Orchestrator just awaits `coros[0]` directly without the race wrapper.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's interface block listed HoarePost.elapsed_ms but actual model has timestamp_ns + healed_to + target_key**
- **Found during:** Task 1 GREEN — `_fake_post()` in tests would have crashed with `pydantic.ValidationError`
- **Issue:** The plan's `<interfaces>` block (line 130-135) declared `HoarePost(verified, confidence, tier_signals, elapsed_ms)`. The real `cua_overlay/state/causal_dag.py:HoarePost` has `target_key, confidence, tier_signals, verified, healed_to, timestamp_ns` and a `model_validator` enforcing `verified == (confidence >= 0.5)`.
- **Fix:** Tests build `HoarePost(target_key, confidence, tier_signals, verified, healed_to, timestamp_ns)` with the actual schema. Race orchestrator removed `elapsed_ms` from the `_log_race` event payload (was not asserted by any test).
- **Files modified:** `tests/integration/test_race_orchestrator.py`, `cua_overlay/actions/race_orchestrator.py`
- **Verification:** All 11 tests pass; HoarePost validator does not raise.
- **Committed in:** `8051a08` + `6a18eda`

**2. [Rule 1 - Bug] Plan's example called axmgr.expect with `ax_element=` kwarg but Phase 1 signature uses positional `target` first**
- **Found during:** Task 1 GREEN — Phase 1's `AXObserverManager.expect` signature is `expect(target: UIElement, notifs, action_id, timeout_ms=500, ax_element=None)`. Plan had `expect(ax_element=target.ax_element, notifs=..., action_id=..., timeout_ms=100)` which omits the required `target` positional.
- **Issue:** Wrong call shape would TypeError at runtime.
- **Fix:** Orchestrator calls `self._axmgr.expect(target=target.element, notifs=notifs, action_id=action.id, timeout_ms=100, ax_element=target.ax_element)`.
- **Files modified:** `cua_overlay/actions/race_orchestrator.py`
- **Verification:** Test `test_subscribe_before_fire_ordering` calls expect successfully through the AsyncMock.
- **Committed in:** `6a18eda`

**3. [Rule 2 - Missing Critical] Orchestrator rejects empty channel list with NoTargetResolvable**
- **Found during:** Task 1 GREEN code review
- **Issue:** Plan didn't specify what happens when `registry.select(priority, effective)` returns `[]` (e.g., none of the priority tiers have registered channels yet during partial Wave 2 builds). Without a guard, `coros[0]` would raise IndexError.
- **Fix:** Added `if not candidate_channels: raise NoTargetResolvable(...)` after channel selection.
- **Files modified:** `cua_overlay/actions/race_orchestrator.py`
- **Verification:** Existing `NoTargetResolvable` exception class covers this; no new test required (orchestrator integration tests use registered mocks).
- **Committed in:** `6a18eda`

**4. [Rule 1 - Bug] Plan's race_first_complete used `with CancelScope(shield=False) as scope` but anyio task groups already provide the cancel scope**
- **Found during:** Task 1 GREEN
- **Issue:** RESEARCH Pattern 2 example wraps `_runner` body in `with CancelScope(shield=False)`, but anyio task groups create their own cancel scope by default (`shield=False`). Wrapping again is redundant and the inner `scope` variable was unused in the example.
- **Fix:** `_runner` uses the default task-group cancel scope (no explicit `with CancelScope(...)` block). `tg.cancel_scope.cancel()` propagates because the inner await on `coro` is in the default unshielded scope.
- **Files modified:** `cua_overlay/actions/race_orchestrator.py`
- **Verification:** `test_race_first_complete_winner_idx_zero_cancels_loser` confirms slow loser is cancelled.
- **Committed in:** `6a18eda`

**5. [Rule 1 - Bug] Doc comment containing literal `shield=True` failed plan's grep -c 0 acceptance criterion**
- **Found during:** Task 1 verification step
- **Issue:** Plan acceptance criterion: `grep -c 'shield=True' cua_overlay/actions/race_orchestrator.py` returns 0. My initial docstring said "Wrapping channel bodies in shield=True breaks race-cancel correctness" — that one literal substring tripped the grep.
- **Fix:** Rewrote the comment to "Wrapping channel bodies in a shielded scope breaks race-cancel correctness" — same meaning, no literal `shield=True`.
- **Files modified:** `cua_overlay/actions/race_orchestrator.py`
- **Verification:** `grep -c 'shield=True' cua_overlay/actions/race_orchestrator.py` returns 0.
- **Committed in:** `6a18eda`

---

**Total deviations:** 5 auto-fixed (3 bugs, 1 missing critical, 1 verification compliance)
**Impact on plan:** All deviations were essential for correctness — wrong HoarePost schema would have crashed tests immediately; wrong axmgr.expect call shape would have crashed at first real run; missing channel-list guard would have IndexError'd in production; redundant CancelScope was confusing dead code; literal `shield=True` violated the plan's own acceptance criterion. No scope creep.

## Issues Encountered

None — plan structure was correct, only the contract documentation in the plan's `<interfaces>` block diverged slightly from the real Phase 1 modules. Resolved by reading the actual modules (`cua_overlay/state/causal_dag.py`, `cua_overlay/verifier/axobserver.py`) and adapting the implementation to the real signatures.

## Next Phase Readiness

- **Plan 02-11 (MCP healing tools)** can now route every healing tool through `RaceOrchestrator.execute(...)`. The 6 new MCP tools (`click_with_healing`, `type_with_healing`, `scroll_with_healing`, `set_value_with_healing`, `send_destructive`, `key_combo_with_healing` per D-29) all call this same entry point.
- **Plan 02-12 (real-app integration tests)** has the full racing pipeline available end-to-end: D-25 Slack T2 wins, D-26 Pages T3 wins, D-27 Chess T4+T5 fires.
- **Phase 3 recovery branches** can wrap orchestrator calls in 5-branch parallel recovery; failure classifier consumes `race_winner` / `race_loser` events for diagnosis.
- **No blockers** — Phase 2 Wave 3 is one plan from complete (02-11 MCP surface, 02-12 e2e tests).

## Self-Check: PASSED

Verification:
- `cua_overlay/actions/race_orchestrator.py` exists (386 lines)
- `cua_overlay/actions/__init__.py` re-exports `RaceOrchestrator`, `race_first_complete`, `NoTargetResolvable`, `AS_STAGGER_MS_DEFAULT`
- Commit `8051a08` (RED test) present in git log
- Commit `6a18eda` (GREEN feat) present in git log
- All 11 integration tests pass: `uv run pytest tests/integration/test_race_orchestrator.py -m integration -q` -> `11 passed`
- Acceptance criteria all met (class RaceOrchestrator: 1, race_first_complete: 1, tg.cancel_scope.cancel: 3, resolve_race_policy: 3, axmgr.expect: 2, l1.snapshot: 1, agg.verify: 1, duplicate.record: 1, AS_STAGGER_MS_DEFAULT=500: 1, shield=True: 0)

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
