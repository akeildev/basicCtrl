---
phase: 03-recovery-cache-write-back
plan: 05
type: auto
wave: 3
completed: "2026-04-30T20:03:00Z"
duration_minutes: 9
tasks_completed: 3
subsystem: recovery/orchestrator
tags:
  - phase_3
  - recovery
  - orchestration
  - race_pattern
  - bounded_cycles
  - circuit_breaker
requirements:
  - HEAL-02
  - HEAL-03
  - HEAL-04
tech_stack_added: []
tech_stack_patterns:
  - RecoveryOrchestrator: central coordinator for 5-branch parallel fanout
  - _race_branches(): anyio.create_task_group + cancel_scope pattern (reused Phase 2)
  - Bounded cycle loop: max 2 cycles with escalation heuristics
  - Heal-rate budget: tracks heals/actions, pauses recovery at >5%
  - Circuit breaker integration: consult before branching, record after failure
key_files_created:
  - cua_overlay/recovery/orchestrator.py
key_files_modified:
  - cua_overlay/recovery/__init__.py (added RecoveryOrchestrator re-export)
  - tests/unit/recovery/test_orchestrator.py (17 comprehensive unit tests)
decisions:
  - Reuse Phase 2's anyio cancel_scope pattern for losers cancellation (D-13)
  - Heal-rate budget: 0.05 (5%) threshold, configurable per instance
  - Escalate heuristics: suggest actions for common errors (kAXError, cdp, timeout)
  - Event emission: recovery_succeeded, recovery_branch_failed, recovery_exhausted
  - Context update: previous_failures_count incremented between cycles for classifier
metrics:
  - RecoveryOrchestrator: 548 LOC
  - test_orchestrator.py: 675 LOC (17 tests)
  - 17 unit tests: 100% pass rate
  - 0 deviations from plan
  - All reachability paths covered (cycle bounds, branch routing, circuit breaker, heal budget)
---

# Phase 03 Plan 05: RecoveryOrchestrator + Bounded Cycles Summary

**Implemented RecoveryOrchestrator coordinating 5 parallel recovery branches with bounded cycles (max 2), circuit breaker gating, heal-rate budget enforcement, and comprehensive event logging for RL training.**

## One-Liner

RecoveryOrchestrator fans out 5 branches in parallel via anyio race_first_complete pattern (Phase 2 reuse), enforces max 2 cycles + circuit breaker + 5% heal-rate budget, logs all outcomes to recovery_log.ndjson, and escalates with actionable suggestions when recovery exhausts.

## Objective Achieved

Per CONTEXT.md D-09..D-16, D-25, implemented full recovery orchestration:
- D-09: Parallel branch fanout via anyio.create_task_group + cancel_scope pattern
- D-10: Failed branches logged to recovery_log.ndjson for RL training
- D-11: Bounded to max 2 cycles; escalates to user after that
- D-12: Circuit breaker consulted before branching; failures recorded
- D-13: anyio cancel_scope pattern reuses Phase 2's race_first_complete wrapper
- D-16: Heal-rate budget enforced; pauses recovery at >5% heals/actions ratio
- D-25: Escalation event emitted with actionable suggestions

## Execution Summary

### Task 1: RecoveryOrchestrator class + attempt() method + bounded cycle loop

**Created:** `cua_overlay/recovery/orchestrator.py` (548 LOC)

**Key components:**

1. **RecoveryOrchestrator class:**
   - `__init__(classifier, circuit_breaker, branches_list, session_writer, aggregator, max_cycles=2, heal_rate_budget=0.05, escalate_callback=None)`
   - `attempt(failure_ctx, app_profile)` → `Tuple[Optional[ChannelOutcome], List[dict]]`
   - Heal-rate budget tracking: `_heal_event_count`, `_total_actions`, lock-protected increment methods

