---
phase: 5
plan: 08
subsystem: visualizer-full-transparency
tags:
  - Phase 5
  - Wave 5
  - Session diff
  - LCS algorithm
  - SwiftUI UI
dependency_graph:
  requires:
    - cua_overlay.state (UIElement, ActionCanonical schemas from Phase 1-4)
    - cua_overlay.observability (SessionWriter, NDJSON persistence)
  provides:
    - cua_overlay.replay.diff (SessionDiffer, DiffRow, lcs_alignment)
    - libs/cua-driver/App/SessionDiffView.swift (side-by-side SwiftUI diff view)
    - tests/test_session_diff.py (17 comprehensive unit tests)
  affects:
    - Phase 5 Wave 5 finalization (OBS-06 requirement complete)
    - Future replay/comparison tooling
tech_stack:
  added:
    - LCS algorithm (O(N²) longest common subsequence)
    - Pydantic frozen model DiffRow with 5 kinds
    - SwiftUI split-view layout for side-by-side comparison
  patterns:
    - DiffRow uses discriminator-like `kind` field (not union discriminator)
    - SwiftUI Color-coding: gray (same), orange (healed/changed), green (added), red (removed)
    - Heal event detection: verdict failed→verified at same target
key_files:
  created:
    - cua_overlay/replay/diff.py (163 lines)
    - libs/cua-driver/App/SessionDiffView.swift (217 lines)
    - tests/test_session_diff.py (392 lines)
    - tests/fixtures/session_a.ndjson (5 actions)
    - tests/fixtures/session_b.ndjson (6 actions)
  modified:
    - None
decisions:
  - LCS match key is (app, target_label, action_type) tuple — tier/verdict ignored for alignment
  - DiffRow kind "healed" reserved for failed→verified verdict change (heal events)
  - DiffRow kind "changed" for any other tier/verdict mismatch (healing without verdict flip)
  - SwiftUI colors: common=gray, healed=orange, changed=orange, added=green, removed=red
  - Hotkey Cmd+Shift+D for counterfactual conflicts with macOS Dock toggle — documented as known limitation, user can remap
metrics:
  phase: 5
  plan: 08
  tasks_completed: 2
  files_created: 5
  files_modified: 0
  total_lines_added: 772
  duration_minutes: 20
  tests_passing: 17/17 (LCS + diff + model validation)
  requirements_covered: 1/1 (OBS-06 complete)
---

# Phase 5 Plan 08: Session Diff — LCS Alignment + SwiftUI Diff View

**One-liner:** LCS-based session differ aligns two action logs on (app, target_label, action_type) tuple; detects heal events (failed→verified); renders side-by-side SwiftUI split view with color-coded rows.

---

## Overview

Plan 05-08 completes OBS-06 (differential session compare). Implementation ships:

1. **Python LCS differ** (`cua_overlay/replay/diff.py`) — O(N²) alignment + DiffRow model
2. **SwiftUI diff view** (`SessionDiffView.swift`) — split-view layout with markers
3. **Comprehensive tests** (17 unit tests) — LCS edge cases, heal event detection, fixtures

All tests pass. Swift builds cleanly. Ready for Phase 5 finalization.

---

## Tasks Completed

### Task 1: LCS Alignment + Diff Algorithm (Python)

**Status:** ✅ Complete

**Deliverables:**

- `cua_overlay/replay/diff.py` — 163 lines
  - `lcs_alignment(seq_a, seq_b)` — O(N²) longest common subsequence
  - `DiffRow` Pydantic model (frozen) with fields: kind, step_idx_a/b, action_a/b, before/after_verdict, heal_reason
  - `SessionDiffer` class — loads two sessions from NDJSON, generates aligned diff
  - DiffRow kinds: "common", "added", "removed", "changed", "heal"

**Algorithm Details:**

- **Match key:** `(app, target_label, action_type)` tuple — tier and verdict are NOT part of match
- **LCS:** Standard dynamic programming (O(N²) time, O(N²) space)
- **Backtrack:** Produces (index_a, index_b) pairs where:
  - `(i, j)`: matched steps
  - `(i, None)`: removed from A
  - `(None, j)`: added in B
- **Diff generation:** For matched pairs, check if tier or verdict differs:
  - `failed → verified`: kind="heal" (self-healing indicator)
  - Other differences: kind="changed"
  - No difference: kind="common"

**Heal Event Detection:**

When step has same target but:
- Verdict changed `failed → verified` → **heal event** (self-healing marker)
- Tier changed (e.g., T3→T1) → **changed event** (translator swap)
- Both → **heal event** (takes precedence)

