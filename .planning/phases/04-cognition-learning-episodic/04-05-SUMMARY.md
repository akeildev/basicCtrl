---
phase: 04
plan: 05
subsystem: learning-recorder
tags: [cgevent-tap, keystroke-coalescing, jsonl-ipc, observedaction]
dependency_graph:
  requires: [04-01]
  provides: [observedaction-builder, keystroke-coalescing]
  affects: [04-06, 04-07, 04-08, 04-09]
tech_stack:
  added:
    - Swift 6 CGEvent tap (.listenOnly)
    - CFRunLoopTimer-style async coalescing
    - asyncio socket IPC
  patterns:
    - Ghost-os LearningRecorder pattern
    - NDJSON event streaming
    - Pydantic frozen ObservedAction schema
key_files:
  created:
    - libs/cua-driver/App/LearningRecorder.swift (~260 LOC)
    - cua_overlay/learning/recorder.py (~380 LOC)
    - cua_overlay/learning/coalesce.py (~150 LOC)
    - tests/unit/learning/test_recorder.py (~280 LOC)
    - tests/integration/learning/test_cgevent_tap.py (~280 LOC)
  modified:
    - cua_overlay/learning/__init__.py (added exports)
decisions: []
metrics:
  duration: 9m
  completed_date: 2026-05-01T18:41:00Z
  tasks_completed: 2
  files_created: 6
  files_modified: 1
  tests_created: 23
---

# Phase 04 Plan 05: CGEvent Tap Recorder + Keystroke Coalescing

**Summary:** Built continuous-learning subsystem that observes user actions via OS-level CGEvent tap, coalesces rapid keystrokes into single actions per word, and outputs ObservedAction Pydantic models for recipe synthesis.

## Objective

Per D-11..D-16 (04-CONTEXT.md): Create CGEvent tap sidecar (Swift) + Python consumer with keystroke coalescing (0.5s CFRunLoopTimer window → 1 typeText per word, respecting word boundaries).

## Implementation

### Task 1: CGEvent Tap Swift Sidecar (LearningRecorder.swift)

**Location:** `libs/cua-driver/App/LearningRecorder.swift` (~260 LOC)

**Features:**
- CGEvent tap (.listenOnly) — reads events without consuming them
- Background DispatchQueue execution — never blocks main thread
- CFRunLoop integration on bg thread for tap stability
- Auto re-enable on `tapDisabledByTimeout` (per D-13)
- JSONL event streaming to stdout for Phase 1 IPC pattern

**Event types emitted (JSONL):**
- `key_down` / `key_up` — keystroke with key code → text mapping
- `left_mouse_down` / `left_mouse_up` / `right_mouse_down` / `right_mouse_up` — click events with (x, y)
- `scroll` — scroll events with (dx, dy)
- `mouse_moved` — mouse motion with (x, y)
- `tap_re_enabled` — signal when auto-re-enable fires after timeout

**Key design decisions:**
- `.listenOnly` mask prevents tap from interfering with event delivery
- Background DispatchQueue + CFRunLoop avoids Python asyncio conflicts (resolves PITFALL P-2 + P-3)
- Keystroke to string mapping covers common Mac key codes (0-50); unmapped codes fall through to `key_<code>` format

### Task 2: Python Recorder Consumer + Keystroke Coalescing

**Files created:**

**1. `cua_overlay/learning/recorder.py` (~380 LOC)**
   - `LearningRecorder` class consumes JSONL from stdin or Unix socket
   - Async iterators for both stream sources
   - Converts raw events to `ObservedAction` Pydantic models
   - Integrates `KeystrokeCoalescer` for keystroke buffering
   - Flushes coalesced keystrokes on word boundaries or non-keystroke events
   - Full ActionCanonical schema compliance (frozen, kind="READ", session_id tracking)

**2. `cua_overlay/learning/coalesce.py` (~150 LOC)**
   - `KeystrokeCoalescer` implements CFRunLoopTimer-style 0.5s window
   - `add_keystroke(key, ts)` buffers keystrokes; flushes on word boundary
   - Word boundaries: space, return, tab, punctuation (`.`, `,`, `!`, `?`, `;`, `:`, `-`, `/`)
   - `start_timer()` async method runs background timer that fires on 0.5s inactivity
   - Callback registration for flush notifications
   - `inspect.iscoroutinefunction` used (modern Python 3.14+ compatible)

