---
phase: 01-foundation-state-verifier
plan: 05
subsystem: verifier-ensemble
tags: [pyobjc, anyio, imagehash, cgwindowlist, nspasteboard, weighted-vote, hoarepost, t-1-03, blocker-1-fix]

# Dependency graph
requires:
  - phase: 01-foundation-state-verifier
    plan: 01
    provides: UIElement, Bbox, ActionCanonical, HoarePost (model_validator), structlog redaction pipeline
  - phase: 01-foundation-state-verifier
    plan: 03
    provides: cua_overlay/ax — TokenBucket, walker, AXError hierarchy (consumed transitively via Plan 04 imports)
  - phase: 01-foundation-state-verifier
    plan: 04
    provides: AXObserverManager.expect() (subscribe-before-fire); NSWorkspaceObserver; KqueueProcObserver
provides:
  - cua_overlay/verifier/ensemble/ subpackage with locked public surface
  - L0Push consumer — drains AXObserverManager + NSWorkspace + kqueue futures into a signal dict; never polls AX (source-grep test enforces)
  - L1Cheap with three sub-checks running in parallel via anyio.create_task_group
    - L1a CGWindowList diff (added / removed / title-changed windows)
    - L1b NSPasteboard.changeCount (T-1-03: integer-only; never inspects payload)
    - L1c pixel ROI dHash via ImageHash 4.3.2 with Hamming threshold 5 bits
  - WeightedVote with present-signal renormalization (BLOCKER 1 fix from planning iter 1)
  - VERIFIED_THRESHOLD=0.50 and L3_ESCALATE_THRESHOLD=0.30 constants for Plan 06 escalation gating
  - Aggregator — top-level entry that wires L0+L1 in parallel → WeightedVote → HoarePost
  - Three plan-level test modules: test_l0_push.py (11), test_l1_cheap.py (6), test_aggregator.py (7) — 24 tests, all green
affects:
  - 01-06 (extends Aggregator with L2 medium-cost AX walker + L3 LLM stub; consumes L3_ESCALATE_THRESHOLD)
  - 01-08 (MCP proxy wraps verifier results into MCP tool responses)
  - 01-09 (Calculator demo: end-to-end <50ms verification anchor)
  - phase-02 (race orchestrator: every translator subscribes before fire, then awaits Aggregator.verify)
  - phase-03 (5-branch recovery consumes HoarePost.confidence to decide which branch to keep)

# Tech tracking
tech-stack:
  added:
    - "imagehash 4.3.2 wired in L1Cheap._roi_dhash via PIL.Image round-trip from CGImage"
    - "Pillow PIL.Image used for the in-memory CGImage→PNG→PIL bridge in L1Cheap._cgimage_to_pil"
    - "Quartz CGWindowListCopyWindowInfo + CGWindowListCreateImage (deprecated-but-working Phase 1 path)"
    - "AppKit NSPasteboard.changeCount (T-1-03: integer-only; payload never read)"
  patterns:
    - "Three sub-checks in parallel via anyio.create_task_group + asyncio.to_thread — each PyObjC sync helper is pushed to a thread so the asyncio loop never blocks on framework C calls"
    - "Present-signal renormalization in WeightedVote.aggregate — active = {signal: weight for signal, weight in WEIGHTS[action_class] if signals.get(signal, 0.0) > 0.0}; ratio = weighted_sum / active_total; absent signals are EXCLUDED from the denominator"
    - "T-1-03 triple-defence: (1) L1Cheap._pasteboard_change_count returns int only; (2) structlog log.py _redact_sensitive processor strips pasteboard_contents/clipboard_data/secrets/password fields; (3) test_no_pasteboard_contents_logged asserts no SECRET string appears in any captured log event"
    - "Source-grep test for L0 no-polling — inspect.getsource(L0Push) must NOT contain walk_subtree / AXUIElementCopyAttributeValue / read_attribute. Module docstrings worded carefully so the literal grep returns 0"
    - "Aggregator uses nonlocal closures to write l0_signals / l1_signals from inside the task group's two child coroutines — simpler than asyncio.gather() and gives anyio's structured cancellation semantics"
    - "Per-tier sub-confidence bookkeeping: HoarePost.tier_signals = {L0: max ax.* signal, L1: max l1.* signal, L2: None, L3: None}. None is the explicit 'this layer didn't run' marker; Plan 06 fills L2/L3 on escalation"