**Verification:** ✅ All 7 LCS tests pass + 6 diff generation tests pass

---

### Task 2: SwiftUI Session Diff Side-by-Side View

**Status:** ✅ Complete

**Deliverables:**

- `libs/cua-driver/App/SessionDiffView.swift` — 217 lines
  - `DiffItem` value type with 5 kinds + markerColor computed property
  - `SessionDiffView` struct — split-view layout:
    - Left column: Session A actions
    - Center: diff markers (SAME, HEAL, CHG, NEW, DEL)
    - Right column: Session B actions
  - Color-coded rows:
    - `common` → gray background
    - `healed` → orange background + "HEAL" badge + tier swap reason
    - `changed` → orange background + "CHG" marker
    - `added` → green background + "NEW" marker
    - `removed` → red background + "DEL" marker
  - Toggle "Diffs only" hides matching steps
  - Responsive layout with proper insets and dividers

**Key Features:**

- Marker text: "SAME" (14px monospace), "HEAL" (with reason), "CHG", "NEW", "DEL"
- Action row shows: tier badge (blue), action_type (monospace), target_label (gray, truncated)
- Placeholder text: "(removed)" in gray, "(added)" in gray for unmatched sides
- SwiftUI Canvas-free (uses simple Text + VStack layout for clarity)

**Verification:** ✅ Swift build passes cleanly, preview renders correctly

---

## Test Suite

### Unit Tests (17 total, all passing)

**TestLCSAlignment (7 tests):**
- `test_lcs_identical_sequences` — identical sequences match all pairs
- `test_lcs_removed_step` — removed step shows (i, None) alignment
- `test_lcs_added_step` — added step shows (None, j) alignment
- `test_lcs_empty_a` — empty A sequence
- `test_lcs_empty_b` — empty B sequence
- `test_lcs_both_empty` — both sequences empty
- `test_lcs_match_key_only_app` — match key ignores tier (different tier, same target → matched)

**TestSessionDifferDiffGeneration (6 tests):**
- `test_diff_common_unchanged` — matched steps with no tier/verdict change → kind="common"
- `test_diff_heal_event_failed_to_verified` — verdict failed→verified → kind="heal" with heal_reason
- `test_diff_changed_tier_swap` — tier change (T3→T1) → kind="changed"
- `test_diff_removed_step` — unmatched A step → kind="removed"
- `test_diff_added_step` — unmatched B step → kind="added"
- `test_diff_multiple_rows` — mixed common + heal + removed + added

**TestDiffRowModel (2 tests):**
- `test_diff_row_frozen` — DiffRow is immutable (frozen=True)
- `test_diff_row_all_fields` — all fields populated correctly

**TestSessionDifferLoadSession (2 tests):**
- `test_load_session_from_ndjson` — loads action_log.ndjson from temp dir
- `test_load_session_missing_file` — returns empty list for missing file

**Test Fixtures:**
- `tests/fixtures/session_a.ndjson` — 5 actions (Inbox, Compose[failed/T3], To, Subject, Send)
- `tests/fixtures/session_b.ndjson` — 6 actions (Inbox, Compose[healed/T1], To, Subject, Body, Send)

**Test Results:**

```
pytest tests/test_session_diff.py -v
=============== 17 passed in 0.05s ===============

TestLCSAlignment::test_lcs_identical_sequences               PASSED
TestLCSAlignment::test_lcs_removed_step                      PASSED
TestLCSAlignment::test_lcs_added_step                        PASSED
TestLCSAlignment::test_lcs_empty_a                           PASSED
TestLCSAlignment::test_lcs_empty_b                           PASSED
TestLCSAlignment::test_lcs_both_empty                        PASSED
TestLCSAlignment::test_lcs_match_key_only_app                PASSED
TestSessionDifferDiffGeneration::test_diff_common_unchanged  PASSED
TestSessionDifferDiffGeneration::test_diff_heal_event_failed_to_verified PASSED
TestSessionDifferDiffGeneration::test_diff_changed_tier_swap PASSED
TestSessionDifferDiffGeneration::test_diff_removed_step      PASSED
TestSessionDifferDiffGeneration::test_diff_added_step        PASSED
TestSessionDifferDiffGeneration::test_diff_multiple_rows     PASSED
TestDiffRowModel::test_diff_row_frozen                       PASSED
TestDiffRowModel::test_diff_row_all_fields                   PASSED
TestSessionDifferLoadSession::test_load_session_from_ndjson  PASSED
TestSessionDifferLoadSession::test_load_session_missing_file PASSED
```

---

## Success Criteria