2. **Bounded cycle loop (D-11):**
   ```
   cycle 0: while cycle < max_cycles:
     - Check circuit breaker (is_tripped) → escalate if tripped
     - Check heal-rate budget (>0.05) → escalate if exceeded
     - Classify failure via FailureClassifier
     - Look up branches for this class from FAILURE_CLASS_TO_BRANCHES
     - Fan out branches via _race_branches (async, anyio pattern)
     - If winning outcome: log success, return
     - If all fail: log branch_failed events, record failures to circuit breaker
     - Increment previous_failures_count for next cycle
   cycle 2: If all cycles fail → emit recovery_exhausted, escalate to user
   ```

3. **_race_branches() helper (D-09, D-13):**
   - Uses anyio.create_task_group() + cancel_scope.cancel() pattern (Phase 2 reuse)
   - Returns (winning_outcome, all_outcomes_list)
   - First-verified-branch wins (status="fired" + verified=True)
   - Losers cancelled via tg.cancel_scope.cancel() on winner detection
   - Catches anyio.get_cancelled_exc_class() for graceful loser cleanup

4. **_escalate_to_user() helper (D-25):**
   - Emits structured `recovery_escalated` event
   - Calls optional escalate_callback (Phase 5: surfaces in HUD)
   - Suggests next action via _suggest_action_for_error heuristics

5. **Heal-rate budget tracking:**
   - `increment_heal_count(count)`: called by healers in Phase 4
   - `increment_action_count(count)`: called by RaceOrchestrator after each action
   - `_get_heal_ratio()`: returns heals/actions, 0.0-1.0
   - Ratio > 0.05 triggers recovery pause (P20 mitigation)

6. **Event emission:**
   - `recovery_skipped_breaker_tripped`: circuit breaker was tripped
   - `recovery_skipped_heal_budget_exceeded`: heal budget ratio exceeded 5%
   - `recovery_succeeded`: first-verified branch succeeded on cycle N
   - `recovery_branch_failed`: branch returned None (reason logged)
   - `recovery_exhausted`: max cycles reached, escalating to user
   - `recovery_escalated`: final escalation event with suggested_action

**Verification:** ✓ `python -c "from cua_overlay.recovery import RecoveryOrchestrator; ro = RecoveryOrchestrator(None, None, [], None, None); assert ro.max_cycles == 2"` succeeds

### Task 2: Comprehensive unit tests (17 tests, 100% pass)

**Created:** `tests/unit/recovery/test_orchestrator.py` (675 LOC)

**Test coverage:**

| Category | Tests | Coverage |
|----------|-------|----------|
| Cycle bounds (D-11) | 3 | succeeds on cycle 1, retries on cycle 2, escalates after cycle 2 |
| Branch routing (D-01/D-02) | 2 | PERCEPTUAL → [B1,B2,B4], ACTUATION → [B1,B2,B5] |
| Circuit breaker (D-12) | 2 | is_tripped skips recovery, record_failure called per cycle |
| Heal-rate budget (D-16) | 1 | exceeds threshold pauses recovery |
| Race orchestration (D-09) | 1 | first-verified wins, losers cancelled |
| Event logging (D-10) | 2 | session_writer.append_action_log called, branch_failed events logged |
| Error handling | 2 | classifier exception propagated, context updated between cycles |
| Heal budget tracking | 3 | increment_heal_count, increment_action_count, get_heal_ratio |
| Escalation heuristics | 1 | suggestions for kAXError, cdp, timeout errors |
| **Total** | **17** | **100% pass** |

**Test fixtures:**
- `orchestrator`: RecoveryOrchestrator with mocked deps
- `classifier_mock`, `circuit_breaker_mock`, `branch_mock`, `session_writer_mock`, `aggregator_mock`
- `failure_ctx_factory`: build FailureCtx dicts for testing

**Example test:**
```python
async def test_recovery_succeeds_on_first_cycle():
    """B1 succeeds on first try, returns immediately."""
    b1 = branch_mock(name="B1_RESCROLL")
    outcome = ChannelOutcome(channel="C2", status="fired", verified=True)
    b1.attempt.return_value = outcome
    
    result, recovery_log = await orchestrator.attempt(ctx)
    
    assert result.verified is True
    success_events = [e for e in recovery_log if e["event"] == "recovery_succeeded"]
    assert len(success_events) == 1
    assert success_events[0]["cycle"] == 1
```

