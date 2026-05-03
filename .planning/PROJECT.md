# basicCtrl — Self-Healing Autonomous Mac CU Framework

## What This Is

A maximalist, self-healing, autonomous computer-use framework for macOS. Built as a Python overlay above `trycua/cua`'s Swift driver with full private-SPI access (SkyLight, Endpoint Security, DYLD injection). Drives any Mac app — native Cocoa, Electron, browser, Canvas, terminal, game — by automatically picking the right protocol per app, racing multiple action channels in parallel, verifying with deterministic ensembles before falling back to LLMs, and recovering from any failure via 5-branch parallel recovery. Local-only and experimental — no production, security, or App Store constraints.

For Akeil personally: maximum-power Mac control, fully transparent (ghost cursor + HUD + 60fps replay), continuously self-improving via CGEvent recording → recipe synthesis → episodic memory.

## Core Value

**Autonomous control of any app on any Mac surface, with deterministic self-healing and full transparency — never silently fails, never gives up, never makes the user babysit.**

When everything else fails, the system picks the next translator, races recovery branches, replays from cassette, or asks the user. It never silently drops a task.

## Requirements

### Validated

(None yet — ship to validate)

### Active

**Foundation**
- [ ] **CORE-01**: Fork `trycua/cua` to `~/dev/basicCtrl/` with Python overlay scaffold above `libs/cua-driver/`
- [ ] **CORE-02**: Hook into `ToolRegistry.swift:55-97` post-action callback to emit structured events to Python overlay
- [ ] **CORE-03**: Initialize app classifier — `bundleID → AppProfile` with capability probe (AX-rich? .sdef? CDP-port? Tauri/Wails?), cached per-bundle per-session

**Unified state model (the State Bridge)**
- [ ] **STATE-01**: Typed-graph state model: `UIElement{id, role, label, value, bbox, capabilities, confidence, source[], visual_embedding, ocr_text, history[t-5..t-1], caused_by, causes[], episodic_ref}`
- [ ] **STATE-02**: Causal DAG of action → state delta
- [ ] **STATE-03**: Temporal ring buffer (last 5 frames)
- [ ] **STATE-04**: Episodic memory — FAISS vector store keyed by `(app, task_class, state_fingerprint)`

**Protocol translators (5, ordered by information density)**
- [ ] **TRANS-01**: T1 AX SPI translator — bidirectional read/write via AXUIElement + private `_AXUIElementGetWindow` + `_AXObserverAddNotificationAndCheckRemote`
- [ ] **TRANS-02**: T2 CDP translator — auto-relaunch Electron apps with `--remote-debugging-port`, attach via WebSocket, full DOM/JS/network access
- [ ] **TRANS-03**: T3 AppleScript translator — NSAppleScript in-process, ScriptingBridge typed access for apps with .sdef
- [ ] **TRANS-04**: T4 Vision/Screen2AX translator — Vision OCR + MacPaw Screen2AX synthetic tree + uitag SoM (Apple Vision + YOLO11 MLX) for non-AX apps
- [ ] **TRANS-05**: T5 Pixel translator — CGEvent + SkyLight `SLEventPostToPid` (background, no cursor warp) for total fallback

