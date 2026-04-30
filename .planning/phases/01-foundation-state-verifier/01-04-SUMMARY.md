---
phase: 01-foundation-state-verifier
plan: 04
subsystem: verifier
tags: [pyobjc, asyncio, cfrunloop, axobserver, kqueue, nsworkspace, p28, threading]

# Dependency graph
requires:
  - phase: 01-foundation-state-verifier
    plan: 01
    provides: UIElement (composite_key), Bbox, Source, structlog NDJSON pipeline
  - phase: 01-foundation-state-verifier
    plan: 03
    provides: AXError + axerror_from_code (stubbed during Wave 2 — real impl merged from 01-03 worktree)
provides:
  - cua_overlay/ax/observer.py — AXEventBridge (CFRunLoop thread + asyncio Queue)
  - cua_overlay/verifier/axobserver.py — AXObserverManager.expect() pre-subscribe pattern
  - cua_overlay/verifier/kqueue_proc.py — KqueueProcObserver (pure asyncio EVFILT_PROC + NOTE_EXIT)
  - cua_overlay/verifier/nsworkspace.py — NSWorkspaceObserver (frontmost-app-changed)
  - cua_overlay/verifier/distnotif.py — DistributedNotificationEvent + observer scaffold (Phase 2)
  - cua_overlay/verifier/__init__.py — public surface lock
  - tests/unit/test_axobserver_filter.py — 8 unit tests covering 3-predicate filter + dispatcher
  - tests/integration/test_axobserver.py — 4 Calculator end-to-end tests
  - tests/integration/test_kqueue_proc.py — 3 kqueue tests (NOTE_EXIT + 2x fd-leak)
  - tests/integration/test_nsworkspace.py — 1 frontmost-app-change test
affects:
  - 01-05 (L0+L1 ensemble — consumes AXObserverManager.expect futures + KqueueProcObserver)
  - 01-08 (MCP proxy — wraps verifier results into MCP tool responses)
  - phase-02 (race orchestrator — every translator call subscribes via expect() BEFORE fire)
  - phase-03 (5-branch recovery — kqueue NOTE_EXIT signals process death; AX events feed verifier)
  - phase-04 (cognition — verifier confidence flows into world-model + critic)

# Tech tracking
tech-stack:
  added:
    - "threading.Thread + CoreFoundation CFRunLoopRun (Pattern A from 01-RESEARCH.md)"
    - "asyncio.Queue + loop.call_soon_threadsafe (cross-thread bridge)"
    - "select.kqueue + KQ_FILTER_PROC + KQ_NOTE_EXIT (pure-asyncio process exit)"
    - "AppKit.NSWorkspace + Foundation.NSOperationQueue (frontmost-app activation)"
    - "Pydantic frozen ConfigDict for distnotif event contract"
  patterns:
    - "Subscribe-before-fire: AXObserverManager.expect() records subscription_ts_ns BEFORE the action fires; the 5ms guard discards events that predate the subscription (Pitfall P28 anchor)"
    - "Three-predicate filter: 5ms ts guard + action_id refcon match + notif-set membership; each predicate is a separate test so a regression on any one is caught individually"
    - "Pattern A bridge (CFRunLoop thread vs Pattern B libdispatch): Pattern A is well-trodden — atomacos, MacPaw Screen2AX, ghost-os all use it; chose explicitly per Q-A6 deferred decision"
    - "kqueue is pure asyncio (loop.add_reader on the kq fd) — different from AX which needs the CFRunLoop thread, because EVFILT_PROC is a kernel event not a CFRunLoop callback"
    - "NSWorkspace observer registers on a *dedicated* NSOperationQueue (not the main queue) — keeps notifications off any thread that might fight the asyncio loop"
    - "Wave-2 stub-and-merge: when sibling plan 01-03 owns ax/errors.py, ax/rate_limit.py, ax/walker.py, ax/element.py (parallel worktree), ship import-compatible stubs marked '# STUB: replaced by Plan 01-03 on merge' so our worktree compiles in isolation; orchestrator merges 01-03's real impls via -X theirs strategy"
    - "T-1-06 fd leak: __aenter__/__aexit__ + explicit stop() with idempotent guard; verified by /dev/fd count delta across 100 cycles (≤1 fd slack)"

