# Requirements: cua-maximalist

**Defined:** 2026-04-29
**Core Value:** Autonomous control of any Mac surface, with deterministic self-healing and full transparency — never silently fails, never gives up, never makes the user babysit.

## v1 Requirements

All 79 active requirements are v1. Phased across 6 milestones per ARCHITECTURE.md.

### Foundation

- [ ] **CORE-01**: Fork `trycua/cua` to `~/dev/cua-maximalist/` with Python overlay scaffold above `libs/cua-driver/`
- [ ] **CORE-02**: Hook into `ToolRegistry.swift:55-97` post-action callback to emit structured events to Python overlay
- [ ] **CORE-03**: Initialize app classifier — `bundleID → AppProfile` with capability probe (AX-rich? .sdef? CDP-port? Tauri/Wails?), cached per-bundle per-session

### State Bridge

- [ ] **STATE-01**: Typed-graph state model — `UIElement{id, role, label, value, bbox, capabilities, confidence, source[], visual_embedding, ocr_text, history[t-5..t-1], caused_by, causes[], episodic_ref}`
- [ ] **STATE-02**: Causal DAG of action → state delta
- [ ] **STATE-03**: Temporal ring buffer (last 5 frames)
- [x] **STATE-04**: Episodic memory — FAISS vector store keyed by `(app, task_class, state_fingerprint)`

### Protocol Translators

- [x] **TRANS-01**: T1 AX SPI translator — bidirectional read/write via AXUIElement + private `_AXUIElementGetWindow` + `_AXObserverAddNotificationAndCheckRemote`
- [x] **TRANS-02**: T2 CDP translator — auto-relaunch Electron apps with `--remote-debugging-port`, attach via WebSocket, full DOM/JS/network access
- [x] **TRANS-03**: T3 AppleScript translator — NSAppleScript in-process via py-applescript, ScriptingBridge typed access for apps with .sdef
- [x] **TRANS-04**: T4 Vision/Screen2AX translator — Vision OCR (ocrmac) + MacPaw Screen2AX synthetic tree + uitag SoM (Apple Vision + YOLO11 MLX) for non-AX apps
- [x] **TRANS-05**: T5 Pixel translator — CGEvent + SkyLight `SLEventPostToPid` (background, no cursor warp) for total fallback

### Racing Action Delivery

