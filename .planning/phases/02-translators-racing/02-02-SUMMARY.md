---
phase: 02-translators-racing
plan: 02
subsystem: actions
tags: [idempotency, race-policy, asyncio-lock, ndjson, ring-buffer, ACT-03, ACT-04, D-09, D-10, D-11, D-12, D-16, D-17, D-18, D-19, D-30]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: basicctrl.persist.session_writer.SessionWriter (NDJSON sink), basicctrl.state.causal_dag.ActionCanonical (id field doubles as idempotency token)
  - phase: 02-translators-racing
    provides: Wave-0 stub tests (Plan 02-01), pytest asyncio_mode=auto + stress marker
provides:
  - basicctrl.actions package (Wave 1 atomic foundation — idempotency + race policy + duplicate receipt)
  - IdempotencyTokenStore.try_claim() — atomic asyncio.Lock-guarded claim, single winner under concurrent fan-out (D-16, D-17)
  - IdempotencyTokenStore.is_claimed() — lock-free peek for OS-level pre-syscall kill-switch (D-18)
  - ChannelClaim Pydantic model — frozen record of (action_id, claimed_at_ns, claimed_by_channel)
  - RacePolicy enum (AUTO, RACE, SINGLE_CHANNEL) per D-30
  - resolve_race_policy(policy, action_type) dispatcher with T-2-09 destructive-override safety (D-09..D-12)
  - DuplicateReceipt 2-second sliding ring buffer for verifier-side near-miss dedup (D-19)
  - SessionWriter NDJSON event type "idempotency_claim" (the trace replay sink for D-16)
affects: [phase-02 plans 02-04 (channel base), 02-10 (race orchestrator), 02-12 (idempotency stress), phase-03 (recovery uses race winners), phase-04 (cassette replay reads NDJSON claim trace)]

# Tech tracking
tech-stack:
  added: []  # No new dependencies — uses stdlib (asyncio, time, collections.deque), pydantic v2, structlog (already pinned)
  patterns:
    - "Pattern 3 RESEARCH.md — atomic claim under single asyncio.Lock around whole dict mutation; first-claimer-wins is correct by design (Pitfall F)"
    - "Pattern 9 RESEARCH.md — Phase 2 channel registry shape: channels are awaitables that read IdempotencyTokenStore at start of fire path"
    - "TDD RED→GREEN per task: failing test commit precedes implementation commit; visible in git log as test()→feat() pairs"
    - "Server-side safety override (T-2-09): RACE→SINGLE_CHANNEL downgrade emits structlog warning so caller learns ack rejected; type-system + log-event enforcement combined"
    - "Type-system enforced: RacePolicy is str-enum (Pydantic-friendly); claimed_by_channel is Literal['C1','C2','C3','C4','C5'] (orchestrator can't pass an arbitrary string)"

key-files:
  created:
    - "basicctrl/actions/__init__.py — package init re-exporting IdempotencyTokenStore, ChannelClaim, RacePolicy, resolve_race_policy, DuplicateReceipt"
    - "basicctrl/actions/idempotency.py — IdempotencyTokenStore (asyncio.Lock + dict + NDJSON sink) + ChannelClaim Pydantic model"
    - "basicctrl/actions/race_policy.py — RacePolicy enum + 4 dispatch tables (RACE_ALLOWLIST, SINGLE_CHANNEL_ALLOWLIST, DESTRUCTIVE_COMBOS, SAFE_RACE_COMBOS) + resolve_race_policy()"
    - "basicctrl/actions/duplicate_receipt.py — DuplicateReceipt 2s sliding deque ring buffer with O(1) prune-on-record"
  modified:
    - "tests/unit/actions/test_idempotency.py — replaced importorskip stub with 5 real tests (sequential first-wins, concurrent 5-way fan-out single winner, NDJSON trace, lock-free peek without deadlock, monotonic timestamps)"
    - "tests/unit/actions/test_race_policy.py — replaced stub with 11 real tests covering D-10 RACE allowlist, D-11 SINGLE_CHANNEL allowlist, D-12 safe-race combos, T-2-09 destructive override warning capture"
    - "tests/unit/actions/test_duplicate_receipt.py — replaced stub with 6 real tests (first not-dup, within-window dup, outside-window not-dup, different kind/target not-dup, sliding-window bounded buffer)"