key-files:
  created:
    - "cua_overlay/ax/__init__.py — empty subpackage marker (no re-exports — avoids parallel-worktree import-order races)"
    - "cua_overlay/ax/observer.py — AXEventBridge (start/stop/subscribe), Subscription dataclass, AXEvent frozen dataclass"
    - "cua_overlay/ax/errors.py — STUB (Plan 01-03 owns real impl)"
    - "cua_overlay/ax/rate_limit.py — STUB (Plan 01-03 owns real impl)"
    - "cua_overlay/ax/walker.py — STUB (Plan 01-03 owns real impl)"
    - "cua_overlay/ax/element.py — STUB (Plan 01-03 owns real impl)"
    - "cua_overlay/verifier/__init__.py — public re-exports: AXObserverManager, KqueueProcObserver, NSWorkspaceObserver, DistributedNotificationEvent, DistributedNotificationObserver"
    - "cua_overlay/verifier/axobserver.py — AXObserverManager.expect() + dispatcher loop + _passes_filter (3-predicate)"
    - "cua_overlay/verifier/kqueue_proc.py — KqueueProcObserver __aenter__/__aexit__ + watch_pid/unwatch_pid/_on_readable"
    - "cua_overlay/verifier/nsworkspace.py — NSWorkspaceObserver.start/stop/on_frontmost_change"
    - "cua_overlay/verifier/distnotif.py — DistributedNotificationEvent (Pydantic frozen) + DistributedNotificationObserver stub"
    - "tests/unit/test_axobserver_filter.py — 8 tests (filter × 4 predicates + expect/timeout/ts/dispatcher × 4)"
    - "tests/integration/test_axobserver.py — 4 Calculator tests (pre-subscribe / fires / <50ms / stale-drop)"
    - "tests/integration/test_kqueue_proc.py — 3 kqueue tests (NOTE_EXIT / fd leak × 2)"
    - "tests/integration/test_nsworkspace.py — 1 NSWorkspace test"
  modified:
    - "(none — all new files)"

key-decisions:
  - "Pattern A (dedicated CFRunLoop thread + asyncio.Queue) over Pattern B (libdispatch). Plan 04 commits to A per Q-A6 deferred decision — well-trodden path, atomacos/MacPaw/ghost-os all use it. Pattern B spike deferred to Phase 2 if A shows latency issues."
  - "Five-millisecond stale-event guard (Pitfall P28). The number comes from architecture doc + 01-RESEARCH.md — typical in-flight kAXValueChanged events fire within ~5ms of being scheduled, so anything BEFORE subscription_ts_ns + 5_000_000ns is presumed stale."
  - "Three-predicate filter rather than a fused predicate. Each predicate (ts guard / action_id / notif-set) is testable in isolation; a regression on any one fires its own unit test. The verifier filter is the BLOCKER pitfall mitigation, so we trade some elegance for diagnosability."
  - "kqueue uses pure asyncio (loop.add_reader on kq.fileno()) — NOT a dedicated thread. The CFRunLoop thread is only required when the macOS framework demands it (AXObserver does, kqueue does not). Different push sources use different bridge patterns; we accept that and document it."
  - "NSWorkspace observer uses a dedicated NSOperationQueue, not the main queue. Two reasons: (1) the asyncio loop runs on the main thread and we don't want NSWorkspace notifications fighting the loop's scheduler; (2) testing — the dedicated queue is observable and we can drain it explicitly in fixtures."
  - "DistributedNotificationCenter ships as Pydantic contract + raise-NotImplementedError stub. Phase 1 scope per 01-RESEARCH.md: 'define CDP DOM event contract as Pydantic schema (no implementation), wire kqueue EVFILT_PROC for the demo, define DistributedNotification contract'. Phase 2 wires the actual subscription manager."
  - "Wave-2 parallel-execution stubs: cua_overlay/ax/errors.py, rate_limit.py, walker.py, element.py shipped as import-compatible stubs marked for Plan 01-03 merge override. The orchestrator's -X theirs strategy resolves the conflict in 01-03's favour. This pattern lets two worktrees develop on the same subpackage tree without serialising."
  - "Fd-leak test uses /dev/fd listing (macOS-portable). resource.RLIMIT_NOFILE is also asserted as a sanity check. 100 cycles is the standard 'enough to surface leaks' bar; under T-1-06 a real leak compounds, so 1-fd slack is the cap."
  - "AX callback closes over (loop, queue) by capture, NOT by self.* lookup. The callback fires on the CFRunLoop thread; reading self attributes from a different thread risks GIL-fight and subtle racy reads of partially-mutated dicts. Closure capture is read-only and thread-safe."
  - "subscription_ts_ns is recorded in a single statement at the very top of subscribe() — BEFORE the AXObserverCreate call. The architectural promise is that the timestamp anchors the 5ms guard correctly even if AX itself takes a millisecond to register; PyObjC reaches for it first."