- [x] **ACT-01**: Action channel registry — C1 SLEventPostToPid, C2 AX kAXPress, C3 CGEvent.postToPid, C4 AppleScript, C5 CDP Input.dispatch
- [x] **ACT-02**: Race orchestrator — `asyncio.wait(FIRST_COMPLETED)` across channels, cancel losers when first verifier passes
- [x] **ACT-03**: Atomic idempotency tokens — written to shared state before fire, channels skip if already claimed
- [x] **ACT-04**: Action interference mitigations — staggered_race for AppleScript, AX rate-limit (cmux #2985 fix, 20 calls/sec/pid token bucket), pre-action AX validity check, per-action-class race policy (read/focus/scroll race; submit/send/delete single-channel)

### Push-Event Verifier

- [ ] **VERIFY-01**: AXObserver subscription manager — subscribe to kAXValueChanged / kAXFocusedUIElementChanged / kAXWindowCreated / kAXTitleChanged / kAXLayoutChanged / kAXSelectedTextChanged / kAXSelectedRowsChanged BEFORE action fires
- [ ] **VERIFY-02**: NSWorkspace + DistributedNotificationCenter + CDP DOM mutation + kqueue EVFILT_PROC subscriptions
- [ ] **VERIFY-03**: Event aggregator with weighted vote per action class
- [ ] **VERIFY-04**: L0 push events (0ms, already subscribed) — primary signal
- [ ] **VERIFY-05**: L1 cheap diff (1-5ms) — CGWindowList diff, NSPasteboard.changeCount, pixel ROI dHash via ImageHash
- [ ] **VERIFY-06**: L2 medium (50-200ms) — Vision OCR text diff (ROI), AX depth-limited subtree (3 levels MAX, never full recursive)
- [ ] **VERIFY-07**: L3 LLM fallback (300-800ms) — only when ensemble confidence < 0.30

### Failure Classifier + Recovery

- [ ] **HEAL-01**: 6-class typed failure enum — Perceptual / Cognitive / Actuation / Environmental / Resource / Loop
- [ ] **HEAL-02**: 5-branch parallel recovery — re-scroll+AX, OCR regrounding+CGEvent, world-model replan, planner replan, AppleScript fallback
- [ ] **HEAL-03**: First-verified branch wins, others cancelled, failed branches → RL training buffer
- [ ] **HEAL-04**: Bounded recovery — max 2 cycles then escalate to user
- [ ] **HEAL-05**: Circuit breaker after 3 consecutive failures on same target + heal-event emission with rate budget (defeats 41% silent-mask abandonment problem)

### Cache Self-Heal Write-Back

- [ ] **CACHE-01**: AgentCache port — SHA-256 keyed by `(bundleID, role_path, instruction)`
- [ ] **CACHE-02**: Cassette replay — replay until broken step, live re-execute, semantic diff write-back of healed selectors (Stagehand AgentCache.ts:573-624 pattern)
- [ ] **CACHE-03**: Stream wrapping for transparent caching of streaming results

### Continuous Learning

- [x] **LEARN-01**: CGEvent tap (.listenOnly) on background thread via Swift sidecar (ghost-os pattern, LearningRecorder.swift:62-88)
- [x] **LEARN-02**: Keystroke coalescing via CFRunLoopTimer (0.5s) — 1 typeText per word
- [x] **LEARN-03**: Auto re-enable on tapDisabledByTimeout
- [x] **LEARN-04**: Recording → ObservedAction → Recipe JSON synthesis (params + preconditions + steps + per-step on_failure)
- [x] **LEARN-05**: Episodic memory retrieval — "last time we did this" lookup before planning

### Cognitive Layer

- [x] **COG-01**: Planner agent (Claude Opus class) with bounded plan generation
- [x] **COG-02**: Grounder (UI-TARS-1.5-7B MLX local via mlx-vlm) running in parallel with planner; uitag SoM as primary, sanity gate against #330 quantization bug
- [x] **COG-03**: Verifier-LLM (V-Droid prefill-only, prefix-cached, 0.7s/step batch)
- [x] **COG-04**: World-model predictor (CUWM-style — predicts post-state before action)
- [x] **COG-05**: Apple FoundationModels tier-0 classifier — local 3B for routing decisions (binary/small-enum only; 4096 ctx limit; text-only API gate)
- [x] **COG-06**: Critic / recovery arbiter — ranks oracle outputs, never self-critiques (avoids 16-27% intrinsic accuracy trap)
- [x] **COG-07**: Speculative pre-execution — draft model predicts steps N+1, N+2 in parallel with N's verifier; READ-ONLY only (Skyvern agent.py:4337 pattern)
- [x] **COG-08**: Ensemble vote on action selection (Opus + GPT-5 + Apple FM, majority + tiebreaker)

### Persistence + Durable Execution

- [ ] **PERSIST-01**: Each translator call wrapped as durable step (LangGraph PostgresSaver, local Postgres)
- [ ] **PERSIST-02**: `~/.cua/sessions/<id>/` structure — snapshot.json, action_log.ndjson, checkpoints/, recipes/, cassettes/, recordings/
- [ ] **PERSIST-03**: Crash → resume from last verified step

### Visualizer

- [x] **VIS-01**: NSPanel transparent overlay (.borderless, .nonactivatingPanel, ignoresMouseEvents, .popUpMenu level, canJoinAllSpaces)
- [x] **VIS-02**: Ghost cursor with NSView.draw + ease-in-out lerp + click ripple (NOT CALayer — WindowServer perf bug)
- [x] **VIS-03**: Element box highlight via kAXFrameAttribute, semi-transparent rectangle with label
- [ ] **VIS-04**: SwiftUI HUD with .ultraThinMaterial — last 8 actions, status icons, tier badges (T1-T5 / C1-C5)
- [x] **VIS-05**: SCContentFilter excludes overlay from own captures (macOS 15+ where sharingType=.none no longer works)
- [x] **VIS-06**: Toggle/config — Cmd+Shift+V hotkey, opacity slider, position snap

### Full Transparency

- [x] **OBS-01**: 60fps lossless H.265 screen recording per session via CoreMediaIO
- [ ] **OBS-02**: Per-step state snapshot logging (full StateNode at every step) via structlog NDJSON
- [x] **OBS-03**: 3D timeline visualization (X=time, Y=app/window, Z=action depth)
- [x] **OBS-04**: Replay any past session with full state at every step
- [ ] **OBS-05**: Counterfactual replay — "what if branch B had won?"
- [ ] **OBS-06**: Differential session compare

### Private SPI Integration

- [ ] **SPI-01**: SkyLight `SLEventPostToPid` Swift bridge — background events, no cursor warp
- [ ] **SPI-02**: `_AXObserverAddNotificationAndCheckRemote` — Electron AX trees stay alive when occluded
- [ ] **SPI-03**: `CGSManagedDisplaySetCurrentSpace` — cross-Space window control
- [ ] **SPI-04**: Endpoint Security `es_new_client` — kernel-level fork/exec/file-event observation
- [ ] **SPI-05**: DTrace probes for app internals (SIP off OK locally)
- [ ] **SPI-06**: DYLD_INSERT_LIBRARIES + Mach injection into Electron renderers (SIP off, arm64e signing spike required)
- [ ] **SPI-07**: WebKit RemoteInspector private headers for Safari deep access
- [ ] **SPI-08**: AppleSPUHIDDevice IMU reader (undocumented MEMS sensor, lid-angle / motion / vibration)

### MCP Server Interface

- [ ] **MCP-01**: Maintain trycua/cua's existing MCP server surface (the Python overlay extends, doesn't replace)
- [x] **MCP-02**: Expose self-healing wrapper as MCP tools so Claude Code / Cursor / Codex can invoke it