**Racing action delivery**
- [ ] **ACT-01**: Action channel registry — C1 SLEventPostToPid, C2 AX kAXPress, C3 CGEvent.postToPid, C4 AppleScript, C5 CDP Input.dispatch
- [ ] **ACT-02**: Race orchestrator — `asyncio.wait(FIRST_COMPLETED)` across channels, cancel losers when first verifier passes
- [ ] **ACT-03**: Atomic idempotency tokens — written to shared state before fire, channels skip if already claimed
- [ ] **ACT-04**: Action interference mitigations — staggered_race for AppleScript, AX rate-limit (cmux #2985 fix), pre-action AX validity check

**Push-event verifier (the secret weapon)**
- [ ] **VERIFY-01**: AXObserver subscription manager — subscribe to kAXValueChanged / kAXFocusedUIElementChanged / kAXWindowCreated / kAXTitleChanged / kAXLayoutChanged / kAXSelectedTextChanged / kAXSelectedRowsChanged BEFORE action fires
- [ ] **VERIFY-02**: NSWorkspace + DistributedNotificationCenter + CDP DOM mutation + kqueue EVFILT_PROC subscriptions
- [ ] **VERIFY-03**: Event aggregator with weighted vote per action class

**Deterministic ensemble verifier (4 layers)**
- [ ] **VERIFY-04**: L0 push events (0ms, already subscribed) — primary signal
- [ ] **VERIFY-05**: L1 cheap diff (1-5ms) — CGWindowList diff, NSPasteboard.changeCount, pixel ROI dHash
- [ ] **VERIFY-06**: L2 medium (50-200ms) — Vision OCR text diff (ROI), AX depth-limited subtree (3 levels MAX, never full recursive)
- [ ] **VERIFY-07**: L3 LLM fallback (300-800ms) — only when ensemble confidence < 0.30

**Failure classifier + active recovery**
- [ ] **HEAL-01**: 6-class typed failure enum — Perceptual / Cognitive / Actuation / Environmental / Resource / Loop
- [ ] **HEAL-02**: 5-branch parallel recovery — re-scroll+AX, OCR regrounding+CGEvent, world-model replan, planner replan, AppleScript fallback
- [ ] **HEAL-03**: First-verified branch wins, others cancelled, failed branches → RL training buffer
- [ ] **HEAL-04**: Bounded recovery — max 2 cycles then escalate to user
- [ ] **HEAL-05**: Circuit breaker after 3 consecutive failures on same target

**Cache self-heal write-back (Stagehand pattern)**
- [ ] **CACHE-01**: AgentCache port — SHA-256 keyed by `(bundleID, role_path, instruction)`
- [ ] **CACHE-02**: Cassette replay — replay until broken step, live re-execute, semantic diff write-back of healed selectors
- [ ] **CACHE-03**: Stream wrapping for transparent caching of streaming results

**Continuous learning**
- [ ] **LEARN-01**: CGEvent tap (.listenOnly) on background thread (ghost-os pattern, LearningRecorder.swift:62-88)
- [ ] **LEARN-02**: Keystroke coalescing via CFRunLoopTimer (0.5s) — 1 typeText per word
- [ ] **LEARN-03**: Auto re-enable on tapDisabledByTimeout
- [ ] **LEARN-04**: Recording → ObservedAction → Recipe JSON synthesis (params + preconditions + steps + per-step on_failure)
- [ ] **LEARN-05**: Episodic memory retrieval — "last time we did this" lookup before planning

**Cognitive layer (parallel multi-agent)**
- [ ] **COG-01**: Planner agent (Claude Opus class) with bounded plan generation
- [ ] **COG-02**: Grounder (UI-TARS-1.5-7B MLX local) running in parallel with planner
- [ ] **COG-03**: Verifier-LLM (V-Droid prefill-only, prefix-cached, 0.7s/step batch)
- [ ] **COG-04**: World-model predictor (CUWM-style — predicts post-state before action)
- [ ] **COG-05**: Apple FoundationModels tier-0 classifier — local 3B for routing decisions (binary/small-enum only; 4096 ctx limit)
- [ ] **COG-06**: Critic / recovery arbiter
- [ ] **COG-07**: Speculative pre-execution — draft model predicts steps N+1, N+2 in parallel with N's verifier (Skyvern agent.py:4337 pattern)
- [ ] **COG-08**: Ensemble vote on action selection (Opus + GPT-5 + Apple FM, majority + tiebreaker)

**Persistence + durable execution**
- [ ] **PERSIST-01**: Each translator call wrapped as durable step (Inngest or LangGraph PostgresSaver)
- [ ] **PERSIST-02**: `~/.cua/sessions/<id>/` structure — snapshot.json, action_log.ndjson, checkpoints/, recipes/, cassettes/, recordings/
- [ ] **PERSIST-03**: Crash → resume from last verified step

**Visualizer + transparency**
- [ ] **VIS-01**: NSPanel transparent overlay (.borderless, .nonactivatingPanel, ignoresMouseEvents, .popUpMenu level, canJoinAllSpaces)
- [ ] **VIS-02**: Ghost cursor with NSView.draw + ease-in-out lerp + click ripple
- [ ] **VIS-03**: Element box highlight via kAXFrameAttribute, semi-transparent rectangle with label
- [ ] **VIS-04**: SwiftUI HUD with .ultraThinMaterial — last 8 actions, status icons, tier badges (T1-T5 / C1-C5)
- [ ] **VIS-05**: SCContentFilter excludes overlay from own captures
- [ ] **VIS-06**: Toggle/config — Cmd+Shift+V hotkey, opacity slider, position snap

**Full transparency (replay + counterfactual)**
- [ ] **OBS-01**: 60fps lossless H.265 screen recording per session via CoreMediaIO
- [ ] **OBS-02**: Per-step state snapshot logging (full StateNode at every step)
- [ ] **OBS-03**: 3D timeline visualization (X=time, Y=app/window, Z=action depth)
- [ ] **OBS-04**: Replay any past session with full state at every step
- [ ] **OBS-05**: Counterfactual replay — "what if branch B had won?"
- [ ] **OBS-06**: Differential session compare

**Private SPI integration (no production constraints)**
- [ ] **SPI-01**: SkyLight `SLEventPostToPid` Swift bridge — background events, no cursor warp
- [ ] **SPI-02**: `_AXObserverAddNotificationAndCheckRemote` — Electron AX trees stay alive when occluded
- [ ] **SPI-03**: `CGSManagedDisplaySetCurrentSpace` — cross-Space window control
- [ ] **SPI-04**: Endpoint Security `es_new_client` — kernel-level fork/exec/file-event observation
- [ ] **SPI-05**: DTrace probes for app internals (SIP off OK locally)
- [ ] **SPI-06**: DYLD_INSERT_LIBRARIES + Mach injection into Electron renderers (SIP off)
- [ ] **SPI-07**: WebKit RemoteInspector private headers for Safari deep access
- [ ] **SPI-08**: AppleSPUHIDDevice IMU reader (undocumented MEMS sensor, lid-angle / motion / vibration)

**MCP server interface**
- [ ] **MCP-01**: Maintain trycua/cua's existing MCP server surface (the Python overlay extends, doesn't replace)
- [ ] **MCP-02**: Expose self-healing wrapper as MCP tools so Claude Code / Cursor / Codex can invoke it

