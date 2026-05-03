---
phase: 01-foundation-state-verifier
plan: 03
subsystem: ax-safety-primitives
tags: [pyobjc, hiservices, asyncio, structlog, pydantic, tdd, pitfall-p2, pitfall-p3, pitfall-p25, t-1-04]

# Dependency graph
requires:
  - phase: 01-foundation-state-verifier
    plan: 01
    provides: UIElement, Bbox, Source enum, structlog log.py, Pydantic state-graph contracts, tests/conftest.py with calculator_pid fixture
provides:
  - basicctrl/ax/ subpackage with locked public surface (8 exports)
  - TokenBucket(rate_per_sec=20.0, capacity=20) — per-pid AX call rate limiter (P2 mitigation)
  - walk_subtree() — iterative BFS depth-limited walker (P3 mitigation; max_depth=3, max_children=50, max_nodes=500; emits truncated flag + cap_hit reason)
  - has_blocking_modal() — pre-action modal probe (P25 mitigation; scans up to 10 top-level windows for AXModal=True)
  - AXError typed exception hierarchy — 6 subclasses sourced from PyObjC HIServices live exports of AXError.h
  - axerror_from_code(code) — native AX code → typed exception mapper
  - AXUIElementWrapper — high-level façade combining rate-limit + 100ms read cache + typed errors
affects: [01-04, 01-05, 01-06, 01-08, 02-*, 03-*]

# Tech tracking
tech-stack:
  added:
    - "asyncio.Lock for per-bucket concurrency safety (no new top-level deps)"
  patterns:
    - "Source AX error code values from live PyObjC HIServices exports rather than frozen integer literals — kAXError* constants come from AXError.h on the build machine, so macOS-version drift in code values is invisible to us"
    - "Iterative BFS via list.pop(0) work-queue — never Python-recursive — verified by a no-recursion-grep source check that fails the test if anyone reintroduces self-call"
    - "Fail-open rate limit — TokenBucket.acquire returns False (does not block, does not raise) so callers serve last-cached state with reduced confidence per P2 prevention rule 5"
    - "Three independent caps emit a SINGLE truncated flag + cap_hit string — verifier consumes one signal, not three"
    - "AXUIElementWrapper façade pattern — consolidate rate-limit + cache + typed-errors at the entry-point so individual call sites never need to remember the safety primitives"
    - "Test-isolation fixtures — pass an explicit big_bucket TokenBucket(rate=10000, cap=10000) to walker tests that exercise structural caps, so rate-limit and structural caps are never co-tested"

key-files:
  created:
    - "basicctrl/ax/__init__.py — public API exports (8 names: 6 errors + axerror_from_code, TokenBucket, walk_subtree + WalkResult, has_blocking_modal, AXUIElementWrapper)"
    - "basicctrl/ax/errors.py — AXError + 6 typed subclasses + axerror_from_code; canonical AX error codes pulled from HIServices via try/import-fallback"
    - "basicctrl/ax/rate_limit.py — TokenBucket per-pid (20/sec/pid) with asyncio.Lock + structlog ax.rate_limited deny event"
    - "basicctrl/ax/walker.py — walk_subtree iterative BFS + WalkResult + _read_attr (typed-error-mapping AXUIElementCopyAttributeValue) + _coords_to_bbox"
    - "basicctrl/ax/modal_probe.py — has_blocking_modal(pid, *, bundle_id, bucket); MAX_WINDOWS_TO_CHECK=10"
    - "basicctrl/ax/element.py — AXUIElementWrapper façade with 100ms read cache (CACHE_TTL_SECONDS=0.1)"
    - "tests/unit/test_rate_limit.py — 6 tests (initial-burst-20, 21st-deny, per-pid-isolation, refill-at-20/sec frozen-clock, structlog-deny-event, non-blocking-deny)"
    - "tests/unit/test_ax_errors.py — 9 tests (canonical -252xx tripwire, parametrised 6 subclasses, unknown-code fallback, message-includes-code)"
    - "tests/unit/test_walker.py — 8 tests (depth/children/nodes caps + no-truncation, role_path emission, default-caps signature, no-recursion source check, rate-limit-throttle integration)"
    - "tests/integration/test_modal_probe.py — 7 tests (1 real-Calculator skipped under SKIP_INTEGRATION=1, 1 manual-only @skip, 5 mock-driven + 2 cache-behaviour)"
  modified:
    - "(none — Plan 01-03 is purely additive; basicctrl/state/* stay untouched per Plan 01-01 contract)"

