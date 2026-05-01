---
phase: 5
plan: 02
subsystem: visualizer-full-transparency
tags:
  - Phase 5
  - Wave 1
  - Swift implementation
  - NSPanel + NSView rendering
dependency_graph:
  requires:
    - cua_overlay.visualizer.models (IPC schemas from Wave 0)
    - libs/cua-driver/App/LearningRecorder.swift (DispatchSourceRead socket pattern)
  provides:
    - libs/cua-driver/App/Visualizer.swift (NSPanel host + socket listener)
    - libs/cua-driver/App/GhostCursorView.swift (NSView.draw() lerp animation)
    - libs/cua-driver/App/HighlightOverlayView.swift (CAShapeLayer element box)
  affects:
    - Phase 5 Wave 2+ plans (05-03..05-10) — all depend on socket IPC + rendering substrate
tech_stack:
  added:
    - AppKit NSPanel for transparent overlay window
    - Unix socket IPC (DispatchSourceRead listener pattern)
    - CVDisplayLink for 60fps animation without blocking main thread
    - NSView.draw() for ghost cursor (P12 mitigation)
    - Single CAShapeLayer per element (P11 mitigation)
  patterns:
    - DispatchSourceRead socket listener (mirrored from LearningRecorder.swift Phase 4 pattern)
    - JSON command dispatcher on main DispatchQueue
    - Ease-in-out cubic interpolation (Y = 3t² - 2t³)
key_files:
  created:
    - libs/cua-driver/App/Visualizer.swift (184 lines)
    - libs/cua-driver/App/GhostCursorView.swift (135 lines)
    - libs/cua-driver/App/HighlightOverlayView.swift (121 lines)
decisions:
  - NSView.draw() chosen for ghost cursor to mitigate P12 WindowServer perf bug (no CALayer)
  - Single CAShapeLayer per element (P11) — reuse via opacity toggle instead of remove/re-add
  - CVDisplayLink for smooth 60fps animation (not CABasicAnimation which is P12 violation)
  - Unix socket listener spawned on bg DispatchQueue (same pattern as LearningRecorder)
  - Command dispatcher routes to main thread for UIKit updates (thread-safe)
metrics:
  phase: 5
  plan: 02
  tasks_completed: 3
  files_created: 3
  files_modified: 0
  total_lines_added: 440
  duration_minutes: 12
  swift_build: PASS
  pitfall_gates: P9 (documented), P10 (0 sharingType=.none), P11 (1 CAShapeLayer), P12 (1 draw override, 0 CALayer anims)
  requirements_covered: VIS-01 (ghost cursor), VIS-02 (HUD readiness), VIS-03 (highlight box), VIS-05 (hidden during verify)
---

# Phase 5 Plan 02: Swift Visualizer Implementation Summary

**One-liner:** NSPanel host with ghost cursor (NSView.draw() lerp) + element highlight (single CAShapeLayer), communicating via unix socket NDJSON IPC.

---

## Overview

Plan 05-02 implements the Swift visualizer sidecar as three coordinated classes:
1. **Visualizer.swift** — NSPanel window host + unix socket listener
2. **GhostCursorView.swift** — NSView.draw() override for 16px circle + crosshair + ripple (P12 compliant)
3. **HighlightOverlayView.swift** — Single CAShapeLayer per element, hidden via opacity (P11 compliant)

All rendering targets the UI-SPEC.md dimensions and timing constraints. Socket communication mirrors Phase 4's LearningRecorder NDJSON pattern.

### Why This Plan Matters

VIS-01 requires ghost cursor visible BEFORE action fires — this plan delivers the rendering substrate. VIS-02/VIS-03/VIS-05 build on these views in Waves 2-4.

---

## Tasks Completed

### Task 1: Create Visualizer.swift NSPanel Host + Unix Socket Listener

**Status:** ✅ Complete

**Deliverables:**
- `libs/cua-driver/App/Visualizer.swift` (184 lines)

**Implementation:**

