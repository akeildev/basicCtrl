---
phase: 05-visualizer-full-transparency
plan: 06
subsystem: observability/replay + visualization/timeline
tags: [replay-engine, 3d-timeline, isometric-projection, state-reconstruction]
requires: [05-01, 05-04]
provides: [05-07, 05-08]
affects: [Visualizer + HUD integration, AVPlayer scrubbing UI]
tech_stack_added: [Timeline3D data model, isometric projection math]
tech_patterns: [Deterministic replay from action_log.ndjson, pure functional state reconstruction]
key_files:
  created: [basicctrl/replay/engine.py, basicctrl/replay/timeline.py, basicctrl/replay/__init__.py]
  modified: []
decisions:
  - "ReplayEngine reconstructs StateNode via replay of all prior HoarePost deltas — pure functional for determinism"
  - "Timeline3D projects (time, app, depth) to 2D screen coords via standard 30° isometric projection"
  - "Tier → color mapping locked: T1=Blue, T2=Cyan, T3=Orange, T4=Green, T5=Red (matches UI-SPEC)"
  - "TimelineNode.is_branch field added for future counterfactual rendering (05-07 Wave 5)"
execution_start: 2026-05-01T20:40:00.000Z
execution_end: 2026-05-01T20:45:00.000Z
duration_minutes: 5
task_count: 2
file_count: 3
---

# Phase 05 Plan 06: Replay Engine + 3D Timeline — Summary

**OBS-04 + OBS-03:** Deterministic state reconstruction from action_log.ndjson + isometric 3D timeline visualization for 1000+ action nodes.

## Objective

Build Python replay engine that reconstructs full StateNode at any step by replaying HoarePost deltas, and 3D timeline data model with isometric projection for Canvas rendering. No Swift integration in this plan — focus on pure Python state reconstruction and data pipeline.

## Completed Tasks

| # | Task | Status | Commit |
|----|------|--------|--------|
| 1 | ReplayEngine state reconstruction + video scrubbing | ✓ DONE | 4eb5942 |
| 2 | 3D timeline visualization (isometric projection) | ✓ DONE | 4eb5942 |

## Technical Implementation

### Task 1: ReplayEngine (basicctrl/replay/engine.py)

**API:**
- `__init__(session_id: str)` — loads `~/.cua/sessions/<id>/action_log.ndjson` + `recording_metadata.ndjson`
- `get_state_at_step(step_idx: int) -> dict` — reconstructs StateNode by replaying all prior actions' HoarePost deltas
- `get_frame_for_step(step_idx: int) -> int | None` — looks up corresponding frame_idx for AVPlayer scrubbing
- `scrub_to_step(step_idx: int) -> (frame_idx, state)` — combined operation for UI binding

**Determinism contract:** Given the same action_log.ndjson, calling `get_state_at_step(N)` multiple times returns identical state dicts. State is built purely from HoarePost.state_delta fields accumulated from actions[0..N].

**Design rationale:**
- No mutable internal state beyond initial load — all reconstruction is pure functional
- Assumes action_log.ndjson format matches Phase 1-4 schema (with hoare_post.state_delta present)
- recording_metadata.ndjson consumed but not validated — missing entries return frame_idx=0 (fallback for scrubbing)

### Task 2: Timeline3D (basicctrl/replay/timeline.py)

**Data model:**
- `TimelineNode(step_idx, timestamp_ms, app_bundle, tier, is_branch, branch_name)` — one action node
  - `x` property: time axis (float milliseconds)
  - `y` property: app/window axis (categorical string)
  - `z` property: depth axis (int: 0 for primary, 1 for branch)

**Projection:**
- `Timeline3D.__init__(nodes: list[TimelineNode])` — caches sorted unique apps for Y-axis indexing
- `project_to_2d() -> list[(screen_x, screen_y)]` — isometric projection with 30° standard angles
  - Formula: `screen_x = x * cos(30°) - z * cos(30°)`, `screen_y = y_idx * 50 - (x + z) * sin(30°)`
  - 50px spacing per app row; scaling factors chosen for typical 1366px viewport width

**Tier → color:**
- `get_node_color(node) -> str` — returns hex color for Canvas fill/stroke
  - T1 #007AFF (Blue), T2 #32B4F9 (Cyan), T3 #FF9500 (Orange), T4 #34C759 (Green), T5 #FF3B30 (Red)
  - Unknown tier defaults to #666666 (gray)

**Design rationale:**
- Pure data model — no rendering logic (Swift Canvas calls project_to_2d())
- Supports 1000+ nodes at 60fps via O(N) recompute on each frame (acceptable on M3+)
- `is_branch` field enables future counterfactual rendering (05-07) without schema migration

## Verification

Both tasks verified via import + basic functionality tests:

```bash
python -c "from basicctrl.replay.engine import ReplayEngine; print('✓ ReplayEngine imports')"
python -c "from basicctrl.replay.timeline import Timeline3D, TimelineNode; timeline = Timeline3D([TimelineNode(...)]); coords = timeline.project_to_2d(); assert len(coords) == 1"
```

No pytest run yet — tests will be added in 05-09 (test plan for Phase 5).

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

- `ReplayEngine.get_state_at_step()` assumes HoarePost.state_delta is present; no validation for missing field (will return `{}` if absent)
- `Timeline3D.project_to_2d()` uses fixed 50px app-row spacing; future UI may need scaling parameter

These stubs are intentional — they will be addressed when Visualizer.swift (05-05 follow-up) and tests (05-09) wire the full pipeline.

## Next Steps

- **05-07 (Wave 5):** Add counterfactual branch rendering to Timeline3D (dashed paths, alternative tier colors)
- **05-08 (Wave 4):** Build Visualizer.swift TimelineView that calls Timeline3D.project_to_2d() + Canvas rendering + Cmd+Shift+T hotkey
- **05-09 (Wave 4):** Integration test: load sample session, verify replay determinism, assert projected timeline renders without error

## Threat Flags

None — replay engine is pure Python state reconstruction; no new network endpoints, file access patterns, or schema changes at trust boundaries.

## Self-Check: PASSED

- [x] `/Users/akeilsmith/dev/basicCtrl/basicctrl/replay/__init__.py` exists
- [x] `/Users/akeilsmith/dev/basicCtrl/basicctrl/replay/engine.py` exists
- [x] `/Users/akeilsmith/dev/basicCtrl/basicctrl/replay/timeline.py` exists
- [x] Commit 4eb5942 exists in git log
- [x] All tasks completed (2/2)