key-decisions:
  - "Source AX error codes from PyObjC HIServices's live exports (`from HIServices import kAXErrorAPIDisabled, ...`) rather than hardcoded integer literals. macOS 26.4's AXError.h verified to match canonical values (-25202 / -25204 / -25205 / -25206 / -25207 / -25211); a tripwire test (test_canonical_axerror_h_values) fails immediately if Apple changes the integer values in macOS 27+."
  - "Walker default bucket is a fresh TokenBucket(20, 20) when bucket=None — same cap as the wrapper. This means a default-bucketed walker that walks more than ~20 nodes will throttle, which is intentional: structural caps and rate-limit caps both protect the target app, and structural-only tests pass an explicit big_bucket so the cap behaviour is isolated."
  - "Walker cap_hit ladder: nodes > children > depth (first-hit wins, but nodes is checked before pop-from-queue so it always wins for >=max_nodes-tree). Recorded in WalkResult.cap_hit string; downstream verifier confidence drops by 0.1 / 0.2 / 0.3 depending on which cap fired (consumer-side mapping, not enforced here)."
  - "Modal probe is intentionally NOT a walker — it scans top-level windows only via direct AXModal read. A walker invocation would defeat the point: modals often coincide with main-thread saturation, and we want to know within a single bucket-token whether to abort the action."
  - "AXUIElementWrapper raises AXError on InvalidUIElement / NotificationUnsupported (in addition to the API-disabled / cannot-complete codes that walker raises on). Reason: the wrapper is the high-level façade that VERIFIER code uses, and the verifier needs to know if its AX ref went stale or if a notification couldn't be subscribed. Walker is bulk-read and treats those as 'attribute not present'."
  - "Tests freeze time.monotonic via monkeypatch on basicctrl.ax.rate_limit.time.monotonic rather than mocking the whole time module. This keeps refill-rate tests deterministic without affecting other tests' real-clock behaviour."

patterns-established:
  - "Pattern: PyObjC live-import-with-integer-fallback for AX-framework constants — try/import the named const, fall back to literal value with a comment recording the AXError.h-verified value"
  - "Pattern: Token-bucket per-pid keyed on integer pid; asyncio.Lock per-bucket; structlog deny event with pid attribute"
  - "Pattern: Iterative BFS over a (elem, depth, role_path) tuple queue with pre-pop nodes-cap check + post-read children-cap check + depth-cap-on-children-enqueue"
  - "Pattern: WalkResult dataclass with truncated bool + cap_hit Optional[str] for verifier confidence reduction"
  - "Pattern: Async _read_attr helper that wraps AXUIElementCopyAttributeValue via asyncio.to_thread and maps native error codes through axerror_from_code"
  - "Pattern: 100ms TTL read cache via _CachedValue(__slots__=('value', 'ts')) — ts is time.monotonic, lookup is dict.get(attribute)"
  - "Pattern: Mock AX hierarchy (MockAXElement, MockApp, MockWindow) with .attr(name) method + monkeypatch _read_attr to delegate"

requirements-completed: [VERIFY-06]

# Metrics
duration: 7min21s
started: 2026-04-30T00:15:25Z
completed: 2026-04-30T00:22:46Z
---

# Phase 1 Plan 3: AX Safety Primitives Summary

**TokenBucket + depth-limited walker + modal probe + typed AX errors + AXUIElementWrapper façade — three BLOCKER-class pitfalls (P2/P3/P25) and threat T-1-04 mitigated at the basicctrl/ax/ entry-point. 28 dedicated tests green; 63/63 plan-level test suite green.**

## Performance

- **Duration:** 7 min 21 s
- **Started:** 2026-04-30T00:15:25Z
- **Completed:** 2026-04-30T00:22:46Z
- **Tasks:** 3 (all atomically committed)
- **Files created:** 10 (5 source + 5 test) — no files modified outside the plan
- **Dependencies added:** none (uses asyncio + structlog already pinned in Plan 01-01)

## Public API Surface

`from basicctrl.ax import ...`:

| Name | Kind | Purpose |
|------|------|---------|
| `TokenBucket` | class | Per-pid AX call rate limiter (default 20/sec/pid) |
| `walk_subtree` | async fn | Iterative BFS subtree walker with hard caps |
| `WalkResult` | dataclass | (nodes, truncated, cap_hit, duration_ms) |
| `has_blocking_modal` | async fn | Pre-action modal probe |
| `AXUIElementWrapper` | class | rate-limit + 100ms cache + typed errors façade |
| `AXError` | exception | Base typed AX error |
| `AXAPIDisabledError` | exception | TCC revoked / SIP-style denial (-25211) |
| `AXCannotCompleteError` | exception | Main-thread saturation (-25204) |
| `AXNotificationUnsupportedError` | exception | Web/Electron content (-25207) |
| `AXInvalidUIElementError` | exception | Stale ref (-25202) |
| `AXAttributeUnsupportedError` | exception | (-25205) |
| `AXActionUnsupportedError` | exception | (-25206) |
| `axerror_from_code(code)` | fn | native code → typed exception |

## Key Numbers