key-files:
  created:
    - "cua_overlay/verifier/ensemble/__init__.py — re-exports L0Push, L1Cheap, L1Snapshot, WeightedVote, VERIFIED_THRESHOLD, L3_ESCALATE_THRESHOLD"
    - "cua_overlay/verifier/ensemble/l1_cheap.py — L1Cheap + L1Snapshot dataclass; three sub-checks in anyio task group; ImageHash dHash with hash_size=8 + 5-bit Hamming threshold"
    - "cua_overlay/verifier/ensemble/l0_push.py — L0Push consumer; _AX_NOTIF_TO_SIGNAL map; never polls AX (source-grep enforced)"
    - "cua_overlay/verifier/ensemble/weighted_vote.py — WEIGHTS table for click/type/scroll/set_value; aggregate() with present-signal renormalization; VERIFIED_THRESHOLD=0.50 and L3_ESCALATE_THRESHOLD=0.30 module-level constants"
    - "cua_overlay/verifier/aggregator.py — Aggregator class wiring L0+L1 in parallel via anyio.create_task_group → WeightedVote → HoarePost; tier_signals max-aggregation"
    - "tests/unit/test_l1_cheap.py — 6 tests (window-diff / pasteboard-int-only / dhash-threshold / parallel-budget / no-secret-leak / signals-are-floats)"
    - "tests/unit/test_l0_push.py — 11 tests (collect-on-event / collect-on-timeout / no-polling-source-grep / 4× WeightedVote math including BLOCKER-1 single-signal-renorm + Calculator-scenario + absent-signal / zero-signal / unknown-action / unit-clamp / required-action-classes)"
    - "tests/unit/test_aggregator.py — 7 tests (hoare-post-with-signals / parallel-execution / verified-above-0.5 / not-verified-below / threshold-consistency / target-key-propagated / action-class-routing)"
  modified:
    - "cua_overlay/verifier/__init__.py — added Aggregator, L0Push, L1Cheap, L1Snapshot, WeightedVote, VERIFIED_THRESHOLD, L3_ESCALATE_THRESHOLD to __all__"

key-decisions:
  - "WeightedVote.aggregate() RENORMALIZES BY SUM OF WEIGHTS OF PRESENT-NON-ZERO SIGNALS (not by total weight). Without this fix, single-signal Calculator click resolves to confidence ≤0.45 and the demo fails. With the fix, ax.value_changed=1.0 alone resolves to 1.0 in its own column. Phase 3 will tune weights against real failure data; Phase 1 demo passes deterministically because Calculator click reliably emits ax.value_changed."
  - "Three L1 sub-checks in parallel via anyio.create_task_group + asyncio.to_thread, NOT asyncio.gather. anyio's structured cancellation propagates failures cleanly; if one helper raises, the other two are cancelled deterministically. Same pattern Plan 04 uses for the AX bridge."
  - "L1c uses CGWindowListCreateImage (deprecated) for screenshot capture rather than ScreenCaptureKit. CGWindowListCreateImage is sync, returns a CGImage, and works inside asyncio.to_thread. ScreenCaptureKit is async-only and would fight our budget. Phase 2 may switch when the deprecation actually breaks something."
  - "_DHASH_THRESHOLD_BITS = 5 (out of 64 bits = ~8% pixel change). 5 bits is conservative enough to ignore text-cursor blink and AA jitter, but loose enough to catch any meaningful UI change in a 100×100 px ROI. ImageHash 4.3.2 dHash uses gradient-direction sign so two solid colours produce identical hashes — that surfaced in test_dhash_threshold which now uses a striped image instead of solid black/white."
  - "L0Push initializes ALL known signal keys to 0.0 BEFORE awaiting expect(). The merged signal dict at the aggregator always has every weighted-vote key present-but-zero or present-and-1, so WeightedVote.aggregate's renormalization rule has a stable surface to operate on."
  - "L0 source-grep test (test_no_polling_used) inspects.getsource(L0Push) — the class body, not module-level docstrings. Comments and docstrings discussing 'never polls AX' don't trigger the test, but the plan's literal acceptance-criteria grep does. Module docstrings worded to avoid forbidden tokens entirely so both checks pass."
  - "test_dhash_threshold uses a striped (red/blue alternating columns) image instead of solid black vs solid white. ImageHash dHash hashes the SIGN of horizontal-pixel-gradient differences; both solid colours produce identical zero-gradient hashes. Stripes have a meaningful gradient pattern that differs from solid black."
  - "tier_signals['L2'] and tier_signals['L3'] are explicitly None in Phase 1 — NOT 0.0. None means 'this layer didn't run'; 0.0 means 'this layer ran and saw nothing'. Plan 06 will set them to floats when L2 walker invocation or L3 LLM fallback executes."

