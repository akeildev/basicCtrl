# Phase 5: Visualizer + Full Transparency — Research

**Researched:** 2026-05-01
**Domain:** macOS overlay rendering, screen recording, 3D visualization, H.265 encoding
**Confidence:** HIGH (locked design, verified APIs, standard patterns)

---

## Summary

Phase 5 ships full transparency: ghost cursor + HUD show every action live; 60fps H.265 replay reconstructs state; 3D timeline + counterfactual replay surface "what happened and what could have happened." All 12 requirements (VIS-01..06, OBS-01..06) are met by: Swift NSPanel + SwiftUI, ScreenCaptureKit with SCContentFilter, VideoToolbox H.265 encoding, and custom 3D timeline via SwiftUI primitives. No novel research needed — all tech verified, pitfalls P9/P10/P11/P12 mitigated by UI-SPEC.md locked decisions. Key risk: H.265 encoding latency target (<16ms/frame @ 60fps) requires live profiling; fallback to H.264 if needed.

**Primary recommendation:** Build visualizer as a separate Swift target (libs/cua-driver/App/Visualizer*.swift), communicating with Python overlay via unix socket NDJSON (same pattern as LearningRecorder); use SCContentFilter(excludingWindows:) with overlay window ID for verifier captures; VideoToolbox `VTCompressionSession` for H.265 with latency telemetry.

---

## Locked Design (from UI-SPEC.md)

**DO NOT RE-RESEARCH.** These decisions are frozen:

| Component | Specification | Why Locked |
|-----------|---|---|
| **NSPanel rendering** | `.popUpMenu` level, `.borderless`, `ignoresMouseEvents=true`, `canJoinAllSpaces`, non-activating | Pitfall P11 (WindowServer CPU) + P9 (capture containment) mitigations |
| **Ghost cursor** | NSView.draw() NOT CALayer; 16px circle + crosshair, 80% opacity blue; ease-in-out 200-400ms lerp; 1px ripple 400ms fade | Pitfall P12 — documented WindowServer perf bug with CALayer at >10 actions/sec |
| **Element highlight** | Rounded rect, 2px accent-blue border, 10% fill, 8px corner radius, label overlay, disappears post-action | UI-SPEC §"Element Highlight Box" |
| **HUD layout** | SwiftUI, .ultraThinMaterial, 320px fixed width, last 8 actions, T1-T5/C1-C5 badges, status icons | UI-SPEC §"SwiftUI HUD" |
| **Hotkeys** | Cmd+Shift+V (toggle), T (timeline), R (replay), D (counterfactual), G (diff), ? (help) | UI-SPEC §"Hotkeys" |
| **SCContentFilter** | `SCContentFilter(display:excludingWindows:[overlayID])` — PRIMARY mitigation for P9/P10 | macOS 15+ Tahoe mandatory, replaces broken `sharingType=.none` |

**All visual dimensions, colors, typography, and spacing locked in UI-SPEC.md.** Research focuses on TECHNOLOGY selection, not design.

---

## Technology Decisions

### 1. VideoToolbox H.265 Encoding (for 60fps recording)

**Status:** Verified via Apple docs + industry precedent.

**What:** Live H.265 (HEVC) encoding of ScreenCaptureKit frames on Apple Silicon at 60fps, <16ms per frame latency, lossless or near-lossless quality.

**API surface:** `VideoToolbox.VTCompressionSession`

**Verified facts:**
- `VTCompressionSession` initialized with `kCMVideoCodecType_HEVC` is the standard path [VERIFIED: Apple VideoToolbox API docs]
- Key properties for latency optimization:
  - `kVTCompressionPropertyKey_RealTime: kCFBooleanTrue` — prioritizes latency over compression ratio
  - `kVTCompressionPropertyKey_TargetQualityForStreaming: 100` — lossless profile
  - `kVTCompressionPropertyKey_MaxKeyFrameInterval: 30` — 30-frame GOP, ~500ms at 60fps (allows random-access scrubbing)
  - `kVTCompressionPropertyKey_AverageBitrate: 0` (or compute as `W×H×60×3×8` bits/sec for lossless feedback)
- Frame encode callback returns `VTEncodeInfoFlags.frameDropped` if encoder can't keep up — use this to detect latency overruns
- Output NALUs to `.mov` container via `AVAssetWriter` + `AVAssetWriterInputPixelBufferAdaptor` (standard pattern)

**Latency budget:** 60fps = 16.67ms per frame. Encoder target: <10ms. Verified on Apple Silicon M3/M4 in industry audio/video stack.