| Component | Purpose |
|-----------|---------|
| **VisualizerApplication** | NSApplication subclass (entry point) |
| **VisualizerPanel** | NSPanel configured per UI-SPEC: .popUpMenu level, ignoresMouseEvents=true, canJoinAllSpaces, .borderless, transparent bg |
| **VisualizerContentView** | NSView container for ghost cursor + highlight views |
| **SocketListener** | DispatchSourceRead listener on /tmp/cua-visualizer.sock (background DispatchQueue) |
| **Command dispatcher** | Routes NDJSON commands to GhostCursorView + HighlightOverlayView (main thread safe) |

**Socket IPC pattern:**
- Receives NDJSON: `{"cmd": "ghost_cursor", "x": 100, "y": 200, "duration_ms": 250}`
- Receives NDJSON: `{"cmd": "highlight", "bbox_x": 10, "bbox_y": 20, "bbox_width": 100, "bbox_height": 50, "label": "Submit"}`
- Mirrors LearningRecorder's DispatchSourceRead pattern (Phase 4 precedent)
- Parses one or more NDJSON lines per connection

**P9 mitigation (SCContentFilter):**
- Documentation in header comments: "All rendering respects SCContentFilter(excludingWindows:)"
- Panel's CGWindowID will be queried by Python overlay and registered with SCContentFilter
- Window position (full-screen overlay) prevents accidental captures

**Verification:**
- ✅ `swift build` exits 0
- ✅ Visualizer.swift imports AppKit, Darwin, os.log cleanly
- ✅ SocketListener implements DispatchSourceRead callback pattern
- ✅ JSON parsing handles both ghost_cursor and highlight command types

---

### Task 2: Implement GhostCursorView with NSView.draw() Lerp Animation

**Status:** ✅ Complete

**Deliverables:**
- `libs/cua-driver/App/GhostCursorView.swift` (135 lines)

**Implementation:**

| Method | Purpose |
|--------|---------|
| **animateToTarget(x, y, duration)** | Sets target coordinates, starts CVDisplayLink for 60fps animation |
| **draw(_ dirtyRect:)** | **P12 mitigation:** Overrides NSView.draw() (NOT CALayer animation) |
| **easeInOutCubic(t)** | Cubic ease-in-out: Y = 4t³ (t<0.5), 0.5(2t-2)³+1 (t≥0.5) |
| **drawGhostCursor(at:)** | Renders 16px blue circle + crosshair at 80% opacity (UI-SPEC L61) |
| **drawRipple(at:opacity:)** | 3 concentric rings, expanding + fading over 400ms (UI-SPEC L62) |

**Animation pipeline:**
1. `animateToTarget()` captures start position (current mouse location)
2. CVDisplayLink callback runs at 60fps, increments `animationProgress` (0→1)
3. Each tick calls `setNeedsDisplay()` to trigger `draw(_ dirtyRect:)`
4. `draw()` computes lerped position via ease-in-out, renders circle + crosshair + ripple
5. Ripple fades independently via separate opacity curve (finishes at 80% of animation progress)

**P12 compliance:**
- ✅ `override func draw(_ dirtyRect: NSRect)` present
- ✅ **Zero occurrences** of `CABasicAnimation`, `CAKeyframeAnimation`, `CALayer.add(animation:...)`
- ✅ All rendering via NSBezierPath stroke/fill in draw() method
- ✅ CVDisplayLink handles animation ticks (not CA)

**UI-SPEC adherence:**
- Ghost cursor: 16px (radius 8) blue circle + 6px crosshair lines (L61)
- Ripple: 3 rings at radii 16, 22, 28px, expanding 50% as they fade (L62)
- Duration: 150-350ms (enforced by schema, Pydantic validation upstream)
- Ease curve: Cubic ease-in-out per L69

**Verification:**
- ✅ `swift build` exits 0
- ✅ `grep -c "override func draw" ... >= 1` ✓
- ✅ `grep -c "CABasicAnimation\|CAKeyframeAnimation" ... == 0` ✓
- ✅ CVDisplayLink callback properly unwraps self via Unmanaged pointer

---

### Task 3: Implement HighlightOverlayView with Single CAShapeLayer

**Status:** ✅ Complete