### Out of Scope

- **Production-grade security / safety guards** — local-only experimental; we trust ourselves
- **App Store distribution / sandboxing** — uses private SPIs, no production code-signing path
- **Cross-platform (Windows / Linux)** — Mac-only by design
- **Multi-user / cloud-hosted** — Akeil's machine only
- **Headless server operation** — needs a real desktop, GUI, and active session
- **Microsoft Teams / new Outlook** — these are native AppKit (not Electron), so we use the AX path; no special integration
- **Game engine accessibility plugins** — out of scope; games fall through to T4 SoM + T5 pixel
- **Pre-action LLM verification** — production research says wasted latency for marginal gain; we run post-action only, with deterministic ensemble FIRST
- **Intrinsic LLM self-correction** — papers 2601.00828 and 2412.14959 show 16-27% accuracy and cognitive wavering; we use external oracles only
- **Full recursive AX tree diff** — 15-20s on Safari (confirmed); always use depth-limited (3 levels)
- **VLM-pixel-only as primary path** — 5-25% OSWorld success rate (UI-TARS-1.5 verified); fallback only

## Context

### Why this exists
- Anthropic Cowork ships at ~50% reliability on complex tasks (MacStories 12-task test, March 2026)
- Cowork crashes lose session data (issue #49498); no auto-recovery
- Apple Intelligence agentic Siri is delayed to iOS 26.5 / 27 (Bloomberg, Federighi confirmed)
- OpenAI Codex Mac CU is 2 weeks old (April 16, 2026), unverified at scale
- `trycua/cua` is the right Mac driver foundation (15.2k★ MIT, ~21k LOC Swift) but has zero retry/recovery built in
- No shipping system today combines: self-healing recovery + cross-session durability + headless-first execution + agent-agnostic composition

### What we build on
- `trycua/cua` — forked, Swift driver reused untouched (~21k LOC)
- `browser-harness` (Akeil already uses daily) — provides T2 CDP for Chrome family
- `MacPaw/Screen2AX` — synthetic AX tree from screenshots (77% F1, beats OmniParser-v2)
- `swaylenhayes/uitag` — Apple Vision + YOLO11 MLX SoM (90.8% coverage)
- `apple/python-apple-fm-sdk` — on-device 3B FoundationModel
- Code patterns from: Stagehand (cache write-back), Skyvern (parallel verify + speculative), magentic-ui (JSON retry), ghost-os (CGEvent tap recording, recipe JSON)

### Research artifacts (vault)
- `~/thinker/vault/research/computer-use-alternatives-2026-04-29.md` — landscape
- `~/thinker/vault/research/self-healing-cua-driver-2026-04-29.md` — initial cua-driver injection plan
- `~/thinker/vault/research/cua-autonomous-self-healing-framework-2026-04-29.md` — 8-driver registry v1
- `~/thinker/vault/research/basicCtrl-self-healing-framework-2026-04-29.md` — **THE locked maximalist architecture (this project's blueprint)**

### Local clones (reference)
- `~/thinker/research-clones/trycua-cua/` — Swift driver to fork
- `~/thinker/research-clones/browser-harness/` — Python harness reference
- `~/thinker/research-clones/skyvern/` — parallel verify + failure taxonomy patterns
- `~/thinker/research-clones/stagehand/` — cache self-heal write-back patterns
- `~/thinker/research-clones/magentic-ui/` — JSON retry + n_replans patterns
- `~/thinker/research-clones/ghost-os/` — CGEvent tap + recipe JSON patterns

## Constraints

- **Platform**: macOS 26+ (Tahoe), Apple Silicon only — depends on FoundationModels framework + ANE-accelerated Vision + Apple's MLX
- **Trust model**: local-only, single-user (Akeil's Mac), full TCC grant (Accessibility, Screen Recording, Input Monitoring, Automation per-app)
- **SIP**: partial-off acceptable for DTrace + DYLD injection paths (these are optional/private-SPI tier)
- **Distribution**: never to App Store; never beyond Akeil's machine
- **Languages**: Python (overlay primary, ~1500-2500 LOC) + minimal Swift glue (Visualizer + SkyLight bridges, ~300 LOC)
- **Compatibility**: must continue to work alongside browser-harness (Akeil uses it daily)
- **Cost**: 5-branch recovery + ensemble LLM voting are expensive at Opus pricing — fine locally, never run in tight loops without bounded retries
- **macOS version risk**: Apple may close private SPIs in macOS 27+; drivers must degrade gracefully (registry skips unavailable channels)

## Key Decisions

| Decision | Rationale | Outcome |
|---|---|---|
| Fork `trycua/cua`, build Python overlay above ToolRegistry hooks | trycua's 21k Swift LOC is the right driver; rewriting in Swift would be 6 weeks of churn for no benefit; ToolRegistry.swift:55-97 + cua-agent's `_on_api_end` callbacks are perfect intercept points | — Pending |
| 1 meta-driver + 4-5 strategy translators, NOT 8 separate driver classes | Production evidence (LangGraph, Linux kernel, Selenium, trycua's own pattern): single driver with internal capability-routed strategy beats N driver classes | — Pending |
| LLM is the classifier (no separate classifier module) | Every production system found (LangGraph ToolNode, Magentic-One, MCP) lets the LLM pick from capability-probed shortlist; pre-classifier adds latency for nothing | — Pending |
| Push-event subscription as primary verifier | AXObserverAddNotification fires <1ms via Mach port, no before/after snapshot needed; deterministic; production systems all miss this | — Pending |
| Deterministic ensemble FIRST, LLM verification only on disagreement | Papers 2601.00828 + 2412.14959 prove intrinsic LLM self-correction is 16-27% accurate (worse with stronger models); deterministic checks (AX diff, OCR, pixel hash) cost 1-50ms vs 300-800ms for LLM | — Pending |
| Race translators in parallel with idempotency tokens | First verified channel wins; cancel losers; atomic pre-action ID prevents double-apply; AX wins standard ~50ms / CGEvent wins canvas <1ms / AppleScript fallback (slow but catches legacy) | — Pending |
| Apple FM (macOS 26 on-device 3B) for tier-0 classification only | Free, local, ~50-200ms/token, but 50% hallucinated params on complex schemas; safe for binary/small-enum decisions only | — Pending |
| Use ALL private SPIs (SkyLight, ES, DTrace, DYLD) | No production constraints; SkyLight is what trycua already uses; ES + DTrace + DYLD unlock kernel/Electron-renderer power for free; degrade gracefully if Apple closes them | — Pending |
| Stagehand-style cache self-heal write-back | Cache that updates itself on selector drift is qualitatively different from one that goes stale; AgentCache.ts:573-624 is the proven pattern | — Pending |
| Recipe JSON format (ghost-os pattern) for "teach by demo" | params + preconditions + steps + per-step on_failure schema is the right artifact for episodic memory + replay | — Pending |
| Visualizer in v2, not Sprint 0 | Failure logs come first; we need real recordings before we know what's worth visualizing; no shipping CU system has good telemetry yet | — Pending |
| Skip pre-action verification (post-action only) | No production system uses pre-action verify; adds 200-500ms per step; cost > benefit | — Pending |
| Durable execution wrapper (Inngest / LangGraph PostgresSaver) | Every serious 2026 agent uses it; replace hand-rolled checkpoints; crash → resume not restart | — Pending |
| Trace-replay (cassette → broken-step → live re-execute → re-record) | Selective healing > full retry; production library `traceops` validates the pattern | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-29 after initialization*