key-decisions:
  - "Single asyncio.Lock around the whole _claims dict mutation, NOT per-target locks (D-16 explicit: dict authoritative for live race; per-target locks rejected). Pitfall F: first-claimer-wins is correct by design — race happens at the OS level, not at Python claim level."
  - "Lock-free is_claimed() peek (D-18) — channels call this immediately before the OS syscall to trim the ~50µs uncancellable window. Verified by holding _lock in a separate `async with` block while is_claimed() returns the prior claim without deadlock."
  - "_classify_intrinsic defaults unknown action_type to SINGLE_CHANNEL (conservative). Unknown verbs do NOT race; explicit RACE caller request would still be downgraded only if intrinsic says SINGLE_CHANNEL. This means an unknown verb passed with RACE will NOT race (correct: unknown = unsafe)."
  - "DuplicateReceipt always appends new receipt even when is_duplicate=True so a third-attempt-within-2s also fires near_miss_duplicate; the deque is FIFO + popleft cutoff so unbounded growth is impossible while retaining O(1) operations."
  - "NDJSON write happens INSIDE the asyncio.Lock (after dict mutation). This serializes claim-event ordering across concurrent contention so replay can reconstruct who-won-first deterministically (D-16 trace contract)."
  - "Stub Wave-0 tests used pytest.importorskip; this plan deletes that guard line because the target module now exists. Tests are now active and gating future regressions."

patterns-established:
  - "Per-feature sub-package mirror — basicctrl/actions/ matches tests/unit/actions/, both with __init__.py. Phase 2 Wave 2+ plans (02-04 channel base, 02-10 race orchestrator) follow the same shape."
  - "Module-level frozenset dispatch tables for D-09..D-12 — RACE_ALLOWLIST / SINGLE_CHANNEL_ALLOWLIST / DESTRUCTIVE_COMBOS / SAFE_RACE_COMBOS. All-caps + frozenset enforces immutability + sub-microsecond lookup. Adding new action_types = one-line edit."
  - "Module-level structlog logger via `_log = structlog.get_logger()` — race_policy.py uses module-level logger (stateless function); idempotency.py and duplicate_receipt.py use instance-bound `self._log` (per-instance context if bound later)."
  - "Wave-0 stub → Wave-1 real test transition: replace `pytest.importorskip(MODULE)` line with the actual import. Phase 2 Wave 1+ plans repeat this pattern as their target modules ship."

requirements-completed:
  - ACT-03
  - ACT-04

# Metrics
duration: 4min
completed: 2026-04-30
---

# Phase 2 Plan 02: Atomic Idempotency + Race Policy + Duplicate Receipt Summary

**Atomic foundation that prevents double-fires across racing channels — IdempotencyTokenStore with asyncio.Lock + NDJSON trace (D-16/D-17/D-18), RacePolicy dispatcher with T-2-09 destructive override (D-09..D-12), and a 2-second sliding ring buffer for verifier-side near-miss dedup (D-19).**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-30T06:35:17Z
- **Completed:** 2026-04-30T06:39:01Z
- **Tasks:** 3 (all `type=auto tdd=true`, all green)
- **Files modified:** 7 (4 created in basicctrl/actions/, 3 stub tests rewritten with real assertions)

## Accomplishments