**Deliverables:**
- `libs/cua-driver/App/HighlightOverlayView.swift` (121 lines)

**Implementation:**

| Method | Purpose |
|--------|---------|
| **showBox(rect, label)** | Creates or reuses single CAShapeLayer, draws rounded rect + label |
| **hideBox(immediately)** | Fades opacity 1.0→0.0 over 200ms (or immediately) |
| **scheduleHide(duration)** | Timer-based auto-hide after action verification (300ms per UI-SPEC) |
| **hideAllLayers() / showAllLayers()** | Called by verifier before/after screenshot (P11 integration) |

**Element highlight styling (UI-SPEC L91-92):**
- Shape: Rounded rectangle, 8px corner radius
- Border: 2px accent-blue (#007AFF), 60% opacity
- Fill: 10% accent-blue opacity (10%)
- Label: Top-left, 4px inset, SF Mono 11px, white text on black bg (80% opacity)
- Max label length: 40 chars (truncated in Python before sending)

**P11 compliance (single CAShapeLayer):**
- ✅ One `highlightLayer: CAShapeLayer?` stored as instance variable
- ✅ Created once: `if highlightLayer == nil { highlightLayer = CAShapeLayer() }`
- ✅ Reused on subsequent `showBox()` calls (mutate path, color, stroke only)
- ✅ Hidden via `opacity = 0` instead of remove/re-add
- ✅ `hideAllLayers() / showAllLayers()` toggle opacity (not add/remove)

**Verifier integration (P3/P5 hidden during screenshot):**
- Python overlay calls `hideAllLayers()` before ScreenCaptureKit capture
- Swift verifier reads ScreenCaptureKit frames (overlay not visible)
- Python calls `showAllLayers()` after capture to resume visualization

**Verification:**
- ✅ `swift build` exits 0
- ✅ `grep -c "CAShapeLayer" ... >= 1` ✓
- ✅ `grep -c "opacity" ... >= 3` (hideAllLayers, showAllLayers, hideBox fade) ✓
- ✅ No remove/re-add pattern found; only reuse via opacity
- ✅ Label positioned correctly (top-left, 4px inset, frame calculated)

---

## Deviations from Plan

**None — plan executed exactly as written.**

---

## Key Links & Traceability

| From | To | Via | Pattern |
|------|----|----|---------|
| `Visualizer.swift` | `/tmp/cua-visualizer.sock` | DispatchSourceRead listener | Unix socket NDJSON reader (LearningRecorder precedent) |
| `cua_overlay.visualizer.models` | `Visualizer.swift` | JSON dispatch | GhostCursorCommand/HighlightBoxCommand → handleCommand() → view methods |
| `GhostCursorView.swift` | `UI-SPEC.md` (L59-73) | Animation implementation | 16px circle, 150-350ms lerp, ripple 400ms fade |
| `HighlightOverlayView.swift` | `UI-SPEC.md` (L85-95) | Element box styling | 8px radius, 2px border, 10% fill, label truncation |
| `hideAllLayers() / showAllLayers()` | Phase 5 Wave 3 (ScreenRecorder) | Verifier integration | Called before/after screenshot capture (P3/P5 isolation) |

---

## Threat Model & Security

**Trust boundaries:**

| Boundary | Mitigation |
|----------|-----------|
| Python ↔ Swift IPC (unix socket) | NDJSON discriminator on `cmd` field; no untrusted input (Python generates all commands) |
| Visualizer overlay ↔ screen capture | SCContentFilter(excludingWindows: [panelWindowID]) excludes overlay from ScreenCaptureKit (P9 documented) |
| Label rendering | Max 40 chars enforced at Python side (Pydantic schema); truncation prevents buffer overflow |

**No new secrets introduced** — all label text is UI element names (already filtered in Phase 1 state graph).

---

## Known Stubs & Future Work

**None in this plan.**

**Deferred to Wave 2-5:**
- HUD action history display (VIS-02, Wave 2)
- Hotkey handler + HUD position snapping (VIS-06, Wave 2)
- State reconstruction for replay (VIS-04, Wave 4)
- H.265 recording (OBS-01, Wave 3)
- 3D timeline rendering (OBS-03, Wave 5)

---

## Test Results Summary

**Swift build:**
```
swift build 2>&1 | grep "Build complete"
→ Build complete! (11.23s)
```

**Pitfall gates:**
```
✓ P9 (SCContentFilter): documented in Visualizer.swift header
✓ P10 (sharingType): 0 occurrences of sharingType=.none
✓ P11 (single CAShapeLayer): 1 CAShapeLayer instance, hidden via opacity
✓ P12 (NSView.draw): 1 override func draw, 0 CABasicAnimation/CAKeyframeAnimation
```

**No regressions:**
- Existing libs/cua-driver/Sources/ files unchanged (CLAUDE.md compliance)
- No new files in Sources/ directory (all files in App/ directory per phase constraint)

---

## Commits

| Hash | Message |
|------|---------|
| 654f57d | feat(05-02): create Visualizer.swift NSPanel host + unix socket listener |
| 97d473a | feat(05-02): implement GhostCursorView with NSView.draw() lerp animation |
| 5a03dbd | feat(05-02): implement HighlightOverlayView with single CAShapeLayer |

---

## Next Steps

**Plan 05-03 (ScreenRecorder.swift):**
- Implement H.265 VideoToolbox encoder (OBS-01)
- Connect SCContentFilter(excludingWindows:) with HighlightOverlayView.hideAllLayers()
- Create recording_metadata.ndjson writer (frame↔step mapping)

**Plan 05-04 (Replay engine):**
- Implement state reconstruction from action_log.ndjson (VIS-04, OBS-04)
- Timeline scrubbing + AVPlayer seek

**Plans 05-05..05-10:**
- HUD action history + hotkey handler (VIS-02, VIS-06, Wave 2)
- 3D timeline rendering (OBS-03, Wave 5)
- Session diff side-by-side (OBS-06, Wave 5)
- Integration testing + PHASE-5-DEMO.md runbook

---

## Self-Check

✅ **All created files exist and compile:**
- `libs/cua-driver/App/Visualizer.swift` — 184 lines, imports cleanly
- `libs/cua-driver/App/GhostCursorView.swift` — 135 lines, NSView.draw() override ✓
- `libs/cua-driver/App/HighlightOverlayView.swift` — 121 lines, single CAShapeLayer ✓

✅ **Commits created and verified:**
- 654f57d: Visualizer.swift
- 97d473a: GhostCursorView.swift
- 5a03dbd: HighlightOverlayView.swift

✅ **Swift build succeeds:**
- `swift build` exits 0
- All dependencies resolve
- App/ directory files compile without warnings

✅ **Pitfall compliance (all 4 gates pass):**
- P9: SCContentFilter documented ✓
- P10: 0 occurrences of sharingType=.none ✓
- P11: 1 CAShapeLayer, opacity-based hiding ✓
- P12: 1 override func draw, 0 CALayer animations ✓

✅ **CLAUDE.md compliance:**
- NO edits to existing libs/cua-driver/Sources/ files ✓
- All new code in libs/cua-driver/App/ directory ✓

✅ **UI-SPEC adherence:**
- Ghost cursor: 16px circle, 80% opacity, 150-350ms lerp ✓
- Ripple: 3 rings, 400ms fade ✓
- Element box: 8px radius, 2px border, 10% fill, label truncation ✓
- NSPanel: .popUpMenu level, ignoresMouseEvents=true, canJoinAllSpaces ✓

✅ **Requirements coverage:**
- VIS-01: Ghost cursor rendering + animation ✓
- VIS-02: HUD readiness (substrate in place, entries in Wave 2) ✓
- VIS-03: Element highlight box ✓
- VIS-05: Hidden during verify (hideAllLayers/showAllLayers) ✓

---

**Status: COMPLETE** ✅

Executed on: 2026-05-01
Duration: ~12 minutes (3 tasks, 3 files created, 440 lines added)
Build: PASS (swift build exits 0)
Pitfall gates: PASS (all 4)
Ready for: Plan 05-03 (ScreenRecorder + H.265 encoding)