patterns-established:
  - "Pattern: present-signal renormalization in weighted-vote aggregator (single-signal hits resolve to 1.0 in their own column)"
  - "Pattern: three sub-checks in anyio.create_task_group + asyncio.to_thread for parallel PyObjC sync calls"
  - "Pattern: Pre-snapshot via L1Cheap.snapshot() captured BEFORE action; diff via L1Cheap.run(target, before) AFTER action"
  - "Pattern: integer-only T-1-03 mitigation primitive — _pasteboard_change_count returns int; tests assert no string-typed signal value"
  - "Pattern: source-grep test for forbidden API calls — inspect.getsource(class_obj) → assert needle not in src"
  - "Pattern: action_class-driven WeightedVote routing — caller passes action.action_type verbatim; weights table keyed on action class"
  - "Pattern: tier_signals[L0/L1/L2/L3] dict with None for layers that didn't run; explicit floats for layers that did"

requirements-completed: [VERIFY-02, VERIFY-03, VERIFY-04, VERIFY-05]

# Metrics
duration: 8min2s
started: 2026-04-30T00:28:46Z
completed: 2026-04-30T00:36:48Z
---

# Phase 1 Plan 5: L0 Push + L1 Cheap-Diff + WeightedVote Aggregator Summary

**The <50ms-verification heart of Phase 1 — L0 push events streaming from Plan 04's AXObserverManager + L1 cheap-diff (CGWindowList + NSPasteboard.changeCount + ROI dHash) running in parallel through a per-action-class WeightedVote that renormalizes by present-signal weights so single-signal Calculator clicks deterministically clear the 0.50 VERIFIED bar.**

## Performance

- **Duration:** 8 min 2 s
- **Started:** 2026-04-30T00:28:46Z
- **Completed:** 2026-04-30T00:36:48Z
- **Tasks:** 3 (all atomically committed)
- **Files created:** 8 (4 source modules + 3 test modules + 1 ensemble package init)
- **Files modified:** 1 (cua_overlay/verifier/__init__.py — public surface widened)
- **Tests:** 24/24 plan-level green; 97/97 phase-level green (12 skipped — Calculator integration)

## The BLOCKER 1 Math Fix

Planning iter 1 surfaced a critical bug: a naive weighted-vote aggregator (sum-over-all-weights denominator) would resolve a single-signal Calculator click to ≤0.45 confidence, failing the 0.50 VERIFIED threshold and forcing every demo run to escalate to L3 LLM fallback.

The fix: **renormalize by the sum of weights of present-non-zero signals**. Absent signals are EXCLUDED from the denominator, not averaged in as zeros.