- **IdempotencyTokenStore atomicity proven under concurrent fan-out** — `asyncio.gather` of 5 simultaneous claims returns exactly one winner, four losers (verified by `test_concurrent_claim_exactly_one_winner`). Pitfall F mitigated: first-claimer-wins is correct by design.
- **NDJSON trace serialized inside the lock** — claim events (`{event: "idempotency_claim", action_id, channel, claimed_at_ns}`) are written to SessionWriter.action_log_path BEFORE try_claim returns. Phase 4 cassette replay can reconstruct who-won-first deterministically.
- **RacePolicy enum + 4 dispatch tables encode all of D-09/D-10/D-11/D-12** — 6 RACE verbs, 12 SINGLE_CHANNEL verbs, 5 destructive combos, 2 safe-race combos. All literal entries match CONTEXT.md verbatim.
- **T-2-09 destructive override emits structured warning** — `resolve_race_policy(RACE, "submit")` returns SINGLE_CHANNEL and logs `race_policy.destructive_override_blocked` with reason; verified via `structlog.testing.capture_logs`.
- **DuplicateReceipt prune-on-record** — sliding 2s window via `deque.popleft` while head is older than `ts_ns - 2_000_000_000`. Buffer stays bounded under 1100 entries spanning 3.3s simulated time (well under loose 1000 ceiling).
- **22/22 unit tests pass** (5 idempotency + 11 race_policy + 6 duplicate_receipt) in 0.04s.
- **No regressions in full unit suite**: `pytest -q tests/ -m "not integration and not manual"` shows 145 passed / 13 skipped (was 123/16 in 02-01 — gain of 22 new tests, drop of 3 stubs flipped to active).

## Task Commits

Each task followed strict TDD with separate RED + GREEN commits:

1. **Task 1: IdempotencyTokenStore + ChannelClaim** (D-16, D-17, D-18)
   - `42cbb53` (test) — 5 failing tests added (RED)
   - `afa3388` (feat) — IdempotencyTokenStore + ChannelClaim implementation (GREEN, 5/5 pass)
2. **Task 2: RacePolicy enum + resolve_race_policy dispatcher** (D-09..D-12, D-30, T-2-09)
   - `b380f73` (test) — 11 failing tests added (RED)
   - `010d148` (feat) — RacePolicy + dispatch tables + resolve_race_policy + structlog warning (GREEN, 11/11 pass)
3. **Task 3: DuplicateReceipt 2-second ring buffer** (D-19)
   - `07af951` (test) — 6 failing tests added (RED)
   - `51caadd` (feat) — DuplicateReceipt sliding deque with O(1) prune (GREEN, 6/6 pass)

**Plan metadata:** to be appended after this SUMMARY.md is written.

## Idempotency Contract (D-16, D-17, D-18)

**Authority hierarchy:** in-memory `dict[action_id, ChannelClaim]` is live race authority; SessionWriter NDJSON is replay forensics only.

**Atomic claim path:**
```text
channel coroutine ──► await store.try_claim(action_id, channel)
                          ├─ async with self._lock (single global lock per D-16)
                          ├─ if action_id in dict → return None (loser)
                          ├─ create ChannelClaim(action_id, monotonic_ns(), channel)
                          ├─ self._claims[action_id] = claim
                          ├─ session.append_action_log({"event":"idempotency_claim", ...})
                          └─ return claim (winner)
```

**Lock-free peek (D-18):**
```python
maybe = store.is_claimed(action_id)  # NO await; reads dict directly
if maybe is not None:
    return  # cancelled — another channel won
# proceed to OS syscall (~50µs uncancellable window)
```

**NDJSON event shape:** `{"event": "idempotency_claim", "action_id": "act-1", "channel": "C2", "claimed_at_ns": 12345678}`

## RacePolicy Dispatch Table (D-09..D-12)

| Action class | D-ref | Members | Effective policy under AUTO |
|---|---|---|---|
| RACE allowlist | D-10 | click, click_button, right_click, focus, scroll_to_position, hover | RACE |
| SINGLE_CHANNEL allowlist | D-11 | submit, send, delete, confirm, type_into_focused, type, type_text, type_text_chars, set_value, drag_and_drop, drag, scroll_by_delta | SINGLE_CHANNEL |
| Destructive combos | D-11 | cmd+s, cmd+enter, cmd+return, cmd+w, cmd+z | SINGLE_CHANNEL |
| Safe-race combos | D-12 | cmd+c, cmd+v | RACE |
| Unknown action_type | (default) | anything else | SINGLE_CHANNEL (conservative) |

**Override matrix:**
| Caller-requested | Intrinsic | Effective | Side effect |
|---|---|---|---|
| AUTO | * | intrinsic | none |
| SINGLE_CHANNEL | * | SINGLE_CHANNEL | none (always safe direction) |
| RACE | RACE | RACE | none |
| RACE | SINGLE_CHANNEL | SINGLE_CHANNEL | structlog `race_policy.destructive_override_blocked` warning (T-2-09) |