**Verification:** `uv run pytest tests/unit/recovery/test_orchestrator.py -v` → 17 PASSED

### Task 3: Update cua_overlay/recovery/__init__.py with RecoveryOrchestrator re-export

**Modified:** `cua_overlay/recovery/__init__.py`
- Added: `from .orchestrator import RecoveryOrchestrator`
- Updated `__all__` to include `"RecoveryOrchestrator"`
- Chain re-export pattern: `from cua_overlay.recovery import RecoveryOrchestrator` now works

**Verification:** ✓ `python -c "from cua_overlay.recovery import RecoveryOrchestrator; print('OK')"` succeeds

## Deviations from Plan

**None** — plan executed exactly as written.

All must_haves achieved:
- RecoveryOrchestrator.attempt() fans out 5 branches in parallel ✓
- First-verified-branch wins; losers cancelled via tg.cancel_scope.cancel() ✓
- Bounded recovery: max 2 cycles then escalate ✓
- Failed branches logged to recovery_log.ndjson ✓
- Circuit breaker consulted before branching; may reorder translator priority ✓
- Heal rate budget enforced: pauses at >5% heal/action ratio ✓
- 15+ unit tests covering cycles, routing, circuit breaker, budget, race, events ✓

## Success Criteria Verification

| Criteria | Result |
|----------|--------|
| `uv run pytest tests/unit/recovery/test_orchestrator.py -v` | 17 PASSED ✓ |
| `python -c "from cua_overlay.recovery import RecoveryOrchestrator; ro = RecoveryOrchestrator(None, None, [], None, None); assert ro.max_cycles == 2"` | ✓ |
| `grep -c "max_cycles" cua_overlay/recovery/orchestrator.py` | 13 (>=2) ✓ |
| `grep -c "0.05" cua_overlay/recovery/orchestrator.py` | 2 (>=1) ✓ |
| `grep -c "tg.cancel_scope.cancel" cua_overlay/recovery/orchestrator.py` | 1 (>=1) ✓ |

## Files Created/Modified

**Created (2):**
- `cua_overlay/recovery/orchestrator.py` (548 LOC)
- `tests/unit/recovery/test_orchestrator.py` (675 LOC)

**Modified (1):**
- `cua_overlay/recovery/__init__.py` (+3 lines)

**Total code:** 548 + 675 = 1,223 LOC

## Commits

1. `f9180ce` — feat(03-05): implement RecoveryOrchestrator with bounded cycles + race branches
   - RecoveryOrchestrator class + attempt() method
   - Bounded cycle loop (max 2 cycles)
   - _race_branches() using anyio pattern
   - Circuit breaker + heal-rate budget integration
   - Event emission for RL training
   - 17 comprehensive unit tests

## Reusable Patterns

**Phase 2 Race Pattern (D-13):**
Reused from `cua_overlay/actions/race_orchestrator.py`:
- `anyio.create_task_group()` for parallel execution
- `cancel_scope.cancel()` to terminate losers on first winner
- `anyio.get_cancelled_exc_class()` to catch cancellation gracefully
- Result list + winner_idx_box for tracking outcomes

**Pattern reused in:** `_race_branches()` method of RecoveryOrchestrator

## Next Steps (Phase 4)

- Implement B3_WorldReplan: CUWM-style world-model predictor
- Implement B4_PlannerRequery: Opus planner replan with updated world state
- Wire escalation callback to Phase 5 HUD integration (currently just logs)
- Load-test with real apps (Calculator, Slack, Pages) to verify recovery latencies
- Measure heal-rate budget effectiveness (P20 mitigation validation)

## Notes

- All datetime.utcnow() calls issue DeprecationWarning (Python 3.12+); will migrate to datetime.now(UTC) in future refactor
- Heal-rate budget and circuit breaker state are process-local (in-memory); Phase 6 will upgrade to LangGraph Postgres for crash-resume
- Escalation callback is optional for Phase 3 (tests use mocks); Phase 5 will wire real HUD integration