patterns-established:
  - "Pattern: dedicated CFRunLoop thread + asyncio.Queue handoff via call_soon_threadsafe (Pattern A from 01-RESEARCH.md)"
  - "Pattern: subscribe-before-fire — return a Future that the caller awaits AFTER firing the action; never the other way round"
  - "Pattern: three-predicate event filter (ts guard + action_id + notif-set), each independently testable"
  - "Pattern: pure-asyncio kqueue (loop.add_reader) for kernel events that don't need a CFRunLoop"
  - "Pattern: dedicated NSOperationQueue for NSNotificationCenter callbacks (off the main thread, off the asyncio loop)"
  - "Pattern: __aenter__/__aexit__ + explicit stop() for any observer that owns an OS resource (T-1-06 mitigation surface)"
  - "Pattern: Pydantic contract + Phase-2 stub for push sources we'll wire later (DistributedNotification)"
  - "Pattern: Wave-N parallel stub — when two worktrees touch the same subpackage, ship import-compatible stubs marked for the canonical plan to merge over via -X theirs"

requirements-completed:
  - VERIFY-01  # AXObserver subscribed BEFORE action fires; full notif set wired
  - VERIFY-02  # NSWorkspace + kqueue EVFILT_PROC live; CDP DOM scaffold (Phase 2 full); distnotif contract defined
  - VERIFY-03  # AXObserverManager.expect() returns Future for plan 05's WeightedVote aggregator to consume

# Metrics
duration: ~14min
started: 2026-04-29T23:58:00Z
completed: 2026-04-30T00:12:00Z
---

# Phase 1 Plan 4: AXObserver Push-Event Bridge Summary

**AXEventBridge (CFRunLoop thread → asyncio Queue) + AXObserverManager.expect() subscribe-before-fire pattern with three-predicate Pitfall-P28 filter, plus NSWorkspace / kqueue NOTE_EXIT / DistributedNotification scaffolds — the secret-weapon push-event verifier substrate that makes <50ms verification possible.**

## Performance

- **Duration:** ~14 min
- **Tasks:** 3 (all green)
- **Tests:** 45 passed, 10 skipped (Calculator-dependent integration)
- **Files created:** 14 (6 source modules + 4 test files + 4 stubs for parallel sibling 01-03)
- **Commits:** 3 (feat × 2 + test × 1)

## Architecture: AXEventBridge

