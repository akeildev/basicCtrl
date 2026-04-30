# Roadmap: cua-maximalist

## Overview

Build a self-healing autonomous Mac CU framework as a Python overlay above a forked `trycua/cua` Swift driver. Bottom-up: foundation + state graph + push-event verifier come FIRST (push subs must exist before actions fire), then 5 racing translators with idempotency, then 5-branch recovery + cache write-back, then cognition + episodic learning, then visualizer + transparency, then private SPIs + durability hardening. Each phase ends with a demo-able capability. Six phases for standard granularity.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Foundation + State + Verifier** - Python overlay, state graph, push-event verifier, deterministic L0+L1, durable persistence baseline, MCP surface preserved
- [ ] **Phase 2: Translators + Racing** - 5 protocol translators (T1-T5) and 5 racing channels (C1-C5) with atomic idempotency tokens, decided by Phase 1 verifier
- [ ] **Phase 3: Recovery + Cache Write-Back** - 6-class failure classifier, 5-branch parallel recovery, circuit breaker, Stagehand-style cassette replay + heal write-back
- [ ] **Phase 4: Cognition + Learning + Episodic** - Multi-agent ensemble (Opus + GPT-5 + Apple FM), UI-TARS grounder, V-Droid verifier, world model, speculative read-only, CGEvent tap recorder, recipe synthesis, FAISS episodic memory
- [ ] **Phase 5: Visualizer + Full Transparency** - NSPanel ghost cursor, SwiftUI HUD, 60fps H.265 replay, 3D timeline, counterfactual replay, differential session compare
- [ ] **Phase 6: Private SPIs + Durability Hardening** - SkyLight, AX remote, ES, DTrace, DYLD inject, WebKit RemoteInspector, IMU reader, LangGraph PostgresSaver crash-resume

## Phase Details