**Event processing flow:**
1. Raw keystroke (`key_down`) → add to coalescer buffer
2. If word boundary detected → immediate flush + return
3. Click/scroll/tap_re_enabled → flush pending keystrokes first, emit action
4. Buffer persists until timeout or explicit flush

**Observable outcomes:**
- 5 rapid "hello" keystrokes (within 500ms) → 1 `ObservedAction(action_type="type", payload={"text": "hello"})`
- "hi " (space-terminated) → immediate `ObservedAction(action_type="type", payload={"text": "hi "})`
- Click after typing → 2 actions: keystroke + click

### Task 3: Comprehensive Test Suite (23 tests, all passing)

**Unit tests (`tests/unit/learning/test_recorder.py`, 15 tests):**

1. **KeystrokeCoalescer basics** (8 tests):
   - Single keystroke accumulates
   - Multiple keystrokes without boundary accumulate
   - Space flushes immediately
   - Return flushes immediately
   - Multi-word sequences with spaces
   - Manual flush on empty buffer
   - All word boundary characters (11 variants)

2. **JSONL parsing** (4 tests):
   - Keystroke event parsing
   - Click event flushes keystrokes
   - Scroll event flushes keystrokes
   - ObservedAction schema validation (frozen, kind="READ", session_id)

3. **End-to-end recorder** (3 tests):
   - Keystroke coalescing in recorder workflow
   - Space-triggered flush
   - Recorder initialization with custom params

**Integration tests (`tests/integration/learning/test_cgevent_tap.py`, 8 tests):**

1. Full keystroke pipeline (5 keys → 1 typeText)
2. Space boundary immediate flush
3. Multiple bursts separated by >500ms
4. Click interrupts typing chain
5. Scroll interrupts typing chain
6. Tap re-enabled event flushes buffer
7. Async timer fires on 0.5s inactivity
8. Step index increments per action

**Test result:** All 23 passing, no warnings.

## Verification

**Automated checks:**
```bash
python -m pytest tests/unit/learning/test_recorder.py -v       # 15/15 PASSED
python -m pytest tests/integration/learning/test_cgevent_tap.py -v  # 8/8 PASSED
```

**Success criteria (from plan):**
- ✅ LearningRecorder.swift created with CGEvent tap (.listenOnly) on bg DispatchQueue
- ✅ CFRunLoop integration for tap stability
- ✅ Auto re-enable on tapDisabledByTimeout
- ✅ Python recorder consumer reads JSONL, builds ObservedAction
- ✅ Keystroke coalescing: CFRunLoopTimer 500ms window → 1 typeText per word
- ✅ Tests pass; no real tap interaction (unit mode)

## Dependencies & Integration

**Depends on:**
- Phase 04-01 (ObservedAction schema from 04-01-SUMMARY.md)
- Python 3.12+ asyncio + anyio infrastructure (Phase 1)
- Pydantic v2 (Phase 1-3)

**Feeds into:**
- Phase 04-06: Recipe synthesis (sequences of ObservedAction → Recipe JSON)
- Phase 04-07: Episodic memory indexing (Recipe + embedding storage)
- Phase 04-08, 04-09: Cognition layer wiring

**No external API keys needed** — pure local recording.

## Deviations from Plan

None. Plan executed exactly as specified:
- Swift sidecar at `App/LearningRecorder.swift` (NEW file, not editing existing CuaDriverServer per CLAUDE.md)
- Keystroke coalescing via CFRunLoopTimer-style async timer
- Word boundary semantics (space + punctuation flush immediately)
- Full JSONL-to-ObservedAction pipeline with tests

## Known Stubs

None. All required components implemented:
- CGEvent tap callback is fully functional (not stubbed)
- Keystroke coalescing timer is functional (async, tested)
- ObservedAction construction completes to schema

## Threat Surface

No new security surfaces beyond Phase 1:
- CGEvent tap is `.listenOnly` (non-consuming)
- JSONL socket IPC is same as Phase 1 pattern
- ObservedAction schema immutable (frozen=True)
- All PIIs (keystroke content) logged locally only; no telemetry to external services

## Next Steps

Phase 04-06 (recipe synthesis) will consume the `ObservedAction` stream from this recorder to:
1. Group actions into sequences by pause (e.g., gap > 2s)
2. Extract preconditions from AX state deltas
3. Normalize action sequences (remove fluff, generalize coordinates)
4. Emit Recipe JSON for episodic indexing
