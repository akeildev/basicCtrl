# Feature Research — basicCtrl

**Domain:** Self-healing autonomous Mac CU framework (local-experimental)
**Researched:** 2026-04-29
**Confidence:** HIGH (locked architecture + verified competitive landscape)

---

## Answer (1-line)

```
TABLE STAKES = 5 translators + push verifier + race + recover + persist
DIFFERENTIATORS = transparency + learning + private SPI + ensemble cognition
ANTI-FEATURES = production safety, sandboxing, cross-platform, intrinsic LLM self-correction
```

The locked architecture's 9 layers map cleanly onto this taxonomy. Every Active requirement in PROJECT.md slots into exactly one bucket.

---

## Feature Landscape

### Table Stakes — Must-Have or It's Not a Self-Healing CU Framework

What every "self-healing CU framework" needs to even claim the label. cua-driver baseline + browser-harness + Cowork all fail on at least one of these — that's why we exist.

| Feature | Req IDs | Why Table Stakes | Complexity | Phase Hint |
|---|---|---|---|---|
| Fork trycua/cua + Python overlay scaffold | CORE-01, CORE-02 | Without the driver foundation, nothing works | LOW | foundation |
| App classifier (bundleID → AppProfile + capability probe) | CORE-03 | Per-app translator routing is impossible without it | LOW | foundation |
| Typed-graph state model (UIElement nodes + edges) | STATE-01 | "Self-healing" means "different translator, same entity" — needs unified graph | MEDIUM | foundation |
| Causal DAG (action → state delta) | STATE-02 | Failure attribution requires causal links | MEDIUM | foundation |
| Temporal ring buffer (last 5 frames) | STATE-03 | State diffs need a "before" reference | LOW | foundation |
| T1 AX SPI translator | TRANS-01 | Default channel for ~80% of native Mac apps | MEDIUM | driver |
| T2 CDP translator (Electron + browser) | TRANS-02 | Slack/Discord/VSCode/Notion = half the desktop | MEDIUM | driver |
| T3 AppleScript translator | TRANS-03 | Mail/Calendar/Finder/Office have no other path | LOW | driver |
| T5 Pixel + CGEvent translator | TRANS-05 | Total fallback when nothing else works | LOW | driver |
| Action channel registry (C1-C5) | ACT-01 | Racing requires multiple channels | MEDIUM | driver |
| Race orchestrator (asyncio FIRST_COMPLETED + cancel losers) | ACT-02 | The differentiator vs sequential frameworks | MEDIUM | driver |
| Atomic idempotency tokens | ACT-03 | Without these, racing = double-click bugs | MEDIUM | driver |
| Action interference mitigations | ACT-04 | AppleScript blocks event loop, AX rate-limit (cmux #2985) | MEDIUM | driver |
| AXObserver subscription manager (push events) | VERIFY-01 | THE secret weapon — primary verifier <1ms via Mach port | MEDIUM | verifier |
| L0 push events as primary signal | VERIFY-04 | Already subscribed; 0ms latency; deterministic | LOW | verifier |
| L1 cheap diff (CGWindowList, Pasteboard, dHash) | VERIFY-05 | 1-5ms backup before falling to LLM | MEDIUM | verifier |
| L2 medium (OCR ROI, depth-limited AX subtree) | VERIFY-06 | NEVER full recursive (15-20s on Safari) | MEDIUM | verifier |
| L3 LLM fallback (only when ensemble < 0.30) | VERIFY-07 | Last-resort, NOT default | LOW | verifier |
| 6-class typed failure enum | HEAL-01 | Different failures need different recoveries | LOW | recovery |
| Bounded recovery (max 2 cycles → escalate) | HEAL-04 | Cowork crashes because it has no upper bound | LOW | recovery |
| Circuit breaker (3 consecutive failures on same target) | HEAL-05 | Stops loop traps deterministically | LOW | recovery |
| Durable execution wrapper (per translator call = 1 step) | PERSIST-01 | Crash → resume not restart (Cowork loses session data without this) | MEDIUM | foundation |
| Session directory layout (~/.cua/sessions/<id>/) | PERSIST-02 | Cassettes/recipes/recordings need a home | LOW | foundation |
| Crash → resume from last verified step | PERSIST-03 | The Cowork issue #49498 fix | MEDIUM | foundation |
| MCP server interface (preserve trycua surface) | MCP-01, MCP-02 | Claude Code / Cursor / Codex need to call us | LOW | SPI |

**Why these are non-negotiable:** strip any one → falls back to cua-driver baseline (no recovery) or Cowork (no durability). Table stakes = the floor for "self-healing".

---

### Differentiators — What Makes Us BETTER Than Cowork / Codex / cua-driver

These are the moat. Cowork has none of these. cua-driver has none. Codex Mac CU is too new to know. Stagehand has cache write-back but is browser-only. Skyvern has parallel verify but is web-only.

| Feature | Req IDs | Value Proposition | Complexity | Phase Hint |
|---|---|---|---|---|
| T4 Vision/Screen2AX translator (synthetic AX from pixels) | TRANS-04 | Reaches Canvas/Figma/games where AX returns nothing — 77% F1, beats OmniParser-v2 | HIGH | driver |
| Episodic memory (FAISS keyed by app+task+state_fp) | STATE-04 | "Last time we did this" lookup = qualitatively different from stateless agents | MEDIUM | learning |
| NSWorkspace + DistributedNotif + CDP DOM + kqueue subscriptions | VERIFY-02 | Multi-source push events (no other framework subscribes this widely) | MEDIUM | verifier |
| Event aggregator with weighted vote per action class | VERIFY-03 | Weighted ensemble > single-source verifier | MEDIUM | verifier |
| 5-branch parallel recovery | HEAL-02 | Skyvern has parallel verify but not parallel recovery; nothing else races recovery branches | HIGH | recovery |
| First-verified branch wins, others cancelled, failed → RL buffer | HEAL-03 | Continuous improvement signal from failures | MEDIUM | recovery |
| AgentCache port (Stagehand pattern, SHA-256 keyed) | CACHE-01 | Cache that updates itself on selector drift = qualitative difference | MEDIUM | learning |
| Cassette replay → broken-step → live re-execute → write-back | CACHE-02 | Selective healing > full retry; traceops-validated pattern | HIGH | learning |
| Stream wrapping for transparent streaming cache | CACHE-03 | Streaming results cache without caller awareness | MEDIUM | learning |
| CGEvent tap (.listenOnly) recorder (ghost-os pattern) | LEARN-01 | Continuous learning from human demos — Cowork has zero of this | MEDIUM | learning |
| Keystroke coalescing (CFRunLoopTimer 0.5s → typeText) | LEARN-02 | Word-level not char-level recordings | LOW | learning |
| Auto re-enable on tapDisabledByTimeout | LEARN-03 | Recorder survives macOS quirks without user babysit | LOW | learning |
| Recording → ObservedAction → Recipe JSON synthesis | LEARN-04 | "Teach by demo" with params + preconds + steps + on_failure | HIGH | learning |
| Episodic memory retrieval before planning | LEARN-05 | Plan from past success, not from blank slate | MEDIUM | learning |
| Planner agent (Claude Opus class, bounded plans) | COG-01 | Standard, but bounded plan generation matters | LOW | cognition |
| Grounder (UI-TARS-1.5-7B MLX) running parallel to planner | COG-02 | Parallel multi-agent vs sequential — Cowork is sequential | MEDIUM | cognition |
| Verifier-LLM (V-Droid prefill, prefix-cached, 0.7s/step batch) | COG-03 | Production-fast verifier; nothing else uses V-Droid pattern | MEDIUM | cognition |
| World-model predictor (CUWM-style post-state prediction) | COG-04 | Predict before action; recovery branch uses this | HIGH | cognition |
| Apple FoundationModels tier-0 classifier | COG-05 | Free, local, ~50ms; binary/small-enum routing | LOW | cognition |
| Critic / recovery arbiter | COG-06 | Picks among 5 recovery branches | MEDIUM | cognition |
| Speculative pre-execution (draft predicts N+1, N+2) | COG-07 | Skyvern pattern; 20-55% hit rate saves full Opus round-trip | HIGH | cognition |
| Ensemble vote on action selection (Opus + GPT-5 + Apple FM) | COG-08 | 3-model majority + tiebreaker; nothing else does this for Mac | MEDIUM | cognition |
| NSPanel transparent overlay (.popUpMenu, ignoresMouseEvents) | VIS-01 | Ghost overlay on top of everything, no input steal | MEDIUM | transparency |
| Ghost cursor (NSView.draw + ease-in-out lerp + click ripple) | VIS-02 | The "I see what it's doing" moment | LOW | transparency |
| Element box highlight via kAXFrameAttribute | VIS-03 | Real-time visual confirmation of which element is targeted | LOW | transparency |
| SwiftUI HUD (last 8 actions, status icons, T1-T5/C1-C5 badges) | VIS-04 | Tier visibility — see translator/channel choice live | MEDIUM | transparency |
| SCContentFilter excludes overlay from own captures | VIS-05 | Don't pollute screenshots/recordings with HUD | MEDIUM | transparency |
| Toggle/config (Cmd+Shift+V, opacity, position snap) | VIS-06 | User control over visualization | LOW | transparency |
| 60fps lossless H.265 screen recording per session | OBS-01 | Full session video for post-mortem; nobody else does 60fps lossless | MEDIUM | transparency |
| Per-step state snapshot logging (full StateNode) | OBS-02 | Replay any moment with full graph | LOW | transparency |
| 3D timeline visualization (X=time, Y=app, Z=action depth) | OBS-03 | Novel UX for multi-app multi-step debugging | HIGH | transparency |
| Replay any past session with full state at every step | OBS-04 | Time-travel debugging for agents | MEDIUM | transparency |
| Counterfactual replay ("what if branch B had won?") | OBS-05 | RL signal generator + debugging tool, unique | HIGH | transparency |
| Differential session compare | OBS-06 | Compare run A vs run B side-by-side | MEDIUM | transparency |
| SkyLight SLEventPostToPid Swift bridge | SPI-01 | Background events, no cursor warp — already in trycua | MEDIUM | SPI |
| _AXObserverAddNotificationAndCheckRemote | SPI-02 | Electron AX trees alive when occluded (Slack/Discord/VSCode background) | MEDIUM | SPI |
| CGSManagedDisplaySetCurrentSpace | SPI-03 | Cross-Space window control (yabai pattern) | MEDIUM | SPI |
| Endpoint Security es_new_client | SPI-04 | Kernel-level fork/exec/file-event observation | HIGH | SPI |
| DTrace probes for app internals | SPI-05 | Function-level tracing of any process (SIP off OK locally) | HIGH | SPI |
| DYLD_INSERT_LIBRARIES + Mach injection into Electron renderers | SPI-06 | Inside-process hooks (SIP off) | SPIKE | SPI |
| WebKit RemoteInspector private headers | SPI-07 | Full Safari internals, JS context, live DOM | HIGH | SPI |
| AppleSPUHIDDevice IMU reader | SPI-08 | Lid-angle / motion / vibration (zero entitlements) | SPIKE | SPI |

**Why these differentiate:** every one is something a competitor either *can't* do (private SPI), *won't* do (production constraints block injection), or *hasn't yet* done (3D timeline, counterfactual replay, parallel recovery). Maximalist means we ship all of them.

---

### Anti-Features — Things to DELIBERATELY NOT Build

The "Out of Scope" wall in PROJECT.md, expanded with reasoning. These look reasonable on the surface and would tank the project.

| Anti-Feature | Why It Looks Good | Why It's Wrong For Us | What We Do Instead |
|---|---|---|---|
| Production-grade security / safety guards | "Agents need guardrails" | Local single-user, we trust ourselves; guardrails kill private SPI access | Trust model: full TCC grant, SIP partial-off, no second-guessing |
| App Store distribution / sandboxing | "Wider reach, easier install" | Sandboxing forbids SkyLight, ES, DYLD injection — kills the framework | Local-only, manually-signed, never distributed |
| Cross-platform (Windows / Linux) | "Bigger market, more users" | Mac-only by design; UFO2 owns Win, Skyvern owns web | Mac-native maximalism beats cross-platform mediocrity |
| Multi-user / cloud-hosted | "SaaS market is real" | Akeil's machine only; cloud changes trust model and SPI access | Local-first, single-user, no auth layer |
| Headless server operation | "Run on remote boxes" | Needs real desktop, GUI, active session for AX/CGEvent/Vision | Always run on attended Mac with full UI |
| Microsoft Teams / new Outlook special path | "Common enterprise apps" | These are native AppKit (not Electron) — AX path already covers | T1 AX, no special integration |
| Game engine accessibility plugins | "Help games be controllable" | Games fall through to T4 SoM + T5 pixel by design | Accept lower reliability for games; don't build per-engine plugins |
| Pre-action LLM verification | "Verify before fire = safer" | Production research: 200-500ms wasted latency for marginal gain | Post-action only, deterministic ensemble FIRST |
| Intrinsic LLM self-correction | "LLM can fix its own mistakes" | Papers 2601.00828 + 2412.14959: 16-27% accuracy, cognitive wavering | External oracle verifiers (push events + deterministic ensemble) |
| Full recursive AX tree diff | "Catches every change" | 15-20s on Safari (confirmed); blocks app event loop | Depth-limited (3 levels MAX), push events as primary |
| VLM-pixel-only as primary path | "Vision models are getting good" | UI-TARS-1.5: 5-25% OSWorld success rate | T1-T3 first; T4 Vision only when no AX/CDP available |
| Full screenshot SSIM verification | "Pixel-perfect comparison" | False positives on cursor/tooltip/clock | ROI dHash + push events |
| AX element ID as identity | "Stable handle for elements" | React/SwiftUI re-renders break this | Role-path + bbox + fingerprint |
| AppleScript at high frequency | "Object-model is precise" | 50-200ms blocks app event loop | Use sparingly, staggered_race with 500ms delay |
| Heavy-poll AX (>30 req/sec) | "Stay synced with UI" | cmux #2985 — stalls target app | Cache hierarchy in 100ms windows + push events |
| Blind retry without idempotency | "Just try again" | Double-click risk on actuation success + verify failure | Atomic pre-action ID; channels skip if claimed |
| Silent self-heal | "User shouldn't see fixes" | Masks regressions; can't learn from invisible heals | Emit structured event for every heal |
| Unbounded retries | "Keep trying until success" | Cowork crashes here; infinite cost on Opus | Max 2 cycles → escalate to user |
| Hand-rolled checkpoint system | "Custom fits our needs" | Every 2026 agent uses durable execution; reinventing wastes weeks | Inngest / LangGraph PostgresSaver wrapper |
| OmniParser as primary SoM | "Microsoft has a SoM model" | 90% slower than Apple Vision + YOLO11 MLX (uitag), 77% F1 ties Screen2AX | Apple Vision + uitag YOLO11 + Screen2AX |
| GGUF UI-TARS deployment | "Standard llama.cpp path" | ByteDance pulled GGUFs — Qwen2-VL vision encoder doesn't serialize | MLX-only deployment for UI-TARS |
| Real-time streaming-everything | "Sub-100ms feels alive" | Latency theater; T3 AppleScript is 50-500ms intrinsically | Race for fastest, accept tier latency variance |

**Why these matter:** every CU framework that died (or will die) builds at least one of these. Anti-features document the "no" decisions so we don't relitigate them.

---

## Feature Dependencies

### Critical Dependency Chains

```
                                   ┌─────────────────────────────┐
                                   │   COG-08 ensemble vote      │
                                   └──────────────┬──────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   COG-01..07 cognition     │
                                   └──────────────┬──────────────┘
                                                  │
                                ┌─────────────────┴─────────────────┐
                                │   OBS-04 replay   OBS-05 counterf │
                                └─────────────────┬─────────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   OBS-01,02 record + log    │
                                   └──────────────┬──────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   VIS-01..06 visualizer     │
                                   └──────────────┬──────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   LEARN-04,05 recipes + mem │
                                   └──────────────┬──────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   LEARN-01,02,03 CGEvent tap│
                                   └──────────────┬──────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   CACHE-01,02,03 self-heal  │
                                   └──────────────┬──────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   HEAL-01..05 recovery      │
                                   └──────────────┬──────────────┘
                                                  │
                                   ┌──────────────┴──────────────┐
                                   │   ACT-01..04 race delivery  │
                                   └──────────────┬──────────────┘
                                                  │
                          ┌───────────────────────┴───────────────────────┐
                          │   VERIFY-01..07 push events + ensemble       │
                          └───────────────────────┬───────────────────────┘
                                                  │
                          ┌───────────────────────┴───────────────────────┐
                          │   TRANS-01..05 5 translators                 │
                          └───────────────────────┬───────────────────────┘
                                                  │
                          ┌───────────────────────┴───────────────────────┐
                          │   STATE-01..04 graph + DAG + ring + memory   │
                          └───────────────────────┬───────────────────────┘
                                                  │
                          ┌───────────────────────┴───────────────────────┐
                          │   CORE-01,02,03 fork + hook + classifier     │
                          └───────────────────────────────────────────────┘
                                                  │
                          ┌───────────────────────┴───────────────────────┐
                          │   PERSIST-01,02,03 durable execution         │
                          └───────────────────────────────────────────────┘
```

### Specific Dependency Notes

| Feature | Depends On | Why |
|---|---|---|
| ACT-02 race orchestrator | TRANS-01..05, ACT-01 | Need translators + channel registry to race them |
| ACT-03 idempotency tokens | STATE-01 | Token must be stored in shared state graph |
| VERIFY-01 AXObserver | TRANS-01 | AX subscription requires AX SPI access |
| VERIFY-04 push as primary | VERIFY-01, VERIFY-02 | Push signals must exist before they're "primary" |
| VERIFY-07 LLM fallback | VERIFY-04..06 | Only fires when ensemble L0-L2 disagree |
| HEAL-02 5-branch recovery | TRANS-01..05, ACT-01..04, VERIFY-01..07 | Branches use translators + verifiers |
| HEAL-03 first-verified wins | HEAL-02, VERIFY-01..07 | Need verifier to know which branch won |
| CACHE-01 AgentCache | CORE-03 (bundleID), STATE-01 (role_path) | Cache key needs app classifier + state graph |
| CACHE-02 cassette write-back | CACHE-01, HEAL-02 | Healed selectors come from recovery branches |
| LEARN-04 recipe synthesis | LEARN-01, LEARN-02, STATE-02 | Needs CGEvent stream + coalescing + causal DAG |
| LEARN-05 episodic retrieval | STATE-04, LEARN-04 | Vector store + recipe artifacts |
| COG-02 Grounder parallel | COG-01 | Runs concurrent with Planner, needs Planner running |
| COG-04 World-model | STATE-02, STATE-03 | Predict from causal DAG + temporal buffer |
| COG-07 Speculative | COG-04, COG-05 | Draft model + world-model predict N+1 |
| COG-08 Ensemble vote | COG-01, COG-05 | Need at least 2 models to vote |
| VIS-03 element highlight | TRANS-01 (kAXFrameAttribute) | AX frame attribute is what we draw |
| VIS-04 HUD with tier badges | ACT-01..02 | Need tier metadata from race orchestrator |
| OBS-02 per-step snapshot | STATE-01..03, PERSIST-02 | Snapshot what the state graph is + write to session dir |
| OBS-04 replay | OBS-01 + OBS-02 | Need video + per-step state |
| OBS-05 counterfactual | OBS-04, HEAL-03 | Need replay engine + recovery branch logs |
| MCP-02 self-healing wrappers | All TRANS, ACT, VERIFY, HEAL | MCP exposes the working framework |

### Feature Conflicts (Won't Combine in Same Phase)

| A | B | Why Conflict |
|---|---|---|
| LLM-only verification | Deterministic ensemble | Different verifier philosophies; we pick deterministic-first |
| Sequential planner→grounder | Parallel cognition (COG-01..07) | Architectural fork; we pick parallel |
| Single-channel actuation | Racing channels (ACT-01..04) | Defeats the racing pattern |
| Full recursive AX walk | Depth-limited AX (3 levels) | 15-20s vs <100ms; pick one |
| Pixel-only T5 path | T1-T4 priority routing | Pixel as primary = 5-25% OSWorld; demote to fallback |

---

## MVP Definition

### Launch With (v1) — Sprints 0-4 (~22 days)

The "is this even self-healing?" minimum.

- [ ] **CORE-01,02,03** — fork + ToolRegistry hook + app classifier
- [ ] **STATE-01,02,03** — typed graph + causal DAG + ring buffer (skip episodic memory STATE-04 for v1)
- [ ] **TRANS-01,02,03,05** — AX, CDP, AppleScript, Pixel (T4 Vision deferred to v1.x)
- [ ] **ACT-01,02,03,04** — full race orchestrator
- [ ] **VERIFY-01,02,03** — push event subscriptions + aggregator
- [ ] **VERIFY-04,05,06,07** — full L0→L3 ensemble
- [ ] **HEAL-01,04,05** — failure enum + bounded recovery + circuit breaker (skip HEAL-02,03 5-branch for v1)
- [ ] **PERSIST-01,02,03** — durable execution + session dirs + crash resume
- [ ] **MCP-01,02** — preserve trycua MCP surface

**Why this set:** ships the smallest thing that actually self-heals. Cowork crashes — we resume. cua-driver doesn't recover — we do. Without these, we're not a self-healing framework.

### Add After Validation (v1.x) — Sprints 5-8 (~20 days)

Once the racing+verifying loop is solid, add the moat.

- [ ] **TRANS-04** — Vision/Screen2AX (unlocks Canvas/Figma/games)
- [ ] **STATE-04** — episodic memory FAISS store
- [ ] **HEAL-02,03** — 5-branch parallel recovery + first-verified wins
- [ ] **CACHE-01,02,03** — Stagehand-style write-back
- [ ] **LEARN-01,02,03,04,05** — CGEvent recorder → recipes → episodic retrieval
- [ ] **COG-01..06** — full cognition layer (planner, grounder, verifier-LLM, world-model, Apple FM, critic)

**Trigger to add:** v1 is stable on 5-app smoke test (Slack + Safari + Notion + Mail + Finder).

### Future Consideration (v2+) — Sprints 9-11 (~13 days)

Polish, transparency, private SPI maximalism.

- [ ] **COG-07,08** — speculative pre-execution + ensemble vote
- [ ] **VIS-01..06** — full visualizer (ghost cursor + HUD + overlay)
- [ ] **OBS-01..06** — 60fps recording + per-step snapshots + 3D timeline + counterfactual replay
- [ ] **SPI-01..08** — all 8 private SPIs (some are SPIKE-tier risk)

**Why defer:** transparency only matters once the framework actually works. Private SPIs (especially DYLD injection, AppleSPUHIDDevice) carry breakage risk on macOS updates — ship after core is stable. Visualizer in v2 per Key Decisions table in PROJECT.md.

---

## Feature Prioritization Matrix

| Feature Group | User Value | Implementation Cost | Priority | Phase |
|---|---|---|---|---|
| Foundation (CORE-01..03, STATE-01..03, PERSIST-01..03) | HIGH | LOW-MED | P1 | foundation |
| 4 translators (TRANS-01,02,03,05) | HIGH | MED | P1 | driver |
| Racing delivery (ACT-01..04) | HIGH | MED | P1 | driver |
| Push verifier + ensemble (VERIFY-01..07) | HIGH | MED | P1 | verifier |
| Bounded recovery (HEAL-01,04,05) | HIGH | LOW | P1 | recovery |
| MCP interface (MCP-01,02) | HIGH | LOW | P1 | foundation |
| Vision translator (TRANS-04) | MED | HIGH | P2 | driver |
| 5-branch recovery (HEAL-02,03) | HIGH | HIGH | P2 | recovery |
| Cache write-back (CACHE-01..03) | HIGH | MED-HIGH | P2 | learning |
| Continuous learning (LEARN-01..05) | HIGH | MED-HIGH | P2 | learning |
| Cognition layer base (COG-01..06) | HIGH | MED-HIGH | P2 | cognition |
| Episodic memory (STATE-04) | MED | MED | P2 | learning |
| Speculative + ensemble vote (COG-07,08) | MED | HIGH | P3 | cognition |
| Visualizer (VIS-01..06) | MED | MED-HIGH | P3 | transparency |
| Recording + replay (OBS-01..06) | MED | HIGH-SPIKE | P3 | transparency |
| Private SPIs (SPI-01..08) | MED | HIGH-SPIKE | P3 | SPI |

**Priority key:**
- P1 = MVP (Sprints 0-4); without these, not self-healing
- P2 = Differentiator (Sprints 5-8); without these, baseline-equivalent
- P3 = Maximalist (Sprints 9-11); without these, less power but still works

---

## Competitor Feature Analysis

| Feature | Cowork (Anthropic) | cua-driver baseline | Codex Mac CU | Stagehand v3 | Skyvern 2.0 | **basicCtrl** |
|---|---|---|---|---|---|---|
| Mac native | yes | yes | yes (2 wks) | no (web) | no (web) | **yes** |
| Crash resume | no (issue #49498) | no | unknown | partial | partial | **yes (durable exec)** |
| Self-healing | no | no | unknown | yes (XPath) | yes (workflow) | **yes (5-branch)** |
| Push-event verifier | no | no | unknown | partial | no | **yes (AXObserver+more)** |
| Racing translators | no | no | unknown | no | no | **yes (5 channels)** |
| Cache write-back | no | no | unknown | yes | no | **yes (port from Stagehand)** |
| 60fps replay | no | no | unknown | no | no | **yes** |
| Counterfactual replay | no | no | unknown | no | no | **yes (unique)** |
| 3D timeline | no | no | unknown | no | no | **yes (unique)** |
| Private SPI maximalism | no (sandboxed) | partial (SkyLight) | unknown | n/a | n/a | **yes (8 SPIs)** |
| Continuous learning (CGEvent) | no | no | unknown | no | no | **yes (ghost-os pattern)** |
| Recipe JSON | no | no | unknown | no | no | **yes** |
| Episodic memory | no | no | unknown | no | no | **yes (FAISS)** |
| Parallel cognition | partial | no | unknown | no | partial | **yes (6+ agents)** |
| World-model predictor | no | no | unknown | no | no | **yes (CUWM-style)** |
| Speculative pre-exec | no | no | unknown | no | yes | **yes (Skyvern pattern)** |
| Ensemble LLM voting | no | no | unknown | no | no | **yes (Opus+GPT-5+FM)** |
| MCP server | no | yes | unknown | yes | no | **yes (preserve+extend)** |
| OSWorld reliability | ~50% (12-task) | unknown | unknown | n/a (browser) | n/a (browser) | **target: ≥75%** |
| Loses session on crash | yes | yes | unknown | partial | no | **no** |

**Honest gaps where competitors win:**
- Cowork: Anthropic-trained model alignment (we use the same Opus, but don't train)
- Stagehand: deeper browser-only optimization than our T2 CDP path
- Skyvern: web workflow patterns (195k LOC) we don't replicate

---

## Phase Mapping Hint (for Roadmap)

```
Phase 1: foundation     → CORE-01..03, STATE-01..03, PERSIST-01..03, MCP-01,02
Phase 2: verifier       → VERIFY-01..07
Phase 3: driver         → TRANS-01,02,03,04,05, ACT-01..04
Phase 4: recovery       → HEAL-01..05
Phase 5: learning       → CACHE-01..03, LEARN-01..05, STATE-04
Phase 6: transparency   → VIS-01..06, OBS-01..06
Phase 7: SPI            → SPI-01..08
Phase 8: cognition      → COG-01..08
```

**Why this ordering:**
1. **foundation FIRST** — everything depends on the state graph + persistence layer
2. **verifier BEFORE driver** — push subscriptions must exist before actions fire (subscribe-before-fire is non-negotiable)
3. **driver depends on verifier** — racing requires verifier to declare a winner
4. **recovery depends on driver** — recovery branches use translators + channels
5. **learning AFTER recovery** — cache write-back needs healed selectors from recovery
6. **transparency LATE** — only worth visualizing once we have real data (Key Decisions row)
7. **SPI before cognition** — private SPIs unlock channels that cognition layer routes to
8. **cognition LAST** — runs above the entire stack; speculative pre-exec needs world-model + everything below

**Alternative ordering considered:** cognition early (matches L1 layer position). Rejected because: cognition without driver = nothing to plan against. The 9-layer architecture is *runtime* topology, not *build* order.

---

## Complexity Tag Summary

| Complexity | Count | Examples |
|---|---|---|
| LOW | 23 | bundleID classifier, ring buffer, AppleScript translator, failure enum, circuit breaker, ghost cursor draw |
| MEDIUM | 36 | typed graph, AX translator, CDP translator, race orchestrator, AXObserver, cache port, planner agent |
| HIGH | 13 | T4 Vision/Screen2AX, 5-branch recovery, recipe synthesis, world-model, speculative pre-exec, 3D timeline, counterfactual replay, ES client, DTrace, WebKit RemoteInspector |
| SPIKE | 3 | DYLD_INSERT_LIBRARIES + Mach injection, AppleSPUHIDDevice IMU, OBS-05 counterfactual replay engine end-to-end |

**SPIKE definition:** uncertain enough to need a 1-2 day exploration before committing to a sprint slot. These are the "hardest" items.

---

## Coverage Check Against PROJECT.md Active Requirements

All Active requirements present and grouped:

| PROJECT.md Section | Reqs | Bucket | Phase Hint |
|---|---|---|---|
| Foundation | CORE-01..03 | Table stakes | foundation |
| Unified state model | STATE-01..04 | STATE-01..03 table stakes; STATE-04 differentiator | foundation (1-3), learning (4) |
| Protocol translators | TRANS-01..05 | T1,T2,T3,T5 table stakes; T4 differentiator | driver |
| Racing action delivery | ACT-01..04 | Table stakes | driver |
| Push-event verifier | VERIFY-01,02,03 | VERIFY-01 table stakes; 02,03 differentiator | verifier |
| Deterministic ensemble | VERIFY-04..07 | Table stakes | verifier |
| Failure classifier + recovery | HEAL-01..05 | HEAL-01,04,05 table stakes; HEAL-02,03 differentiator | recovery |
| Cache self-heal write-back | CACHE-01..03 | Differentiator | learning |
| Continuous learning | LEARN-01..05 | Differentiator | learning |
| Cognitive layer | COG-01..08 | Differentiator | cognition |
| Persistence + durable execution | PERSIST-01..03 | Table stakes | foundation |
| Visualizer + transparency | VIS-01..06 | Differentiator | transparency |
| Full transparency (replay) | OBS-01..06 | Differentiator | transparency |
| Private SPI integration | SPI-01..08 | Differentiator | SPI |
| MCP server interface | MCP-01,02 | Table stakes | SPI/foundation |

All 79 Active requirements covered. All Out-of-Scope items mapped to anti-features above.

---

## Sources

### Primary (locked architecture + competitive verified)
- `/Users/akeilsmith/dev/basicCtrl/.planning/PROJECT.md` (requirements + decisions)
- `~/thinker/vault/research/basicCtrl-self-healing-framework-2026-04-29.md` (THE blueprint, 200+ sources, HIGH confidence)
- `~/thinker/vault/research/computer-use-alternatives-2026-04-29.md` (Apr 2026 verified landscape)

### Reference repos (read locally)
- `~/thinker/research-clones/trycua-cua/` — Swift driver to fork
- `~/thinker/research-clones/browser-harness/` — daily-used CDP harness
- `~/thinker/research-clones/skyvern/` — parallel verify + failure taxonomy
- `~/thinker/research-clones/stagehand/` — AgentCache write-back
- `~/thinker/research-clones/magentic-ui/` — JSON retry + n_replans
- `~/thinker/research-clones/ghost-os/` — CGEvent tap + Recipe JSON

### Research papers (cited in vault)
- VeriSafe Agent (arXiv 2503.18492) — pre-action verification
- Decomposing Self-Correction (arXiv 2601.00828) — 16-27% intrinsic accuracy
- Dark Side of Self-Correction (arXiv 2412.14959) — cognitive wavering
- Screen2AX (arXiv 2507.16704) — synthetic AX, 77% F1
- V-Droid (arXiv 2503.15937) — verifier-driven, 0.7s/step
- CUWM (arXiv 2602.17365) — world model for desktop CU
- Speculative Actions (arXiv 2510.04371) — 55% prediction, 20% latency cut
- Shah et al. (arXiv 2603.06847) — 5-dim fault taxonomy

### Production benchmarks (verified Apr 2026)
- Cowork: ~50% reliability (MacStories 12-task test, March 2026)
- Cowork: issue #49498 (loses session data on crash)
- OSWorld leaderboard: Claude Opus 4.6 = 72.7%, Qwen3-VL-235B = 66.7%
- UI-TARS-1.5-7B (open): 27.5% OSWorld (NOT the 42.5% closed full model)

---
*Feature research for: basicCtrl self-healing autonomous Mac CU framework*
*Researched: 2026-04-29*
*All 79 Active reqs from PROJECT.md covered + grouped by category, complexity, dependencies, phase.*