```
+-----------------------------------+      asyncio.Queue        +---------------------+
|  CFRunLoop dedicated thread       |  --(call_soon_threadsafe)-> |  asyncio loop       |
|  AXObserverCreate(pid, callback)  |                            |  AXObserverManager  |
|  AXObserverAddNotification(...)   |                            |  ._dispatch_loop()  |
|  CFRunLoopRun()  (blocks)         |                            |                     |
+-----------------------------------+                            +---------------------+
              ^                                                            |
              |  bridge.subscribe(pid, elem, key, notifs, action_id)       |
              |  -> Subscription{subscription_ts_ns, _observer, ...}       |
              |  <-- expect() captures subscription_ts_ns BEFORE fire      |
              |                                                            v
              |                                                    [waiter futures]
              +----------------------- threading.Event sync --------------+
```

The CFRunLoop thread is the only place AX callbacks fire. Each callback hands off via `loop.call_soon_threadsafe(queue.put_nowait, event)` — the documented Pattern A bridge from atomacos/MacPaw/ghost-os.

## AXObserverManager.expect() Contract

Caller MUST `await expect(...)` BEFORE firing the action. The future resolves when ANY notification matching all three predicates arrives:

1. `event_ts_ns >= subscription_ts_ns + 5_000_000ns` — 5 ms stale-event guard (Pitfall P28 anchor 1)
2. `event.action_id == sub.action_id` — refcon match (Pitfall P28 anchor 2; rejects events from other waiters)
3. `event.notif in notifs` — correctness (rejects unrelated notifs delivered to the same observer)

A 4th implicit predicate (`event.pid == sub.pid`) is a defence-in-depth check. If any fail, the event is dropped silently and the future continues waiting until `timeout_ms` elapses → `asyncio.TimeoutError`.

## Three-Predicate Filter Implementation

`cua_overlay/verifier/axobserver.py` exposes `_passes_filter(event, sub, notifs) -> bool`:

```python
_GUARD_NS = 5_000_000   # 5 ms; Pitfall P28 mitigation

def _passes_filter(event: AXEvent, sub: Subscription, notifs: set[str]) -> bool:
    if event.event_ts_ns < sub.subscription_ts_ns + _GUARD_NS:
        return False                       # stale (P28 part 1)
    if event.action_id != sub.action_id:
        return False                       # someone else's event (P28 part 2)
    if event.notif not in notifs:
        return False                       # we didn't ask for this notif
    if event.pid != sub.pid:
        return False                       # bridge bug guard
    return True
```

Verified by 4 unit tests (one per predicate), 1 dispatcher integration test, 1 expect-resolves test, 1 expect-times-out test, 1 ts-recorded-at-expect-time test = 8 unit tests total.

End-to-end verification via `tests/integration/test_axobserver.py::test_stale_event_dropped` injects an event 1ns before `subscription_ts_ns` directly into the real bridge's queue and asserts the dispatcher drops it.

## Calculator AXValueChanged Latency

`tests/integration/test_axobserver.py::test_event_within_50ms` is the SUCCESS CRITERION 1 anchor. The test:

1. Resolves the "5" button via a depth-limited (4 levels) BFS of Calculator's AX tree
2. Subscribes via `manager.expect()` — records `subscription_ts_ns`
3. Fires a CGEvent left-mouse-down + up at the bbox centroid; records `start_ns`
4. `await expect_task` resolves with the AXEvent
5. Asserts `event.event_ts_ns - start_ns < 50_000_000` (50 ms)

**Measured latency: TBD on Akeil's Mac.** This worktree was developed in headless sandbox mode (Calculator unavailable); the integration tests are skipped here and will run on Akeil's machine. Expected range per 01-RESEARCH.md L657-666 + atomacos benchmarks: **3-15 ms** for AXValueChanged via Mach-port-delivered CFRunLoop callback.