## DuplicateReceipt Window (D-19)

- **Window size:** locked at 2_000_000_000 ns (2 s) per D-19; not configurable per-instance in Phase 2.
- **Match key:** (target_axid, action_kind) tuple.
- **Prune trigger:** every record() call; while `_buffer[0].ts_ns < ts_ns - 2s`, popleft.
- **Always-append semantics:** even when `is_duplicate=True`, the new receipt is appended so the next post within 2s also fires `near_miss_duplicate`.
- **Bounded:** O(rate × 2s) entries at steady state; e.g. at 333 ops/sec, ≤666 entries.

## Files Created/Modified

### Created
- `basicctrl/actions/__init__.py` — Phase 2 racing-action package init; re-exports IdempotencyTokenStore, ChannelClaim, RacePolicy, resolve_race_policy, DuplicateReceipt
- `basicctrl/actions/idempotency.py` — IdempotencyTokenStore (asyncio.Lock + in-memory dict + NDJSON sink) and ChannelClaim Pydantic model with `Literal["C1","C2","C3","C4","C5"]` channel validator
- `basicctrl/actions/race_policy.py` — RacePolicy str-enum + 4 frozenset dispatch tables + resolve_race_policy() entry-point + _classify_intrinsic() helper for key-combo lookup
- `basicctrl/actions/duplicate_receipt.py` — DuplicateReceipt class with `collections.deque` ring buffer + `_RING_WINDOW_NS = 2_000_000_000` constant + `_Receipt` NamedTuple

### Modified
- `tests/unit/actions/test_idempotency.py` — stub→5 real tests (sequential first-wins, 5-way concurrent gather, NDJSON trace assertion, lock-free-peek-while-locked, monotonic timestamps)
- `tests/unit/actions/test_race_policy.py` — stub→11 real tests (1 per D-10 verb sample + 1 per D-11 verb sample + 2 D-12 combos + 1 destructive combo + override + warning-capture)
- `tests/unit/actions/test_duplicate_receipt.py` — stub→6 real tests (first not-dup, within-window dup, outside-window not-dup, different-kind not-dup, different-target not-dup, sliding-bounded under 1100-entry stress)

## Decisions Made