## v2 Requirements

(None — everything in v1 per user directive: "build this entire thing end to end in its entirety and full power")

## Out of Scope

| Feature | Reason |
|---|---|
| Production-grade security / safety guards | Local-only experimental; we trust ourselves |
| App Store distribution / sandboxing | Uses private SPIs, no production code-signing path |
| Cross-platform (Windows / Linux) | Mac-only by design |
| Multi-user / cloud-hosted | Akeil's machine only |
| Headless server operation | Needs a real desktop, GUI, and active session |
| Microsoft Teams / new Outlook | Native AppKit (not Electron); use AX path; no special integration |
| Game engine accessibility plugins | Out of scope; games fall through to T4 SoM + T5 pixel |
| Pre-action LLM verification | Production research says wasted latency for marginal gain; post-action only |
| Intrinsic LLM self-correction | Papers 2601.00828 + 2412.14959 prove 16-27% accuracy + cognitive wavering |
| Full recursive AX tree diff | 15-20s on Safari (confirmed); always depth-limited (3 levels) |
| VLM-pixel-only as primary path | 5-25% OSWorld success rate; fallback only |

## Traceability

Phase mapping (filled by roadmapper, 2026-04-29):

| Requirement | Phase | Status |
|---|---|---|
| CORE-01 | Phase 1 | Pending |
| CORE-02 | Phase 1 | Pending |
| CORE-03 | Phase 1 | Pending |
| STATE-01 | Phase 1 | Pending |
| STATE-02 | Phase 1 | Pending |
| STATE-03 | Phase 1 | Pending |
| STATE-04 | Phase 4 | Complete |
| TRANS-01 | Phase 2 | Complete |
| TRANS-02 | Phase 2 | Complete |
| TRANS-03 | Phase 2 | Complete |
| TRANS-04 | Phase 2 | Complete |
| TRANS-05 | Phase 2 | Complete |
| ACT-01 | Phase 2 | Complete |
| ACT-02 | Phase 2 | Complete |
| ACT-03 | Phase 2 | Complete |
| ACT-04 | Phase 2 | Complete |
| VERIFY-01 | Phase 1 | Pending |
| VERIFY-02 | Phase 1 | Pending |
| VERIFY-03 | Phase 1 | Pending |
| VERIFY-04 | Phase 1 | Pending |
| VERIFY-05 | Phase 1 | Pending |
| VERIFY-06 | Phase 1 | Pending |
| VERIFY-07 | Phase 1 | Pending |
| HEAL-01 | Phase 3 | Pending |
| HEAL-02 | Phase 3 | Pending |
| HEAL-03 | Phase 3 | Pending |
| HEAL-04 | Phase 3 | Pending |
| HEAL-05 | Phase 3 | Pending |
| CACHE-01 | Phase 3 | Pending |
| CACHE-02 | Phase 3 | Pending |
| CACHE-03 | Phase 3 | Pending |
| LEARN-01 | Phase 4 | Complete |
| LEARN-02 | Phase 4 | Complete |
| LEARN-03 | Phase 4 | Complete |
| LEARN-04 | Phase 4 | Complete |
| LEARN-05 | Phase 4 | Complete |
| COG-01 | Phase 4 | Complete |
| COG-02 | Phase 4 | Complete |
| COG-03 | Phase 4 | Complete |
| COG-04 | Phase 4 | Complete |
| COG-05 | Phase 4 | Complete |
| COG-06 | Phase 4 | Complete |
| COG-07 | Phase 4 | Complete |
| COG-08 | Phase 4 | Complete |
| PERSIST-01 | Phase 1 | Pending |
| PERSIST-02 | Phase 1 | Pending |
| PERSIST-03 | Phase 1 | Pending |
| VIS-01 | Phase 5 | Complete |
| VIS-02 | Phase 5 | Complete |
| VIS-03 | Phase 5 | Complete |
| VIS-04 | Phase 5 | Pending |
| VIS-05 | Phase 5 | Complete |
| VIS-06 | Phase 5 | Complete |
| OBS-01 | Phase 5 | Complete |
| OBS-02 | Phase 5 | Pending |
| OBS-03 | Phase 5 | Complete |
| OBS-04 | Phase 5 | Complete |
| OBS-05 | Phase 5 | Pending |
| OBS-06 | Phase 5 | Pending |
| SPI-01 | Phase 6 | Pending |
| SPI-02 | Phase 6 | Pending |
| SPI-03 | Phase 6 | Pending |
| SPI-04 | Phase 6 | Pending |
| SPI-05 | Phase 6 | Pending |
| SPI-06 | Phase 6 | Pending |
| SPI-07 | Phase 6 | Pending |
| SPI-08 | Phase 6 | Pending |
| MCP-01 | Phase 1 | Pending |
| MCP-02 | Phase 1 | Complete |

**Coverage:**
- v1 requirements: 79 total (counting PERSIST-01..03 as 3 entries, durability hardening continues into Phase 6)
- Mapped to phases: 79
- Unmapped: 0

**Note on PERSIST:** PERSIST-01..03 are scoped to Phase 1 (baseline durable persistence + session structure + crash-resume scaffold). Phase 6 hardens the durability story (LangGraph PostgresSaver wrapper, full crash → resume from last verified step under load) but does not introduce new PERSIST-* requirements.

---
*Requirements defined: 2026-04-29*
*Last updated: 2026-04-29 — traceability filled by roadmapper (6 phases, 79/79 mapped)*