### Phase 1: Foundation + State + Verifier
**Goal**: Python overlay can probe any Mac app, write a typed state graph, and verify a click via push events + cheap deterministic checks in <50ms — without touching the cua-driver Swift code.
**Depends on**: Nothing (first phase)
**Requirements**: CORE-01, CORE-02, CORE-03, STATE-01, STATE-02, STATE-03, VERIFY-01, VERIFY-02, VERIFY-03, VERIFY-04, VERIFY-05, VERIFY-06, VERIFY-07, PERSIST-01, PERSIST-02, PERSIST-03, MCP-01, MCP-02
**BLOCKER pitfalls mitigated**: P2 (AX rate-limit / cmux #2985), P3 (full recursive AX = 15-20s on Safari), P14 (AX notifs fail on web/Electron), P24 (TCC revoked mid-session), P25 (modal alert blocks AX), P28 (stale notification races verifier)
**Success Criteria** (what must be TRUE):
  1. Click in Calculator fires `kAXValueChanged` and is recorded as VERIFIED in <50ms via L0 push subscription (subscribed BEFORE action fires)
  2. State graph round-trips: probe Calculator → write `UIElement` entity → read it back with stable composite key (role_path + label + bbox_centroid), not raw AXUIElement ref
  3. AppProfile classifier caches per-bundle capability probe (AX-rich? .sdef? CDP-port?) and survives session restart
  4. L0 push + L1 cheap diff (CGWindowList, NSPasteboard.changeCount, dHash) verifies a click in <50ms with no AX subtree walk
  5. AX rate-limiter caps at 20 calls/sec/pid; depth-limited subtree (3 levels max) prevents Safari hangs
  6. Existing trycua MCP server surface still works; healing wrapper exposed as additional MCP tools so Claude Code / Cursor / Codex can invoke it
**Plans**: 9 plans
- [x] 01-01-PLAN.md — Project scaffold + Pydantic state-graph contracts (UIElement, ActionCanonical, HoarePre/Post, EdgeKind, StateGraph, TemporalRingBuffer, CausalDAG)
- [x] 01-02-PLAN.md — AppProfile classifier with parallel capability probe + per-bundle disk cache + TCC monitor
- [x] 01-03-PLAN.md — AX safety primitives: TokenBucket rate limiter, depth-limited walker, modal probe, typed AX errors
- [x] 01-04-PLAN.md — AXObserver bridge (CFRunLoop thread + asyncio Queue) + AXObserverManager.expect (subscribe-before-fire) + NSWorkspace + kqueue
- [x] 01-05-PLAN.md — L0 push + L1 cheap-diff (CGWindowList + NSPasteboard.changeCount + ImageHash dHash) + WeightedVote + Aggregator
- [x] 01-06-PLAN.md — L2 medium tier (ocrmac + walker delegation) + L3 LLM stub + escalation ladder wiring
- [x] 01-07-PLAN.md — Persistence: SessionWriter ~/.cua/sessions/<id>/ tree + LangGraph PostgresSaver wrapper + crash-resume contract
- [ ] 01-08-PLAN.md — Python MCP server proxying cua-driver mcp via stdio + click_with_healing tool
- [ ] 01-09-PLAN.md — Calculator click <50ms end-to-end demo + 6 ROADMAP success criteria pytest gate + PHASE-1-DEMO.md runbook

### Phase 2: Translators + Racing
**Goal**: Drive any of trycua's covered apps via the BEST translator for that bundle, racing 5 channels in parallel with atomic idempotency — no double-clicks, no double-submits, ever.
**Depends on**: Phase 1 (verifier decides race winners; state graph receives writes from all translators)
**Requirements**: TRANS-01, TRANS-02, TRANS-03, TRANS-04, TRANS-05, ACT-01, ACT-02, ACT-03, ACT-04
**BLOCKER pitfalls mitigated**: P1 (action interference / double-clicks on race), P5 (AppleScript stale-state lag), P8 (Electron `--remote-debugging-port` launch-only), P12 (Tahoe SCScreenshotManager regression #870), P16 (Bear/Things SQLite schema drift)
**Research flags**: T4 Vision/Screen2AX integration (MacPaw Screen2AX + uitag SoM are 2025/2026, sparse docs)
**Success Criteria** (what must be TRUE):
  1. Click on Slack message: T2 CDP wins the race; T1/T3/T4/T5 channels cancelled cleanly with no second-fire
  2. Click on Pages toolbar: T3 AppleScript wins (in own thread pool, staggered 500ms after T1/T2/T5 to prevent loop-blocking)
  3. Click on game canvas (non-AX app): T4 Vision/Screen2AX + uitag SoM grounds; T5 CGEvent fires
  4. Zero double-clicks across 100 racing fires — atomic idempotency token written BEFORE any channel fires; destructive actions (submit/send/delete) use single-channel delivery, not race
  5. Per-app translator priority list matches association map for top 12 apps; classifier never silently relaunches Electron apps to enable CDP
**Plans**: TBD

### Phase 3: Recovery + Cache Write-Back
**Goal**: When verification fails, the system never silently drops. It classifies the failure, fans out 5 recovery branches in parallel, takes the first-verified result, and writes healed selectors back to the cassette — with every heal logged as an event.
**Depends on**: Phase 2 (recovery branches re-fire via translators + channels; write-back needs verified heal path)
**Requirements**: HEAL-01, HEAL-02, HEAL-03, HEAL-04, HEAL-05, CACHE-01, CACHE-02, CACHE-03
**BLOCKER pitfalls mitigated**: P20 (self-healing masks regressions / 41% abandonment — heal-event emission + rate budget), P23 (cassette write-back loop — stable-locator gate + atomic replace), P26 (5-branch recovery cost explosion — bounded cycles), P27 (non-determinism baseline)
**Success Criteria** (what must be TRUE):
  1. Inject a stale selector: cassette replay runs until break → live re-execute via 5-branch fanout → first-verified branch wins → semantic-diff write-back updates cache atomically (not append)
  2. All 6 failure classes (Perceptual / Cognitive / Actuation / Environmental / Resource / Loop) route to correct recovery branch in unit tests
  3. Circuit breaker trips after 3 consecutive same-target failures; emits structured event; switches primary translator for that bundle for 60s
  4. Bounded recovery: max 2 cycles → escalate to user with actionable message (never silent abandon)
  5. Every heal emits `HealEvent{old_locator, new_locator, reason, trace_id, ts}` to `~/.cua/sessions/<id>/heals.ndjson`; heal-rate budget pauses auto-heal at >5%/session
  6. Coordinate-based or vision-based heals are session-only — only stable-tier locators (AXIdentifier, AXLabel, AXTitle) write back to canonical cassette
**Plans**: TBD

### Phase 4: Cognition + Learning + Episodic
**Goal**: Plan with multiple agents in parallel, predict ahead read-only, learn from observed user actions via CGEvent tap, and retrieve "last time we did this" from episodic memory before any LLM call.
**Depends on**: Phase 3 (cognition + learning produce/consume episodic memory together; recovery uses Critic from cognition)
**Requirements**: STATE-04, COG-01, COG-02, COG-03, COG-04, COG-05, COG-06, COG-07, COG-08, LEARN-01, LEARN-02, LEARN-03, LEARN-04, LEARN-05
**BLOCKER pitfalls mitigated**: P4 (UI-TARS coord quantization → screen center — uitag primary + sanity gate), P6 (Apple FM 50% hallucinated params — binary classifier ONLY, hard-validate enum), P7 (Apple FM text-only public API — never feed pixels), P21 (intrinsic LLM self-correction broken — Critic ranks oracles, never self-critiques), P22 (speculation mutating state — speculation is READ-ONLY, type-system gate)
**Research flags**: UI-TARS-1.5 + ShowUI-2B fallback (mlx-vlm #330 mitigation), Recipe JSON schema (borrow from ghost-os, project-specific)
**Success Criteria** (what must be TRUE):
  1. 3-model ensemble (Opus + GPT-5 + Apple FM) votes on action selection; agrees on >80% of routine clicks; tiebreaker rule defined; Apple FM hard-gated to small-enum classification only
  2. Speculative pre-execution predicts steps N+1, N+2 in parallel with N's verifier — type-system enforces READ-ONLY; mutation gate blocks any MUTATE action until N is VERIFIED; hit rate ≥20%
  3. CGEvent tap (.listenOnly) on background Swift thread records user actions; CFRunLoopTimer (0.5s) coalesces keystrokes into 1 typeText per word; auto re-enables on tapDisabledByTimeout
  4. Recording 5min of work produces a valid Recipe JSON (params + preconditions + steps + per-step on_failure)
  5. Episodic memory (FAISS local, keyed by `(app, task_class, state_fingerprint)`) surfaces a matching recipe before the planner makes any LLM call
  6. UI-TARS sanity gate rejects any output landing within ±10px of screen center; uitag SoM is primary grounder; differential grounding (IoU >0.5) on disagreement
**Plans**: TBD

### Phase 5: Visualizer + Full Transparency
**Goal**: Make the agent fully transparent. Ghost cursor + element box + HUD show every action live; 60fps H.265 replay reconstructs full state at every step; 3D timeline + counterfactual replay surface what happened and what could have happened.
**Depends on**: Phase 4 (only worth visualizing once we have real data, recordings, and ensemble decisions to replay)
**Requirements**: VIS-01, VIS-02, VIS-03, VIS-04, VIS-05, VIS-06, OBS-01, OBS-02, OBS-03, OBS-04, OBS-05, OBS-06
**BLOCKER pitfalls mitigated**: P9 (ScreenCaptureKit captures own overlay — `SCContentFilter(excludingWindows:)`), P10 (macOS 15+ `sharingType=.none` no longer works — SCContentFilter is primary), P11 (WindowServer CPU spike with transparent NSWindow — single CAShapeLayer per element, hide during verify windows)
**Success Criteria** (what must be TRUE):
  1. Ghost cursor lerps to next click target visibly BEFORE the action fires; click ripple draws on landing; uses NSView.draw not CALayer (WindowServer perf bug)
  2. SwiftUI HUD with .ultraThinMaterial shows last 8 actions with tier badges (T1-T5 / C1-C5); Cmd+Shift+V hotkey toggles overlay; opacity slider + position snap
  3. SCContentFilter excludes overlay window IDs from verifier captures — pHash diff and OCR don't see the ghost cursor or HUD; tested macOS 15+ Tahoe
  4. Replay any past session reconstructs full StateNode at every step from `~/.cua/sessions/<id>/action_log.ndjson` + 60fps H.265 video
  5. 3D timeline (X=time, Y=app/window, Z=action depth) renders all session actions; counterfactual replay generates "what if branch B had won?" alternate timeline
  6. Differential session compare surfaces heal-events between session N and N+1 (same UX as `git diff` for runs)
**Plans**: TBD
**UI hint**: yes

### Phase 6: Private SPIs + Durability Hardening
**Goal**: Unlock maximum-power Mac control via private SPIs (SkyLight, AX remote, ES, DTrace, DYLD, WebKit, IMU) with public-API fallbacks for every channel; harden durable execution so kill -9 mid-task resumes from the last verified step.
**Depends on**: Phase 5 (SPIs unlock channels translators route to; durability wraps existing translator calls — only useful once translators are stable; observability shows SPI degradation gracefully)
**Requirements**: SPI-01, SPI-02, SPI-03, SPI-04, SPI-05, SPI-06, SPI-07, SPI-08
**BLOCKER pitfalls mitigated**: P17 (SkyLight breaks across macOS updates — capability probe + version-pinned signatures + public-API fallback), P18 (SIP-off requirements limit caps — tier SPIs by SIP requirement, graceful degradation), P19 (arm64e DYLD signing on Apple Silicon — build inject libs as arm64e + ad-hoc-signed with PAC), P29 (Cowork ships cross-session sync — full-stack differentiation moat)
**Research flags**: DYLD injection on arm64e (PAC + signing fragile, needs spike), AppleSPUHIDDevice IMU (SPIKE — undocumented, may not exist on M-series)
**Success Criteria** (what must be TRUE):
  1. SkyLight `SLEventPostToPid` Swift bridge fires background events with NO cursor warp; capability probe at session start; falls back to public CGEvent.postToPid if unavailable
  2. `_AXObserverAddNotificationAndCheckRemote` keeps Slack/Discord/VS Code AX trees alive when occluded — Slack background automation works
  3. Endpoint Security `es_new_client` observes kernel-level fork/exec/file events; DTrace probes inspect app internals (SIP-off OK locally); both gracefully unavailable on default machines
  4. DYLD_INSERT_LIBRARIES + Mach injection into Electron renderers works on arm64e (PAC-aware, ad-hoc signed); WebKit RemoteInspector private headers give Safari deep access
  5. AppleSPUHIDDevice IMU reader returns lid-angle / motion / vibration data (or cleanly reports unavailable on hardware that lacks it — SPIKE outcome documented)
  6. LangGraph PostgresSaver wraps every translator call as durable step; kill -9 mid-task → `persist/resume.py` picks up at last verified action with full state graph restored from snapshot
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation + State + Verifier | 0/9 | Not started | - |
| 2. Translators + Racing | 0/TBD | Not started | - |
| 3. Recovery + Cache Write-Back | 0/TBD | Not started | - |
| 4. Cognition + Learning + Episodic | 0/TBD | Not started | - |
| 5. Visualizer + Full Transparency | 0/TBD | Not started | - |
| 6. Private SPIs + Durability Hardening | 0/TBD | Not started | - |