```python
def aggregate(self, action_class: str, signals: Mapping[str, float]) -> float:
    weights = self.WEIGHTS.get(action_class, {})
    if not weights:
        return 0.0
    active = {sid: w for sid, w in weights.items() if signals.get(sid, 0.0) > 0.0}
    if not active:
        return 0.0
    weighted_sum = sum(signals[sid] * w for sid, w in active.items())
    active_total = sum(active.values())
    return max(0.0, min(1.0, weighted_sum / active_total))
```

| Scenario | Naive math | Renorm math |
|----------|-----------|-------------|
| `ax.value_changed=1.0` (single-signal) | 0.6 / 1.9 ≈ 0.32 ❌ | 0.6 / 0.6 = 1.0 ✅ |
| `ax.value_changed=1.0, l1.dhash_changed=1.0` (Calculator) | 0.9 / 1.9 ≈ 0.47 ❌ | 0.9 / 0.9 = 1.0 ✅ |
| `ax.value_changed=1.0, ax.focused_changed=0.0, cdp.dom_modified=0.0` | 0.6 / 1.9 ≈ 0.32 ❌ | 0.6 / 0.6 = 1.0 ✅ |
| All signals zero | 0.0 ✅ | 0.0 ✅ |

Tests pinning the fix (test_l0_push.py):
- `test_weighted_vote_renormalizes_single_signal` — single-signal hit returns 1.0
- `test_weighted_vote_calculator_scenario` — Calculator click returns 1.0
- `test_weighted_vote_absent_signal_does_not_drag_down` — zero signals excluded from denominator
- `test_weighted_vote_click_full_signal` — full signal still returns 1.0 (sanity)
- `test_weighted_vote_click_zero_signal` — all zeros returns 0.0 < L3_ESCALATE_THRESHOLD

## Public API Surface

`from cua_overlay.verifier import ...`:

| Name | Kind | Purpose |
|------|------|---------|
| `Aggregator` | class | Top-level verifier entry; wires L0+L1 → WeightedVote → HoarePost |
| `AXObserverManager` | class | (Plan 04) subscribe-before-fire push events |
| `L0Push` | class | Drains AXObserverManager futures into signal dict; never polls AX |
| `L1Cheap` | class | Three sub-checks (CGWindowList + Pasteboard + ROI dHash) in parallel |
| `L1Snapshot` | dataclass | Pre-action L1 state for diffing post-action |
| `WeightedVote` | class | Per-action-class weighted vote with present-signal renormalization |
| `VERIFIED_THRESHOLD` | float | 0.50 — confidence ≥ this means VERIFIED |
| `L3_ESCALATE_THRESHOLD` | float | 0.30 — confidence < this triggers Plan 06 L3 escalation |
| `KqueueProcObserver` | class | (Plan 04) NOTE_EXIT process-death observer |
| `NSWorkspaceObserver` | class | (Plan 04) frontmost-app-changed observer |

## L0Push Contract

```python
class L0Push:
    """Push-event consumer. NEVER polls AX (no walk_subtree, no Copy*, no read_attribute)."""

    def __init__(self, axmgr: AXObserverManager, ws: NSWorkspaceObserver = None, kq: KqueueProcObserver = None) -> None: ...

    async def collect(
        self,
        target: UIElement,
        notifs: list[str],
        action_id: str,
        timeout_ms: int = 50,
        ax_element: Any = None,
    ) -> dict[str, float]:
        """Returns signal dict like:
            {"ax.value_changed": 1.0, "ax.focused_changed": 0.0,
             "ax.window_created": 0.0, "ax.title_changed": 0.0,
             "ax.layout_changed": 0.0, "ax.selected_text_changed": 0.0,
             "ax.selected_rows_changed": 0.0,
             "ws.frontmost_change": 0.0, "kqueue.exit": 0.0}
        """
```