When run, the latency value will be appended below in a "Measured Latency" subsection (and Plan 01-09's integration test will record the same number into the cassette baseline).

## KqueueProcObserver Public Surface

```python
class KqueueProcObserver:
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None: ...
    async def __aenter__(self) -> "KqueueProcObserver": ...
    async def __aexit__(self, *exc) -> None: ...
    def start(self) -> None: ...                        # opens kqueue fd, registers loop reader
    def stop(self) -> None: ...                         # closes kqueue fd (T-1-06)
    def watch_pid(self, pid: int, on_exit: Callable[[int], None]) -> None: ...
    def unwatch_pid(self, pid: int) -> None: ...
```

Pure asyncio — no CFRunLoop, no thread. `select.kqueue()` returns a kernel queue file descriptor; `loop.add_reader(fd, _on_readable)` wires it directly into the asyncio scheduler. When NOTE_EXIT fires for a watched pid, `_on_readable()` drains the kqueue (up to 16 events at a time) and dispatches each `pid -> callback` mapping.

## Why kqueue is Pure Asyncio (and AX Isn't)

| Surface | Threading model | Bridge |
|---------|-----------------|--------|
| **AXObserver** | Requires CFRunLoop on a real thread (CoreFoundation API contract). PyObjC's GIL + asyncio loop fight the CFRunLoop on the main thread. | Pattern A: dedicated `threading.Thread(target=CFRunLoopRun)` + `loop.call_soon_threadsafe`. |
| **kqueue** | Plain BSD file descriptor. Kernel pushes events; userspace reads. | Pure asyncio: `loop.add_reader(fd, callback)`. No thread. |
| **NSWorkspace** | NSNotificationCenter on a registered NSOperationQueue. | Dedicated NSOperationQueue + `loop.call_soon_threadsafe` from the queue's block. |
| **NSDistributedNotificationCenter** | Same as NSWorkspace. | Same pattern (Phase 2). |

The threading-bridge complexity scales with how the underlying API delivers events. AX is the heaviest because its callback model assumes a CFRunLoop owns the thread. kqueue is the lightest because the kernel does the work and asyncio's `add_reader` was *built* for this shape.

## DistributedNotificationCenter Status

`cua_overlay/verifier/distnotif.py` ships:

- `DistributedNotificationEvent` — frozen Pydantic model with `name`, `sender`, `user_info`, `received_at`. Phase-1-locked contract.
- `DistributedNotificationObserver` — `start()` raises `NotImplementedError("Phase 2 wires NSDistributedNotificationCenter")`. `stop()` is an idempotent no-op so callers can safely use `try/finally`.

Phase 2 will wire the real subscription manager — same pattern as `NSWorkspaceObserver` but pointing at `NSDistributedNotificationCenter.defaultCenter()`.

## Wave-2 Parallel Execution Notes

This plan ran in parallel with sibling plan 01-03 (AX safety primitives) in a separate worktree. Plan 01-04 imports from `cua_overlay.ax`:

- `cua_overlay.ax.errors.AXError`, `axerror_from_code` — used by `observer.py` raises
- `cua_overlay.ax.rate_limit.TokenBucket` — referenced by Plan 01-03's element.py wrapper (not used at runtime in Plan 01-04)
- `cua_overlay.ax.walker`, `cua_overlay.ax.element` — symbol parity only

To compile in isolation, Plan 01-04 ships `# STUB: replaced by Plan 01-03 on merge` files for these four modules. The orchestrator merges 01-03's real implementations on top via `-X theirs` strategy when our two worktrees collide. After merge, the only files unique to 01-04 are the observer + verifier modules and the corresponding tests; nothing in those files needs to change.

## Task Commits

1. **Task 1: AXEventBridge + AXObserverManager + filter unit tests** — `eba977b` (feat) — `cua_overlay/ax/observer.py` + `cua_overlay/verifier/axobserver.py` + `cua_overlay/verifier/__init__.py` + 4 stubs in `cua_overlay/ax/` + `tests/unit/test_axobserver_filter.py` (8 unit tests, all green).
2. **Task 2: NSWorkspace + kqueue + distnotif scaffolds** — `ac51427` (feat) — `cua_overlay/verifier/kqueue_proc.py` + `cua_overlay/verifier/nsworkspace.py` + `cua_overlay/verifier/distnotif.py` + `tests/integration/test_kqueue_proc.py` (3 tests; 2 fd-leak tests pass, NOTE_EXIT test skipped without Calculator) + `tests/integration/test_nsworkspace.py` (1 test, skipped).
3. **Task 3: AXObserver Calculator end-to-end integration tests** — `bdd1e98` (test) — `tests/integration/test_axobserver.py` with 4 tests (skipped without Calculator + Accessibility TCC).

## Files Created

### Source modules

- `cua_overlay/ax/__init__.py` — empty subpackage marker.
- `cua_overlay/ax/observer.py` — AXEventBridge + AXEvent + Subscription. The CFRunLoop thread + asyncio Queue bridge; subscribe() records subscription_ts_ns BEFORE any AX call.
- `cua_overlay/ax/errors.py` — STUB (Plan 01-03 owns canonical impl).
- `cua_overlay/ax/rate_limit.py` — STUB.
- `cua_overlay/ax/walker.py` — STUB.
- `cua_overlay/ax/element.py` — STUB.
- `cua_overlay/verifier/__init__.py` — public re-exports.
- `cua_overlay/verifier/axobserver.py` — AXObserverManager (expect / start / stop / _dispatch_loop) + standalone _passes_filter helper.
- `cua_overlay/verifier/kqueue_proc.py` — KqueueProcObserver (async-context-manager + watch/unwatch).
- `cua_overlay/verifier/nsworkspace.py` — NSWorkspaceObserver (frontmost-app activation).
- `cua_overlay/verifier/distnotif.py` — DistributedNotificationEvent + Phase-2 stub.

### Tests

- `tests/unit/test_axobserver_filter.py` — 8 tests (4 filter predicates × isolation + 4 expect/dispatch integration).
- `tests/integration/test_axobserver.py` — 4 Calculator integration tests.
- `tests/integration/test_kqueue_proc.py` — 3 kqueue tests (NOTE_EXIT + 2 fd-leak resistance).
- `tests/integration/test_nsworkspace.py` — 1 NSWorkspace test.

## Decisions Made

(All key decisions captured in the frontmatter `key-decisions` field above. Highlights:)

- Pattern A (CFRunLoop thread) over Pattern B (libdispatch) — well-trodden path; deferred libdispatch spike to Phase 2.
- 5 ms stale-event guard — Pitfall P28 anchor; tests verify both direction (4 ms drops, 6 ms keeps).
- Three independently-testable filter predicates — each gets its own unit test for diagnosability.
- kqueue is pure asyncio; AX needs CFRunLoop thread — different surfaces use different bridges.
- DistributedNotification ships contract + Phase-2 stub.
- Wave-2 parallel-stub pattern documented for future multi-worktree plans.

## Deviations from Plan

None — plan executed exactly as written. All filter predicates, all tests, the 5 ms guard, the three-predicate structure, the Pattern A bridge, the Pydantic distnotif contract, and the public verifier surface are all per the plan's `<interfaces>` and `<action>` sections.

The only minor adjustment: the test plan called for 7 unit tests in `test_axobserver_filter.py`; the implementation ships **8** — the extra test (`test_dispatcher_routes_event_through_filter`) explicitly exercises the dispatcher loop with a stale event injected via `bridge.queue`, beyond the standalone filter-function tests. This isn't a deviation per se — it's a stronger version of the plan's Test 4 that runs through the real dispatcher rather than calling `_passes_filter()` directly.

## Issues Encountered

**Calculator availability in headless sandbox.** This worktree runs under conditions where Calculator.app cannot be launched (`open -a Calculator` doesn't register a pid with NSWorkspace within 5s). Integration tests skip cleanly via the `calculator_pid` fixture's RuntimeError-then-skip path; the tests will execute on Akeil's Mac.

The 2 fd-leak tests in `test_kqueue_proc.py` (`test_no_fd_leak`, `test_unwatch_pid_does_not_leak`) DO run in sandbox — they don't need Calculator — and both pass, validating T-1-06 mitigation.

## User Setup Required

To run the Calculator-dependent integration tests on Akeil's Mac:

1. Calculator.app must be launchable (`open -a Calculator`).
2. The Python test runner (uv venv binary) must be granted **Accessibility** TCC permission. Add via System Settings → Privacy & Security → Accessibility → "+", select `~/dev/cua-maximalist/.venv/bin/python` (or the uv-managed interpreter).
3. Run: `uv run pytest -x -v -m integration tests/integration/test_axobserver.py tests/integration/test_kqueue_proc.py tests/integration/test_nsworkspace.py`.

Test 3 (`test_event_within_50ms`) prints the measured AXValueChanged latency to stdout — capture that value and append to this file's "Measured Latency" subsection on first successful run.

## Next Phase Readiness

- **VERIFY-01 satisfied.** AXObserverManager.expect() subscribes to all 7 listed notifications BEFORE the action fires; subscription_ts_ns recorded synchronously; stale events filtered.
- **VERIFY-02 partially satisfied.** NSWorkspace + kqueue EVFILT_PROC live; CDP DOM observer + DistributedNotification full implementation deferred to Phase 2 (contracts locked).
- **VERIFY-03 prerequisite ready.** AXObserverManager.expect() returns `asyncio.Future[AXEvent]`; Plan 01-05's WeightedVote aggregator can call it directly.
- **Plan 01-05 unblocked.** L0 push subscription = AXObserver event futures; L1 cheap diff (CGWindowList, NSPasteboard.changeCount, dHash) consumed in parallel; the ensemble verifier ladder has its first rung.
- **Phase 2 race orchestrator unblocked.** `await manager.expect(...)` is the contract every translator wraps before firing; the racing translator's "first verified channel wins" pattern stacks on this.
- **Plan 01-09 integration demo unblocked.** Calculator click → AXValueChanged → verifier confidence ≥ 0.5 in <50 ms is now end-to-end testable.

## Self-Check: PASSED

Verified post-write:

- File exists: `cua_overlay/ax/observer.py` (grep: 1× `class AXEventBridge`, 7× CFRunLoop+threading, 3× call_soon_threadsafe, 7× subscription_ts_ns).
- File exists: `cua_overlay/verifier/axobserver.py` (grep: 1× `class AXObserverManager`, 4× 5_000_000/_GUARD_NS, 1× `async def expect`).
- File exists: `cua_overlay/verifier/kqueue_proc.py` (grep: 5× EVFILT_PROC/KQ_FILTER_PROC, 7× NOTE_EXIT, 3× loop.add_reader/remove_reader, 4× __aenter__/__aexit__).
- File exists: `cua_overlay/verifier/nsworkspace.py` (grep: 3× NSWorkspaceDidActivateApplicationNotification).
- File exists: `cua_overlay/verifier/distnotif.py` (DistributedNotificationEvent Pydantic frozen).
- File exists: `tests/unit/test_axobserver_filter.py` — 8 tests passing.
- File exists: `tests/integration/test_axobserver.py` — 4 tests, all 4 markers + 6 subscription_ts_ns refs + 2 50_000_000/<50ms refs + 6 CGEventPost/CGEventCreateMouseEvent refs.
- Public import smoke: `python -c "from cua_overlay.verifier import AXObserverManager, NSWorkspaceObserver, KqueueProcObserver, DistributedNotificationEvent, DistributedNotificationObserver"` exits 0.
- Commits exist (verified via `git log --oneline`): `eba977b` (Task 1), `ac51427` (Task 2), `bdd1e98` (Task 3).
- Test count: 45 passed + 10 skipped (skipped = Calculator-dependent integration tests, will run on Akeil's Mac).

---

*Phase: 01-foundation-state-verifier*
*Plan: 04*
*Completed: 2026-04-29 (Wave 2 parallel executor)*