| Criterion | Status |
|-----------|--------|
| lcs_alignment() function ships with correct backtracking | ✅ |
| SessionDiffer.generate_diff() returns DiffRow[] with 5 kinds | ✅ |
| Heal-event detection: failed→verified classified as "heal" | ✅ |
| SessionDiffView renders split-view with color markers | ✅ |
| Swift build exits 0 | ✅ |
| All tests passing (17/17) | ✅ |
| NDJSON fixtures in tests/fixtures/ for reproducibility | ✅ |

---

## Deviations from Plan

**None — plan executed exactly as written.**

---

## Known Limitations & Documentation

### Hotkey Conflict: Cmd+Shift+D

**Finding:** UI-SPEC.md lists Cmd+Shift+D for "Counterfactual toggle" hotkey. This conflicts with macOS's default system-wide binding for **Show/Hide Dock**.

**Impact:** If Cmd+Shift+D is implemented as-is, Akeil will lose the ability to toggle the Dock via keyboard. Dock toggle must be re-enabled via System Settings → Keyboard → Shortcuts.

**Recommendation (deferred to Phase 5 finalization):**
- **Option A:** Keep Cmd+Shift+D and document that user may need to remap Dock toggle in System Settings
- **Option B:** Use alternative hotkey (e.g., Cmd+Opt+D or Cmd+Ctrl+D) to avoid conflict
- **Option C:** Implement hotkey context — only intercept Cmd+Shift+D when overlay is visible/focused

**Current Status:** Documented in this SUMMARY. Decision on resolution left to Phase 5-09/5-10 finalization when SwiftUI hotkey handler is implemented.

---

## Threat Flags

No new threat surface introduced by session diff:

| Flag | File | Description |
|------|------|-------------|
| (none) | | Session diff reads only NDJSON files from ~/.cua/sessions/ (already protected by Phase 1-3 access controls) |

---

## Self-Check

✅ **All created files exist:**
- `cua_overlay/replay/diff.py` — 163 lines, imports cleanly
- `libs/cua-driver/App/SessionDiffView.swift` — 217 lines, Swift 6.0 syntax valid
- `tests/test_session_diff.py` — 392 lines, 17 tests
- `tests/fixtures/session_{a,b}.ndjson` — NDJSON valid

✅ **All commits created:**
1. `90595ad` — feat(05-08): implement LCS alignment + session diff algorithm
2. `f5ec8a6` — feat(05-08): implement SessionDiffView SwiftUI side-by-side diff
3. `9d26d58` — test(05-08): add comprehensive session diff LCS and heal event tests
4. `e1e5413` — test(05-08): add NDJSON fixture files for session diff testing

✅ **Swift build passes:**
```bash
swift build
Building for debugging...
Build complete! (0.09s)
```

✅ **All tests passing:**
```bash
pytest tests/test_session_diff.py -v
17 passed in 0.05s
```

✅ **Requirement coverage:**
- OBS-06: Differential session compare ✓
  - DiffRow with correct kinds ✓
  - Heal-event detection ✓
  - SessionDiffView UI ✓
  - LCS algorithm O(N²) ✓

---

## Key Integration Points

| From | To | Via | Notes |
|------|----|----|-------|
| `lcs_alignment()` | `SessionDiffer.generate_diff()` | Import | Core algorithm |
| `SessionDiffer` | `SessionDiffView` (Swift) | NDJSON file I/O | Python loads, Swift renders |
| `DiffRow.kind` | SwiftUI color mapping | String discriminator | "heal"/"changed"/"common" → colors |
| `heal_reason` | Marker badge | Optional field | Shows tier swap reason (e.g., "T3→T1") |

---

## Commits

| Hash | Message |
|------|---------|
| 90595ad | feat(05-08): implement LCS alignment + session diff algorithm |
| f5ec8a6 | feat(05-08): implement SessionDiffView SwiftUI side-by-side diff |
| 9d26d58 | test(05-08): add comprehensive session diff LCS and heal event tests |
| e1e5413 | test(05-08): add NDJSON fixture files for session diff testing |

---

## Next Steps

**Phase 5 finalization (Plans 05-09..05-10):**
- Resolve Cmd+Shift+D hotkey conflict (documented above)
- Integrate SessionDiffView into Visualizer window
- Connect SessionDiffer Python module to Swift IPC bridge
- Full integration test with real session files
- PHASE-5-DEMO.md operator runbook

---

**Status: COMPLETE** ✅

Executed on: 2026-05-01
Duration: ~20 minutes (2 tasks, 5 files created, 772 lines added)
Test results: 17/17 passing
Ready for: Phase 5 finalization (Plans 05-09, 05-10)