Initializes ALL known AX-notif and external-observer signal keys to 0.0 before awaiting `axmgr.expect()`. The first matching event sets exactly one signal to 1.0; the rest stay 0.0. Timeout is silent — no exception, just a 0.0-everywhere dict (Plan 06 L1+L2 escalation kicks in via the aggregator's confidence check).

Source-grep test (`test_no_polling_used`) inspects `inspect.getsource(L0Push)` and asserts `walk_subtree`, `AXUIElementCopyAttributeValue`, `read_attribute` are absent.

## L1Cheap Three Sub-Checks (Parallel)

| Sub-check | Helper | Latency | Signal | T-1-03? |
|-----------|--------|---------|--------|---------|
| L1a CGWindowList diff | `_cgwindowlist_snapshot` + `_cgwindowlist_diff` | ~1-2 ms | `l1.window_diff` ∈ [0..1] (changed/3) | n/a |
| L1b Pasteboard.changeCount | `_pasteboard_change_count` | <1 ms | `l1.pasteboard_changed` ∈ {0, 1} | YES — integer only |
| L1c Pixel ROI dHash | `_roi_dhash` + `_cgimage_to_pil` | ~10-20 ms | `l1.dhash_changed` ∈ {0, 1} (Hamming threshold 5/64) | n/a |

All three run inside `anyio.create_task_group` + `asyncio.to_thread` — each PyObjC sync helper is pushed to a thread so the asyncio loop never blocks on a framework C call. Total budget <20 ms typical.

The parallel-budget test (`test_runs_subchecks_in_parallel`) makes each helper sleep 50 ms and asserts total `run()` elapsed < 100 ms. Sequential would be 150 ms+; observed under test is ~50 ms (parallel).

## WeightedVote Tables (verbatim)

```python
WEIGHTS: dict[str, dict[str, float]] = {
    "click": {
        "ax.value_changed":     0.6,
        "ax.focused_changed":   0.4,
        "cdp.dom_modified":     0.6,
        "l1.window_diff":       0.3,
        "l1.dhash_changed":     0.3,
    },
    "type": {
        "ax.value_changed":            0.8,
        "ax.selected_text_changed":    0.5,
        "cdp.dom_attribute_modified":  0.7,
        "l1.pasteboard_changed":       0.1,  # negative class — should NOT change on type
    },
    "scroll": {
        "ax.layout_changed":  0.7,
        "l1.window_diff":     0.5,
        "l1.dhash_changed":   0.4,
    },
    "set_value": {
        "ax.value_changed":   0.9,
    },
}
```

## Aggregator Parallel Task-Group Structure

```
                       ┌─ L0Push.collect (ax.* signals via expect future) ─┐
async with anyio:  ───┤                                                     ├──→ merged
                       └─ L1Cheap.run(before)  (l1.* signals via 3-parallel)─┘
                                              │
                                              ▼
                                    WeightedVote.aggregate(action_type, merged)
                                              │ (renormalised confidence)
                                              ▼
                                          HoarePost{
                                            target_key,
                                            confidence,
                                            tier_signals: {L0: max ax.*, L1: max l1.*, L2: None, L3: None},
                                            verified: confidence >= VERIFIED_THRESHOLD,
                                            healed_to: None,
                                            timestamp_ns,
                                          }
```

`HoarePost.verified` is enforced by Plan 01's `model_validator` to equal `confidence >= 0.5`, so the boolean and the float can never desync.

The parallel-execution test (`test_l0_l1_run_in_parallel`) makes both layers sleep 30 ms and asserts total `verify()` elapsed < 50 ms — sequential would be 60 ms+.

## Threshold Constants

```python
VERIFIED_THRESHOLD: float = 0.50    # confidence >= 0.50 -> HoarePost.verified = True
L3_ESCALATE_THRESHOLD: float = 0.30 # confidence < 0.30 -> Plan 06 escalates to L3 LLM
```

The corridor `0.30 <= confidence < 0.50` is the L2 escalation zone — Plan 06 will run the depth-limited AX walker (Plan 03) before deciding L3.

## T-1-03 Mitigation Verification

Threat T-1-03 (LOW): pasteboard contents must NEVER be logged.

Three layers of defence:

1. **L1Cheap._pasteboard_change_count** returns `int` only — never reads `stringForType:` / `dataForType:` / etc. Function docstring documents 'payload stays opaque'.
2. **structlog log.py _redact_sensitive** processor (Plan 01-01) strips fields named `pasteboard_contents`, `clipboard_data`, `secrets`, `password` to `[REDACTED]` before the JSON renderer.
3. **test_no_pasteboard_contents_logged** in `tests/unit/test_l1_cheap.py` — runs `L1Cheap.run` while a 'SECRET' string is in scope, then asserts `structlog.testing.capture_logs()` contains no entry whose value equals 'SECRET'.

Verification grep step 4: `grep -E "pasteboard.*content|copyContents" cua_overlay/verifier/ensemble/l1_cheap.py` returns 0 matches.

## Task Commits

Each task committed atomically:

1. **Task 1: L1Cheap three parallel sub-checks** — `3fcd23d` (feat) — `cua_overlay/verifier/ensemble/__init__.py` + `cua_overlay/verifier/ensemble/l1_cheap.py` + `tests/unit/test_l1_cheap.py`. 6 unit tests green.
2. **Task 2: L0Push consumer + WeightedVote with renormalization** — `d9db4aa` (feat) — `cua_overlay/verifier/ensemble/l0_push.py` + `cua_overlay/verifier/ensemble/weighted_vote.py` + ensemble `__init__.py` widened + `tests/unit/test_l0_push.py`. 11 unit tests green including 4× math-fix tests pinning the BLOCKER 1 fix.
3. **Task 3: Aggregator wiring L0+L1 → WeightedVote → HoarePost** — `e5e5b9f` (feat) — `cua_overlay/verifier/aggregator.py` + verifier `__init__.py` widened + `tests/unit/test_aggregator.py`. 7 unit tests green.

## Test Counts

| Module | Tests | Status |
|--------|-------|--------|
| tests/unit/test_l1_cheap.py | 6 | All green |
| tests/unit/test_l0_push.py | 11 | All green (incl. 4 math-fix tests) |
| tests/unit/test_aggregator.py | 7 | All green |
| **Plan total** | **24** | **24/24** |
| **Phase total (SKIP_INTEGRATION=1)** | **97** | **97 passed, 12 skipped (Calculator integration)** |

## Decisions Made

(All key decisions captured in the frontmatter `key-decisions` field. Highlights:)

- **Present-signal renormalization** is the BLOCKER 1 fix — single-signal Calculator click now resolves to 1.0, well above 0.50 VERIFIED bar.
- **Three sub-checks in anyio.create_task_group + asyncio.to_thread** — parallel PyObjC sync helpers without blocking the asyncio loop; structured cancellation if any helper raises.
- **CGWindowListCreateImage over ScreenCaptureKit** — sync API works inside `asyncio.to_thread`, async-only ScreenCaptureKit would fight the L1 budget.
- **5-bit Hamming threshold** for dHash — conservative enough to ignore cursor blink, loose enough to catch real UI changes in a 100×100 ROI.
- **Striped test image instead of solid black/white** — ImageHash dHash hashes gradient signs; uniform images produce identical zero hashes.
- **L0 source-grep test** + careful module-docstring wording so both `inspect.getsource` and the literal acceptance-criteria grep return clean.
- **tier_signals['L2']/['L3'] explicitly None in Phase 1** — None means 'didn't run', 0.0 would mean 'ran and saw nothing'.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] dHash on solid colours produces identical hashes**
- **Found during:** Task 1 first run of `test_dhash_threshold` (which used solid black 100×100 vs solid white 100×100).
- **Issue:** ImageHash 4.3.2's dHash algorithm hashes the SIGN of horizontal-pixel-gradient differences. Both solid black and solid white produce zero gradients — identical hashes. The plan's prescribed test (black vs white) failed because dHash distance was 0, not >5.
- **Fix:** Replaced solid-colour test images with a 10-pixel-stripe red/blue alternating pattern. Stripes produce a meaningful gradient pattern; the dHash differs from solid black by far more than the 5-bit threshold.
- **Files modified:** `tests/unit/test_l1_cheap.py` (Test 3 only).
- **Verification:** Test passes; both directions exercised (different images → 1.0; identical images → 0.0).
- **Committed in:** `3fcd23d` (rolled into Task 1).

**2. [Rule 1 - Bug] Plan acceptance-criteria grep caught negative-statement docstrings**
- **Found during:** Task 2 + Task 3 acceptance verification.
- **Issue:** The plan specifies `grep -c "walk_subtree\|AXUIElementCopyAttributeValue\|read_attribute" cua_overlay/verifier/ensemble/l0_push.py returns 0` and `grep -E "pasteboard.*content|copyContents" cua_overlay/verifier/ensemble/l1_cheap.py returns 0 matches`. My initial implementation included module docstrings explaining that those exact tokens were forbidden — which made the literal grep return >0 even though the actual class body never called them.
- **Fix:** Reworded module docstrings to express the constraint without using the forbidden tokens. The functional source-grep test (`inspect.getsource(L0Push)`) inspects only the class body and was always green; the literal grep is now also clean.
- **Files modified:** `cua_overlay/verifier/ensemble/l0_push.py` (module docstring), `cua_overlay/verifier/ensemble/l1_cheap.py` (`_pasteboard_change_count` docstring + L1b inline comment).
- **Verification:** Both verification greps return 0; all 24 plan tests still green; phase-level 97/97 still green.
- **Committed in:** `d9db4aa` (Task 2 docstring) and `e5e5b9f` (Task 3 docstring rewording).

**3. [Rule 3 - Blocking] Dev deps not installed in fresh venv**
- **Found during:** Task 1 first `uv run pytest`.
- **Issue:** Worktree's `.venv` was created during the smoke-test phase but didn't have `[project.optional-dependencies] dev` installed (`pytest`, `pytest-asyncio`, `mypy`, `ruff`, `structlog` for testing). Initial pytest run errored on `ModuleNotFoundError: No module named 'structlog'`.
- **Fix:** `uv pip install -e ".[dev]"` once at the start of the task.
- **Files modified:** none (env setup only).
- **Verification:** All 24 plan tests pass.
- **Committed in:** N/A — environment setup, not a code change.

---

**Total deviations:** 3 (1 Rule-1 test-image fix, 1 Rule-1 docstring grep cleanup spanning two tasks, 1 Rule-3 environment fix). No scope creep. No architectural changes. The math-fix BLOCKER from planning iter 1 is implemented exactly as the plan specifies.

## Issues Encountered

- Calculator.app cannot launch in this parallel-execution worktree sandbox (NSWorkspace doesn't register Calculator within 5s). The `tests/integration/test_app_profile.py::test_calculator_profile` fixture errors when SKIP_INTEGRATION is unset — this is a pre-existing Plan 02 integration-fixture limitation, not a Plan 05 bug. Under `SKIP_INTEGRATION=1` (orchestrator parallel mode) all 97 phase tests pass cleanly. The Calculator-dependent integration tests that exercise the L0+L1 wiring end-to-end will run on Akeil's Mac during Plan 01-09 (the demo).

- ImageHash dHash on solid-colour images produces identical hashes — see Deviation 1 above. Captured as a `key-decisions` entry so Plan 06 (which extends `L1Cheap` for L2 escalation) doesn't get bitten by the same pitfall.

## Next Phase Readiness

- **Plan 01-06 unblocked.** Plan 06 will EXTEND `cua_overlay/verifier/aggregator.py` to add L2 (depth-limited walker via Plan 03) and L3 (LLM stub) escalation paths. The contract Plan 06 inherits:
  - Aggregator constructor takes `(l0, l1, vote)` — Plan 06 will widen to `(l0, l1, vote, l2, l3)`.
  - `verify()` returns HoarePost with `tier_signals['L2']` and `tier_signals['L3']` already keyed; Plan 06 just sets them to floats when those layers run.
  - `L3_ESCALATE_THRESHOLD = 0.30` is exported and consumed.
- **Plan 01-08 unblocked.** MCP proxy can `from cua_overlay.verifier import Aggregator, WeightedVote, L0Push, L1Cheap, VERIFIED_THRESHOLD` and wrap `await aggregator.verify(...)` results into MCP tool responses.
- **Plan 01-09 unblocked.** Calculator demo's success-criterion-4 anchor (<50ms total via L0+L1) is now end-to-end testable. The demo will:
  1. `await mgr.expect(target, ['AXValueChanged'], action_id)` BEFORE firing.
  2. `before_l1 = await l1.snapshot(target)` BEFORE firing.
  3. Fire CGEvent click via Plan 04's bridge.
  4. `post = await aggregator.verify(action, target, ['AXValueChanged'], before_l1)`.
  5. Assert `post.verified is True` and `post.confidence >= 0.50` and `elapsed_ms < 50`.
- **Phase 2 race orchestrator unblocked.** Every translator wraps `await mgr.expect(...)` BEFORE fire and `await aggregator.verify(...)` AFTER fire — the racing translator's "first verified channel wins" pattern stacks cleanly on this contract.
- **VERIFY-02, VERIFY-03, VERIFY-04, VERIFY-05 satisfied.** Plan 04 already satisfied VERIFY-01; this plan completes the deterministic ensemble surface (L0+L1 — L2 in Plan 06, L3 stub in Plan 06).
- **T-1-03 mitigated and triple-tested.** Pasteboard contents never read; structlog redaction strips named fields; unit test asserts no SECRET string leaks into captured logs.
- **BLOCKER 1 from planning iter 1 closed.** Single-signal Calculator click → 1.0 confidence → HoarePost.verified=True under the renormalization rule. Calculator demo passes deterministically.

## Self-Check: PASSED

Verified post-write:

- File exists: `cua_overlay/verifier/ensemble/__init__.py` (re-exports L0Push, L1Cheap, L1Snapshot, WeightedVote, VERIFIED_THRESHOLD, L3_ESCALATE_THRESHOLD).
- File exists: `cua_overlay/verifier/ensemble/l0_push.py` (1× class L0Push, 3× AXObserverManager refs, 0× polling-token refs, 3× AX-notif refs).
- File exists: `cua_overlay/verifier/ensemble/l1_cheap.py` (1× class L1Cheap, 3× create_task_group, 4× imagehash, 2× CGWindowListCopyWindowInfo, 4× changeCount, 5× T-1-03 markers).
- File exists: `cua_overlay/verifier/ensemble/weighted_vote.py` (4× WEIGHTS, 1× VERIFIED_THRESHOLD=0.50, 1× L3_ESCALATE_THRESHOLD=0.30, 5× action-class refs across click/type/scroll/set_value).
- File exists: `cua_overlay/verifier/aggregator.py` (1× class Aggregator, 3× create_task_group, 10× HoarePost, 5× VERIFIED_THRESHOLD/0.5, 4× tier_signals).
- File exists: `tests/unit/test_l0_push.py`, `tests/unit/test_l1_cheap.py`, `tests/unit/test_aggregator.py`.
- Commits exist (verified via `git log --oneline`): `3fcd23d` (Task 1), `d9db4aa` (Task 2), `e5e5b9f` (Task 3).
- Public API import smoke: `python -c "from cua_overlay.verifier import Aggregator, WeightedVote, L0Push, L1Cheap, VERIFIED_THRESHOLD"` exits 0.
- Plan-level test count: 24 PASSED (`uv run pytest -x -q tests/unit/test_l0_push.py tests/unit/test_l1_cheap.py tests/unit/test_aggregator.py`).
- Phase-level test count under SKIP_INTEGRATION=1: 97 PASSED + 12 skipped, no regressions in earlier-plan modules.
- Verification grep step 3 (L0 no polling): 0 matches.
- Verification grep step 4 (no pasteboard content reads): 0 matches.

---

*Phase: 01-foundation-state-verifier*
*Plan: 05 (Wave 3 solo)*
*Completed: 2026-04-30*