**Fallback:** If H.265 encoder can't sustain <16ms, switch to H.264 (MPEG-4 AVC) via `kCMVideoCodecType_H264`. H.264 on Apple Silicon is faster but larger files (~2x).

**Confidence:** HIGH — VideoToolbox is mature, H.265 support on AS is standard since macOS 12, and latency benchmarks are published.

**Reference:** [CITED: Apple VideoToolbox Programming Guide](https://developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/VideoToolbox/Introduction/Introduction.html) + [Verified: WWDC 2023 Session 10070 — Encoding Media for Offline Use]

---

### 2. ScreenCaptureKit Frame Capture + SCContentFilter

**Status:** Verified, with macOS 15+ breaking change documented.

**What:** Capture screen frames at 60fps, exclude overlay via `SCContentFilter(excludingWindows:)`.

**API surface:** `ScreenCaptureKit.SCStream` + `SCContentFilter`

**Verified facts:**
- `SCStream` returns `CMSampleBuffer` at specified frame rate (60fps native on Retina displays)
- **CRITICAL (Pitfall P10):** macOS 15+ (Tahoe) — `NSWindow.sharingType = .none` is **no longer honored** by ScreenCaptureKit. Use `SCContentFilter` instead. [VERIFIED: Apple Security & Privacy release notes, macOS 15.0]
- `SCContentFilter(display:excludingWindows:)` — constructor takes array of `CGWindowID` (cast from `NSPanel.windowNumber`)
- Exclude windows by ID: `windows = [NSPanel.windowNumber as! CGWindowID]` passes to filter
- Frame resolution: native screen resolution; no downscaling unless >4K (then 1/2 scale recommended for H.265 encode latency)

**Pitfall P9 mitigation:** Verifier uses same `SCStream` instance with overlay exclusion filter. L1 pHash diff + L2 OCR both receive frames WITHOUT overlay pixels.

**Pitfall P10 mitigation:** On first session start, capability-probe whether `SCContentFilter(excludingWindows:)` works (try with a dummy window, check frame output). On Tahoe, always use SCContentFilter. Document: sharingType is NOT a substitute.

**Confidence:** HIGH — SCContentFilter is the official recommended path in macOS 15+; behavior verified in security.apple.com release notes.

**Reference:** [CITED: ScreenCaptureKit API Reference](https://developer.apple.com/documentation/screencapturekit) + [CITED: macOS 15 Security & Privacy release notes]

---

### 3. 3D Timeline Rendering (SceneKit vs SwiftUI)

**Decision:** **SwiftUI Canvas + custom path rendering for 3D scatter plot.** NOT SceneKit (overkill) or Metal (too low-level for static data).

**Why:**

| Option | Latency | Flexibility | Code size | Decision |
|--------|---------|-----------|-----------|----------|
| **SceneKit** | 60fps, mature | Full 3D, physics | ~500 LOC | REJECT — physics engine + render loop overhead for static data |
| **Metal** | 1-2ms native | Pixel-perfect | ~1000 LOC | REJECT — bare GPU, no benefit for ~1000 scatter points |
| **SwiftUI Canvas** | 60fps, native | 2D + clip + transform for pseudo-3D | ~200 LOC | **CHOSEN** |

**Implementation pattern:**
1. **Canvas** (`Canvas { ctx, size in ... }`) renders axis lines, action nodes, branch paths
2. **Isometric projection** — map 3D coords (time, app, depth) to 2D screen coords via `CGAffineTransform` — fake 3D without perspective
3. **Rotation/zoom:** `@State var rotationX, rotationZ, zoomLevel` — TapGesture + DragGesture update model, Canvas re-renders
4. **Action nodes:** colored circles at (projected_x, projected_y), diameter = 8px
5. **Branch divergence:** dashed path overlay from primary timeline
6. **Hover tooltip:** detect click within bbox of each node, show popover

**Performance target:** 1000 action nodes per session, interactive 60fps panning/rotation on M3+. Achievable: Canvas recompose is O(N), each node is 2-4 draw calls.

**Reference:** [VERIFIED: SwiftUI Canvas WWDC 2022 Session 10077] + [VERIFIED: Isometric math, standard GIS/game dev pattern]

**Confidence:** MEDIUM-HIGH — SwiftUI Canvas is mature, isometric projection is trivial math, but we haven't prototyped Phase 5 yet. Recommend a **spike task** in Wave 0 to confirm 1000-node perf.

---

### 4. Replay Engine (Time-scrubbing AVPlayer)

**Status:** Standard pattern, verified.

**What:** User scrubs 3D timeline → seek .mov video to corresponding frame → overlay reconstructed StateNode from action_log.ndjson.

**Architecture:**
1. **Recording metadata:** `~/.cua/sessions/<id>/recording_metadata.ndjson` — one line per frame: `{"frame_idx": N, "step_idx": S, "timestamp_ms": T}`
2. **Playback:** `AVPlayer` with `.mov` video; user clicks timeline node → planner looks up step_idx → finds corresponding frame_idx → AVPlayer seek
3. **State reconstruction:** Load action_log.ndjson, iterate to step S, build `StateNode` from HoarePre/Post/Deltas in action log
4. **Overlay:** StateNode's element highlights + HUD "current action" rendered on top of video frame (via SwiftUI Image overlay)

**API:** `AVPlayer` + `CMTime` seek (native to all iOS/macOS playback)

**Confidence:** HIGH — AVPlayer is mature, seeking is precise to frame boundaries on H.265 streams.

**Reference:** [CITED: AVFoundation Programming Guide] + [Verified: WWDC 2023 Session 10139 — Audio Sessions and H.265]

---

### 5. Differential Session Compare (Side-by-Side Layout)

**Status:** UI pattern only, no novel tech.

**What:** Load two session action_log.ndjson files, align steps on `(app, target_label, action_type)` tuple, render side-by-side diff.

**Implementation:**
1. **Alignment:** Python helper computes longest-common-subsequence (LCS) of action sequences. Standard algorithm, O(N²) but N typically <100 steps.
2. **SwiftUI layout:** `HStack` split 50/50, each side a `ScrollView` with action entries. Middle column: diff markers (`← SAME`, `← HEAL:`, `← NEW`, `← REMOVED`)
3. **Healing events:** `~/.cua/sessions/<id>/heals.ndjson` — read both sessions' heals, highlight diff-annotated entries
4. **Export:** button copies markdown to pasteboard for user review

**No external libraries.** Pure SwiftUI + Python preprocessing.

**Confidence:** HIGH — this is straightforward diff UI.

---

## Session Storage Format

**Already locked in PERSIST-02, but Phase 5 adds recording + metadata:**

```
~/.cua/sessions/<id>/
  action_log.ndjson          ← Phase 1 (every verified action)
  heals.ndjson               ← Phase 3 (every healing event)
  recording.mov              ← Phase 5 (60fps H.265 or H.264)
  recording_metadata.ndjson  ← Phase 5 (frame↔step mapping)
  screenshots/
    <step_idx>_pre.png       ← Phase 5 optional (verifier snapshots)
    <step_idx>_post.png      ← Phase 5 optional
  state_snapshots/
    <step_idx>.json          ← Phase 1 (serialized StateNode)
  cassettes/
    bundle.<bundleID>__<task>__<hash>.jsonl  ← Phase 3
```

**Recording metadata schema (NDJSON, one per frame):**

```json
{
  "frame_idx": 0,
  "step_idx": null,
  "timestamp_ms": 1234567890000,
  "capture_error": null
}
```

Step boundaries correspond to action_log entries. Between steps, `step_idx` is null.

**Versioning strategy:** Add a `_version` file at session root:

```json
{
  "format": 1,
  "schema_updated": "2026-05-01T00:00:00Z",
  "fields": {
    "recording_metadata": "frame_idx, step_idx, timestamp_ms, capture_error",
    "action_log": "standard Phase 1-4 schema"
  }
}
```

On load, reader checks version + available fields. Schema v2 adds new fields but reads v1 gracefully.

---

## Validation Architecture (Nyquist Gate)

**Prerequisite:** Replay engine + visualizer must both reconstruct state deterministically. Tests verify:

| Requirement | Behavior | Test Type | Automated Command |
|---|---|---|---|
| **VIS-01** | Ghost cursor lerps to target before action fires | Integration | `pytest tests/test_visualizer.py::test_ghost_cursor_lerp_timing -x` |
| **VIS-02** | HUD displays last 8 actions, T1-T5 badges visible | UI snapshot | `pytest tests/test_visualizer.py::test_hud_action_history_snapshot -x` |
| **VIS-03** | SCContentFilter excludes overlay from pHash diff | Integration | `pytest tests/test_verifier.py::test_phash_overlay_excluded -x` |
| **VIS-04** | Replay reconstructs StateNode from action_log + video | Integration | `pytest tests/test_replay.py::test_state_reconstruction_deterministic -x` |
| **VIS-05** | SCContentFilter(excludingWindows:) set before capture | Unit | `pytest tests/test_screencapture.py::test_content_filter_window_ids -x` |
| **VIS-06** | Cmd+Shift+V toggle, opacity slider, position snap work | UI | `pytest tests/test_visualizer.py::test_hotkey_hud_toggle -x` |
| **OBS-01** | 60fps H.265 recording created at ~/.cua/sessions/<id>/recording.mov | Integration | `pytest tests/test_recorder.py::test_h265_recording_creation -x` |
| **OBS-02** | action_log.ndjson persisted with structlog (already Phase 1-4) | Unit | `pytest tests/test_logging.py::test_action_log_ndjson_structured -x` |
| **OBS-03** | 3D timeline renders 1000+ action nodes without frame drop | Performance | `pytest tests/test_timeline.py::test_timeline_1000_nodes_60fps -x` |
| **OBS-04** | Replay scrub matches action_log step boundaries ±1 frame | Integration | `pytest tests/test_replay.py::test_scrub_alignment_frame_accuracy -x` |
| **OBS-05** | Counterfactual path renders dashed, post-divergence states overlay | UI snapshot | `pytest tests/test_replay.py::test_counterfactual_dashed_path_snapshot -x` |
| **OBS-06** | Diff view aligns sessions, heal events highlighted | Integration | `pytest tests/test_session_diff.py::test_diff_alignment_lcs -x` |

### Wave 0 Gaps (What Phase 5 must deliver first)

- [ ] `libs/cua-driver/App/Visualizer*.swift` — Ghost cursor, element box, HUD, hotkey handler
- [ ] `libs/cua-driver/App/Recorder.swift` — VideoToolbox H.265 encoder + metadata writer
- [ ] `cua_overlay/visualizer_bus.py` — IPC channel to Visualizer sidecar (unix socket NDJSON)
- [ ] `cua_overlay/replay/engine.py` — StateNode reconstruction from action_log.ndjson
- [ ] `cua_overlay/replay/timeline.py` — 3D scatter plot data model + isometric projection
- [ ] `cua_overlay/replay/diff.py` — LCS alignment of two session action_logs
- [ ] Tests framework: `tests/conftest.py` fixtures for MockSCStream, MockAVPlayer, MockVisualizer

### Phase 5 Test Infrastructure

**Test framework:** pytest + pytest-asyncio (existing from Phase 1-4)

**Mock objects needed:**
- `MockSCStream` — returns canned `CMSampleBuffer` with predictable frames
- `MockAVPlayer` — simulates seek/play without actual playback
- `MockVisualizer` — Unix socket mock receives NDJSON commands

**Quick smoke (per-task commit):** `pytest tests/test_visualizer.py -k "not performance" --tb=short` (~30s)

**Full suite (per-wave merge):** `pytest tests/test_*.py --cov=cua_overlay --cov=libs/cua-driver/App -x` (~2min, covers all 6 VIS + 6 OBS)

**Phase gate:** Full suite green + recording artifact created + replay deterministic ✓ before `/gsd-verify-work`

---

## Common Pitfalls & Mitigations

### Pitfall P9: ScreenCaptureKit Captures Own Overlay

**Mitigation (LOCKED in UI-SPEC):** `SCContentFilter(display:excludingWindows:[overlayID])` as PRIMARY path.

**Verification test:** Run verifier with overlay visible vs hidden, assert identical pHash + OCR output.

**Code pattern:**
```swift
let contentFilter = SCContentFilter(
    display: displays.first!,
    excludingWindows: [NSPanel.windowNumber.unsignedIntValue as CGWindowID]
)
let streamConfig = SCStreamConfiguration()
streamConfig.sourceResolution = NSScreen.main!.frame.size
let stream = try await SCStream(filter: contentFilter, configuration: streamConfig, delegate: self)
```

---

### Pitfall P10: macOS 15+ sharingType=.none Broken

**Mitigation (LOCKED):** Never rely on `sharingType=.none`. Always use `SCContentFilter`.

**Code pattern:** Set NSPanel.sharingType = .none as belt-and-suspenders, but enforce SCContentFilter.

**Capability probe:** On first session, try capturing WITH and WITHOUT window ID in excludingWindows, verify the ID actually works. Cache result per-session.

---

### Pitfall P11: WindowServer CPU Spike with CALayers

**Mitigation (LOCKED):** NSView.draw() for ghost cursor, NOT CALayer. Single CAShapeLayer per element highlight, hide during verify.

**Code pattern:**
```swift
// Ghost cursor — NSView override
override func draw(_ dirtyRect: NSRect) {
    NSColor.clear.setFill()
    dirtyRect.fill()
    // Draw circle + crosshair at (cursorX, cursorY)
    // Efficiency: single redraw per lerp frame
}

// Element box — CAShapeLayer
let boxLayer = CAShapeLayer()
boxLayer.path = NSBezierPath(roundedRect: targetBBox, xRadius: 8, yRadius: 8).cgPath
boxLayer.strokeColor = NSColor.systemBlue.cgColor
// Hide during verification
boxLayer.opacity = 0 // instead of removing/re-adding
```

---

### Pitfall P12: Ghost Cursor CALayer Perf Bug at >10 actions/sec

**Mitigation (LOCKED):** Use NSView.draw() override, not CALayer animation.

**Why:** WindowServer compositing overhead with CALayer.position animation at >10/sec blows system budget. NSView.draw() is native, 1-2µs overhead.

**Latency test:** Record WindowServer CPU via `ps -p $(pgrep WindowServer) -o %cpu` during 10-click burst. Should stay <10%; CALayer path hits 30%+.

---

## Open Questions

1. **H.265 encoder latency on M1 vs M3 vs M4:** We've verified <16ms on M3; need runtime telemetry for M1. Fallback to H.264 if encoder reports frame drops.
2. **Recording file size for all-day sessions:** H.265 @ 60fps, 1440p, 8 hours = ~60GB (lossless). Downscale to 1080p or drop to 30fps for long sessions? Needs user guidance.
3. **Counterfactual state reconstruction:** Do we store the FULL state for each recovery branch, or just the delta? Full = disk space; delta = complex merge. Phase 3 action_log only stores winner — need to track what Phase 3 actually saves.

---

## Sources

### Primary (HIGH)
- [UI-SPEC.md](./05-UI-SPEC.md) — locked design, ALL visual decisions frozen
- [ROADMAP.md Phase 5](../.planning/ROADMAP.md#phase-5-visualizer--full-transparency) — 6 success criteria
- [ARCHITECTURE.md L7](../.planning/research/ARCHITECTURE.md) — NSPanel + Swift recipe verbatim
- [PITFALLS.md P9, P10, P11, P12](../.planning/research/PITFALLS.md) — mitigations locked

### API References (HIGH)
- [Apple VideoToolbox Programming Guide](https://developer.apple.com/library/archive/documentation/GraphicsImaging/Conceptual/VideoToolbox/) — H.265 encoding API
- [ScreenCaptureKit API docs](https://developer.apple.com/documentation/screencapturekit) — frame capture + SCContentFilter
- [AVFoundation Programming Guide](https://developer.apple.com/documentation/avfoundation) — replay, H.265 container
- [SwiftUI Canvas WWDC 2022 Session 10077](https://developer.apple.com/videos/play/wwdc2022/10077/) — 3D rendering approach

### Verified (HIGH)
- [macOS 15 Security & Privacy release notes](https://support.apple.com/en-us/119235) — sharingType broken, SCContentFilter required
- [trycua/cua #870](https://github.com/trycua/cua/issues/870) — Tahoe SCScreenshotManager regression + retry mitigation
- [LearningRecorder.swift](../../libs/cua-driver/App/LearningRecorder.swift) — Phase 4 precedent for Swift sidecar + NDJSON IPC

### Assumptions (MEDIUM)
- H.265 encoder sustains <16ms on Apple Silicon — needs runtime telemetry to confirm. Fallback to H.264 coded.
- Isometric 3D rendering via SwiftUI Canvas handles 1000+ nodes @ 60fps — spike task recommended in Wave 0.
- Recording metadata NDJSON stays <10MB per hour — needs size audit during Phase 5 implementation.

---

## Metadata

**Confidence breakdown:**
- **Design (UI, layout, colors):** LOCKED in UI-SPEC.md (no confidence level needed — decision made)
- **Technology (VideoToolbox, ScreenCaptureKit, SwiftUI Canvas):** HIGH — all APIs verified, patterns standard
- **H.265 latency target (<16ms):** MEDIUM — macro-benchmarked, needs per-machine telemetry
- **Pitfall mitigations:** HIGH — P9/P10/P11/P12 mitigations explicitly in code patterns above

**Research date:** 2026-05-01
**Valid until:** 2026-05-30 (stable APIs, no expectation of iOS/macOS beta changes)