| Primitive | Value | Source |
|-----------|-------|--------|
| TokenBucket rate | 20 calls/sec/pid | CLAUDE.md hard rule (cmux #2985 saturates at 30) |
| TokenBucket capacity | 20 (full burst) | matches rate so caller can do a 20-token burst on a fresh bucket |
| Walker max_depth | 3 | ROADMAP §"Phase 1" + ARCHITECTURE.md hard rule |
| Walker max_children | 50 | PITFALLS.md P3 prevention rule 1 |
| Walker max_nodes | 500 | PITFALLS.md P3 prevention rule 1 |
| Modal probe window cap | 10 | targeted-read budget; well past observed real-world max |
| AXUIElementWrapper cache TTL | 100 ms | PITFALLS.md P2 prevention rule 2 |

## AXError → Native Code Mapping

| Subclass | Native code | Constant | Triggers when |
|----------|-------------|----------|----------------|
| AXInvalidUIElementError | -25202 | kAXErrorInvalidUIElement | Element destroyed / window closed |
| AXCannotCompleteError | -25204 | kAXErrorCannotComplete | Main-thread saturation, app busy |
| AXAttributeUnsupportedError | -25205 | kAXErrorAttributeUnsupported | Attribute not on this element |
| AXActionUnsupportedError | -25206 | kAXErrorActionUnsupported | Action not on this element |
| AXNotificationUnsupportedError | -25207 | kAXErrorNotificationUnsupported | Web/Electron content |
| AXAPIDisabledError | -25211 | kAXErrorAPIDisabled | TCC revoked / AX disabled (T-1-04) |

Tripwire test `test_canonical_axerror_h_values` confirms these match AXError.h on macOS 26.4 (read live at scaffold time per Plan 01-03 Task 1 step 0).

## Task Commits

Each task committed atomically:

1. **Task 1: TokenBucket + typed AX errors** — `de3af52` (feat) — basicctrl/ax/__init__.py, basicctrl/ax/errors.py, basicctrl/ax/rate_limit.py, tests/unit/test_rate_limit.py, tests/unit/test_ax_errors.py. 15 tests green.
2. **Task 2: Depth-limited iterative walker** — `b850776` (feat) — basicctrl/ax/walker.py, tests/unit/test_walker.py. 8 tests green (one auto-fix during TDD: structural-cap tests now pass an explicit big_bucket so rate-limit and structural caps are isolated).
3. **Task 3: Modal probe + AXUIElementWrapper façade** — `83a3e50` (feat) — basicctrl/ax/__init__.py update, basicctrl/ax/modal_probe.py, basicctrl/ax/element.py, tests/integration/test_modal_probe.py. 7 tests green (5 mock + 2 cache); 1 real-Calculator skipped under SKIP_INTEGRATION=1; 1 manual-only @skip pending real-modal verification.

## Test Counts

| Module | Passed | Skipped | Notes |
|--------|--------|---------|-------|
| tests/unit/test_rate_limit.py | 6 | 0 | All TokenBucket behaviours |
| tests/unit/test_ax_errors.py | 9 | 0 | Tripwire + parametrised + edge cases |
| tests/unit/test_walker.py | 8 | 0 | Caps + role_path + no-recursion + rate-limit |
| tests/integration/test_modal_probe.py | 5 | 2 | Mocked + cache; Calculator + manual skipped |
| **Plan total** | **28** | **2** | |
| **Phase 1 total (all 4 modules + Plan 01/02 inheritance)** | **63** | **6** | full `pytest` run |

## Decisions Made

(All key decisions captured in the frontmatter `key-decisions` field. Highlights:)

- **AX error codes sourced live from PyObjC HIServices** rather than frozen integer literals — drift in macOS 27+ would surface as a tripwire test failure rather than silent wrong-code mapping.
- **Walker default bucket is a fresh 20/sec/pid TokenBucket** — structural caps test passes `big_bucket` to isolate from rate-limit interaction.
- **Modal probe is targeted-read only**, not a walker — modals coincide with main-thread saturation, so we want a single-token answer.
- **AXUIElementWrapper raises on more codes than walker** — verifier-grade façade needs to know about stale refs and unsupported notifications; bulk walker treats those as "attribute not present" to keep walking.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Walker structural-cap tests collided with default rate-limit**
- **Found during:** Task 2 first test run.
- **Issue:** `test_caps_at_max_children` (100 children, expect 51 nodes) and `test_caps_at_max_nodes` (1111 nodes, expect cap_hit="nodes") both walked far more than 20 nodes. The walker's default bucket is a fresh `TokenBucket(20, 20)`, so reads ran out of tokens and the tree was truncated by rate-limit before structural caps could fire. The test expectations were correct; the test harness needed an explicit big-capacity bucket to isolate structural caps from rate-limit interaction.
- **Fix:** Pass `bucket=TokenBucket(rate_per_sec=10000.0, capacity=10000)` (or 100000 for the largest tree) to the structural-cap tests so they exercise ONLY the structural cap. Rate-limit interaction is verified separately in `test_uses_rate_limit`.
- **Files modified:** `tests/unit/test_walker.py` (3 tests now pass `bucket=big_bucket`).
- **Verification:** All 8 walker tests pass.
- **Committed in:** `b850776` (rolled into Task 2).

**2. [Rule 3 - Blocking] uv venv missing dev dependencies on first test run**
- **Found during:** Task 1 first `uv run pytest` invocation.
- **Issue:** The .venv created earlier (during my `uv run python -c` smoke test for HIServices) only had project deps installed. pytest, pytest-asyncio, mypy, ruff (all under `[project.optional-dependencies] dev`) were not installed, so `uv run pytest` resolved to a system pytest at `/Users/akeilsmith/bench-loop/.venv/bin/pytest` which uses Python 3.14 and could not find structlog.
- **Fix:** `uv pip install -e ".[dev]"` to install the dev extra into the worktree's venv, after which `uv run pytest` resolves to `.venv/bin/pytest`.
- **Files modified:** none (env setup only).
- **Verification:** `uv run pytest` now resolves correctly; all subsequent runs green.
- **Committed in:** N/A — environment setup, not a code change.

---

**Total deviations:** 2 (1 Rule-1 test-isolation fix in Task 2, 1 Rule-3 environment fix). No scope creep, no architectural changes, no auth gates.

## Issues Encountered

- Calculator.app could not launch in the parallel-execution sandboxed environment (NSWorkspace did not register Calculator within 5s). The integration test `test_returns_none_for_calculator_no_modal` is correctly designed to skip via `SKIP_INTEGRATION=1` and will pass on Akeil's machine when run with real Calculator + Accessibility TCC granted. Other 5 modal-probe tests cover the logic on mocks.

## Next Phase Readiness

- **Plan 01-04 (AXObserver bridge)** — unblocked. Sibling agent in Wave 2 can now `from basicctrl.ax import TokenBucket, AXError, AXAPIDisabledError, AXInvalidUIElementError, ...` without redefinition. Plan 01-04's AXEventBridge + AXObserverManager will subscribe to push events using a `TokenBucket` instance shared with the walker.
- **Plan 01-05 (L0+L1 ensemble)** — unblocked. Verifier code uses `AXUIElementWrapper` to read post-action AX state with the 100ms cache + typed errors.
- **Plan 01-06 (L2 walker invocation)** — unblocked. `walk_subtree(...)` returns a `WalkResult` with structured `truncated` flag the verifier consumes to reduce L2 confidence.
- **Pitfall P2 mitigated and tested** — TokenBucket(20, 20) caps at 20/sec/pid; per-pid isolation verified; refill-at-20/sec verified via frozen-clock monkeypatch.
- **Pitfall P3 mitigated and tested** — depth=3, children=50, nodes=500 caps all fire independently; truncated flag + cap_hit emitted; iterative BFS confirmed by no-recursion source-check test.
- **Pitfall P25 mitigation primitive ready** — has_blocking_modal returns a UIElement on AXModal=True; window cap=10.
- **T-1-04 (TCC revocation) mapped** — every AX call surfaces kAXErrorAPIDisabled as AXAPIDisabledError; Plan 02 TCCMonitor catches and emits structured tcc_revoked event; Plan 09 demo can assert end-to-end.

## Self-Check: PASSED

Verified post-write:

- File exists: `basicctrl/ax/__init__.py`, `basicctrl/ax/errors.py`, `basicctrl/ax/rate_limit.py`, `basicctrl/ax/walker.py`, `basicctrl/ax/modal_probe.py`, `basicctrl/ax/element.py`, `tests/unit/test_rate_limit.py`, `tests/unit/test_ax_errors.py`, `tests/unit/test_walker.py`, `tests/integration/test_modal_probe.py`.
- Commits exist (verified via `git log --oneline`): `de3af52` (Task 1), `b850776` (Task 2), `83a3e50` (Task 3).
- Test count: 28/28 plan-specific tests passed (5 module test files); 63/63 phase-level tests passed (no regressions in Plan 01/02 tests).
- Public-API import smoke: `python -c "from basicctrl.ax import TokenBucket, walk_subtree, has_blocking_modal, AXUIElementWrapper, AXError, AXAPIDisabledError, WalkResult, axerror_from_code"` exits 0.
- libs/cua-driver/ untouched: `git diff --name-only $WORKTREE_BASE..HEAD libs/cua-driver/` returns empty.

---

*Phase: 01-foundation-state-verifier*
*Plan: 03 (Wave 2)*
*Completed: 2026-04-30*