See `key-decisions` in frontmatter for the full list. Brief rationale highlights:
- **Single global lock vs per-target locks:** D-16 locked single global lock. Per-target locks rejected because the live race happens at the OS level — Python claim level is just bookkeeping. Single lock is also simpler to reason about and fast enough at our action rate (low single-digit ops/sec under speculation).
- **Conservative default for unknown action_type:** unknown verbs return SINGLE_CHANNEL even under RACE caller-request. Trade-off: caller can never opt-in a new verb without adding it to RACE_ALLOWLIST. This is the right safety direction — Phase 4 cognition layer can add new verbs explicitly.
- **NDJSON write inside the lock:** trades a small latency hit (one fsync per claim) for deterministic claim-event ordering during concurrent fan-out. Replay (Phase 4) needs strict ordering; live race already pays the lock cost.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking] Incremental `__init__.py` build-up across Tasks 1→3**
- **Found during:** Task 1 (planning Step 1 of <action>)
- **Issue:** Plan Step 1 of Task 1 specified the full `__init__.py` listing all three modules (`idempotency`, `race_policy`, `duplicate_receipt`), but Tasks 2 and 3 ship the latter two modules. Importing the package after Task 1 would raise `ModuleNotFoundError: basicctrl.actions.race_policy` because the `__init__.py` would try to load a module that doesn't yet exist.
- **Fix:** Wrote `__init__.py` incrementally — only `idempotency` re-export after Task 1, added `race_policy` after Task 2, added `duplicate_receipt` after Task 3. Final state matches the plan's exact spec verbatim.
- **Files modified:** basicctrl/actions/__init__.py (touched in commits afa3388, 010d148, 51caadd)
- **Verification:** `python -c "from basicctrl.actions import IdempotencyTokenStore, ChannelClaim, RacePolicy, resolve_race_policy, DuplicateReceipt; print('ok')"` prints `ok`.
- **Committed in:** afa3388, 010d148, 51caadd (each task's GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Final state is byte-equivalent to plan spec. Each per-task commit is independently importable and testable, which strengthens the per-task atomicity contract. No scope creep, no spec drift.

## Issues Encountered

- pytest `addopts = "-x --tb=short"` stops on first failure during RED phase — expected behavior; surfaces the import error fast and confirms the test would fail without the implementation.
- No other issues. All 6 commits (3 RED + 3 GREEN) landed on first try; no debug iterations needed.

## User Setup Required

None. Pure stdlib + already-installed deps (pydantic v2, structlog, asyncio).

## Next Phase Readiness

- **Plan 02-04 (channel/translator base+registry):** can `import IdempotencyTokenStore` and `import resolve_race_policy` immediately. Channel base class will accept `IdempotencyTokenStore` in `__init__` and call `await store.try_claim(action.id, self.channel_name)` at the start of every fire path.
- **Plan 02-10 (race orchestrator):** can `import resolve_race_policy` to consult the dispatch table before fanning out channels; can `import DuplicateReceipt` to record post-fire receipts after the verifier signals.
- **Plan 02-12 (race idempotency stress):** the `test_concurrent_claim_exactly_one_winner` shape scales directly to the 100+ iteration stress loop. The `@pytest.mark.stress` marker registered in 02-01 is ready.
- **Phase 4 cassette replay:** SessionWriter `action_log.ndjson` now includes `idempotency_claim` events. The Phase 4 replay reader can consume these to reconstruct who-won-first per action.
- **No blockers.** All 22 new tests pass; full unit suite (145 tests, 1.12s) clean; no regressions.

## Self-Check: PASSED

Files created (all 7 verified):
- FOUND: basicctrl/actions/__init__.py
- FOUND: basicctrl/actions/idempotency.py
- FOUND: basicctrl/actions/race_policy.py
- FOUND: basicctrl/actions/duplicate_receipt.py
- FOUND: tests/unit/actions/test_idempotency.py (replaced stub)
- FOUND: tests/unit/actions/test_race_policy.py (replaced stub)
- FOUND: tests/unit/actions/test_duplicate_receipt.py (replaced stub)

Commits verified (all 6 in git log):
- FOUND: 42cbb53 (Task 1 RED)
- FOUND: afa3388 (Task 1 GREEN)
- FOUND: b380f73 (Task 2 RED)
- FOUND: 010d148 (Task 2 GREEN)
- FOUND: 07af951 (Task 3 RED)
- FOUND: 51caadd (Task 3 GREEN)

Acceptance criteria literals (all greppable):
- FOUND: `class IdempotencyTokenStore`, `asyncio.Lock` (×3), `time.monotonic_ns`, `idempotency_claim`, `class ChannelClaim` in idempotency.py
- FOUND: `class RacePolicy`, `RACE_ALLOWLIST`, `SINGLE_CHANNEL_ALLOWLIST`, `DESTRUCTIVE_COMBOS`, `SAFE_RACE_COMBOS`, `def resolve_race_policy`, `race_policy.destructive_override_blocked` (×2) in race_policy.py
- FOUND: `class DuplicateReceipt`, `2_000_000_000`, `near_miss_duplicate` (×2) in duplicate_receipt.py
- FOUND: All 5 names re-exported from basicctrl.actions.__init__

Verification commands (all pass):
- `uv run pytest -q tests/unit/actions/test_idempotency.py` → 5 passed
- `uv run pytest -q tests/unit/actions/test_race_policy.py` → 11 passed
- `uv run pytest -q tests/unit/actions/test_duplicate_receipt.py` → 6 passed
- `uv run pytest -q tests/unit/actions/` → 22 passed, 1 skipped (channel_registry stub waiting for Plan 02-04)
- `uv run pytest -q tests/ -m "not integration and not manual"` → 145 passed, 13 skipped, 0 errors
- `uv run python -c "from basicctrl.actions import IdempotencyTokenStore, ChannelClaim, RacePolicy, resolve_race_policy, DuplicateReceipt; print('ok')"` → `ok`

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
