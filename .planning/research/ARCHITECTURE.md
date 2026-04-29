# Architecture: cua-maximalist

**Project:** cua-maximalist — Self-Healing Autonomous Mac CU Framework
**Researched:** 2026-04-29
**Granularity:** standard (5–7 phases)
**Confidence:** HIGH (grounded in 9-layer locked architecture + 4 reference clones)

---

## TL;DR

```
.../cua-maximalist/
  libs/cua-driver/Sources/        ← UNTOUCHED Swift driver from trycua
  overlay/                         ← Python overlay (~1500–2500 LOC)
  visualizer/Sources/              ← Swift glue (~300 LOC) — NSPanel + SkyLight bridges
  ~/.cua/sessions/<id>/            ← runtime state
```

- **Python is the brain.** State graph + cognition + verifier orchestration.
- **Swift is the hands + eyes.** Driver execution + push events + visualizer.
- **One IPC seam.** JSONL line protocol over stdio (extends trycua's existing pattern).
- **Build order is bottom-up.** Foundation → State → Translators → Verifier → Race → Heal → Observe.

---

## Component map (ASCII)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                       MCP SURFACE  (existing trycua MCP server)          │
│                       overlay/mcp_server.py — adds healing wrapper       │
└────────────────────────────────┬─────────────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────────────┐
│                       overlay/  (Python — the State Bridge)               │
│                                                                           │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  cognition/   (L0 + L1)                                          │   │
│   │    goal.py        — NL → typed Goal                              │   │
│   │    planner.py     — Opus async                                   │   │
│   │    grounder.py    — UI-TARS MLX                                  │   │
│   │    world_model.py — CUWM-style predictor                         │   │
│   │    verifier_llm.py— V-Droid prefill                              │   │
│   │    apple_fm.py    — local 3B classifier                          │   │
│   │    critic.py      — recovery arbiter                             │   │
│   │    ensemble.py    — 3-model vote (Opus + GPT-5 + FM)             │   │
│   │    speculative.py — N+1 / N+2 draft prediction                   │   │
│   └──────────────┬───────────────────────────────────────────────────┘   │
│                  │ reads/writes graph nodes                              │
│   ┌──────────────▼───────────────────────────────────────────────────┐   │
│   │  state/   (L2 — typed-graph state, the CORE)                     │   │
│   │    graph.py       — UIElement node + edges (containment/         │   │
│   │                     enables/triggers/precedes)                    │   │
│   │    causal_dag.py  — action → state delta                         │   │
│   │    ring_buffer.py — last 5 frames                                │   │
│   │    fingerprint.py — (app, task_class, state_fp) hash             │   │
│   │    episodic.py    — FAISS local vector store                     │   │
│   │    snapshot.py    — serialize/restore for persistence            │   │
│   └──────────────┬───────────────────────────────────────────────────┘   │
│                  │                                                       │
│         ┌────────┼─────────┬─────────────┬──────────────┐                │
│         ▼        ▼         ▼             ▼              ▼                │
│   ┌──────────┐ ┌────────────┐ ┌──────────────┐ ┌──────────────────┐     │
│   │profile/  │ │translators/│ │ verifier/    │ │ recovery/        │     │
│   │(routing) │ │ (L3)       │ │ (L5)         │ │ (L6 + L7)        │     │
│   │classifier│ │ t1_ax      │ │ axobserver   │ │ classifier       │     │
│   │.py       │ │ t2_cdp     │ │ nsworkspace  │ │ branches/        │     │
│   │profile   │ │ t3_apple   │ │ distnotif    │ │   b1_rescroll    │     │
│   │_cache.py │ │ t4_vision  │ │ cdp_dom_obs  │ │   b2_ocr_reground│     │
│   │capability│ │ t5_pixel   │ │ kqueue_proc  │ │   b3_world_replan│     │
│   │_probe.py │ │ registry.py│ │ aggregator   │ │   b4_planner_reqry│    │
│   │          │ │ base.py    │ │ ensemble/    │ │   b5_applescript │     │
│   │          │ │            │ │   l0_push    │ │ orchestrator.py  │     │
│   │          │ │            │ │   l1_cheap   │ │ circuit_breaker  │     │
│   │          │ │            │ │   l2_medium  │ │                  │     │
│   │          │ │            │ │   l3_llm     │ │                  │     │
│   └─────┬────┘ └─────┬──────┘ │   weighted_  │ └─────┬────────────┘     │
│         │            │        │     vote     │       │                  │
│         │            │        └──────┬───────┘       │                  │
│         │            ▼               │               │                  │
│         │     ┌──────────────────────▼───────────────▼──────┐           │
│         │     │ actions/  (L4 — racing delivery)            │           │
│         │     │   channel_registry.py                       │           │
│         │     │   race_orchestrator.py (asyncio.wait FIRST) │           │
│         │     │   idempotency.py (atomic pre-action token)  │           │
│         │     │   channels/                                  │          │
│         │     │     c1_skylight  c2_ax_press                │           │
│         │     │     c3_cgevent   c4_applescript             │           │
│         │     │     c5_cdp_input                            │           │
│         │     └──────────────────────┬──────────────────────┘           │
│         │                            │                                   │
│   ┌─────▼────────────┐  ┌───────────▼───────────┐  ┌──────────────┐     │
│   │ cache/           │  │ persist/    (L8)      │  │ learning/    │     │
│   │ (Stagehand-style)│  │ session_writer.py     │  │ (ghost-os)   │     │
│   │ agent_cache.py   │  │ snapshot_io.py        │  │ recorder.py  │     │
│   │ key.py (SHA-256) │  │ checkpoint.py         │  │ coalesce.py  │     │
│   │ replay.py        │  │ durable_step.py       │  │ recipe_synth │     │
│   │ cassette.py      │  │   (Inngest/LangGraph) │  │ replay_engine│     │
│   │ writeback.py     │  │ resume.py             │  │              │     │
│   └──────────────────┘  └───────────────────────┘  └──────────────┘     │
│                                                                          │
│   ┌──────────────────────────────────────────────────────────────────┐   │
│   │  ipc/  (Python ⇄ Swift seam)                                     │   │
│   │    swift_bridge.py    — JSONL stdio to cua-driver subprocess     │   │
│   │    visualizer_bus.py  — JSONL stdio to visualizer subprocess     │   │
│   │    spi_calls.py       — typed wrappers (skylight, ax_remote, …)  │   │
│   └──────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬───────────────────────────────────────┘
                                   │ JSONL over stdio (line-delimited)
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│ libs/cua-driver/   │  │ visualizer/          │  │ spi-bridge/          │
│ (UNTOUCHED)        │  │ (Swift, ~300 LOC)    │  │ (Swift glue)         │
│                    │  │                      │  │                      │
│ CuaDriverCore/     │  │ GhostCursor.swift    │  │ SkyLightBridge.swift │
│   Input/           │  │ ElementBox.swift     │  │   SLEventPostToPid   │
│   AppState/        │  │ HUD.swiftui          │  │ AXRemoteBridge.swift │
│   Apps/            │  │ NSPanel host         │  │   _AXObserver…Remote │
│   Browser/         │  │   (.popUpMenu,       │  │ ESBridge.swift       │
│   Capture/         │  │    ignoresMouse,     │  │   es_new_client      │
│   Cursor/          │  │    canJoinAllSpaces) │  │ DYLDInject.swift     │
│   Focus/           │  │ SCContentFilter      │  │ IMUReader.swift      │
│   Permissions/     │  │   (excludes self)    │  │   AppleSPUHIDDevice  │
│   Telemetry/       │  │ TimelineView.swiftui │  │                      │
│   ToolRegistry.swift  │ Recorder.swift (60fps│  │                      │
│ ── HOOK ──         │  │   H.265 lossless)    │  │                      │
│  ToolRegistry      │  │                      │  │                      │
│  :55-97 emits      │  │                      │  │                      │
│  structured event  │  │                      │  │                      │
│  to stdout JSONL   │  │                      │  │                      │
└────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

---

## Data flow (explicit)

### Forward path — goal → action

```
NL intent
   │
   ▼  cognition/goal.py
typed Goal {task, preconds, success_criteria}
   │
   ▼  cognition/planner.py + grounder.py + world_model.py (concurrent)
candidate action A on element E
   │
   ▼  state/graph.py → look up E by id
StateNode(E) = {role, bbox, capabilities, source[], confidence}
   │
   ▼  profile/classifier.py — pick translator order for this app
translator priority list [T1, T2, T4, T5]   (e.g. for Slack)
   │
   ▼  verifier/axobserver.py — SUBSCRIBE to expected notifications
                                BEFORE the action (this is the secret weapon)
   │
   ▼  actions/idempotency.py — write atomic pre-action token
   │
   ▼  actions/race_orchestrator.py — fire C1..C5 in parallel
                                      asyncio.wait(FIRST_COMPLETED, timeout=2s)
   │
   ▼  channels execute via ipc/swift_bridge.py → cua-driver
   │   (or in-process for AX/AppleScript Python paths)
   │
   ▼  ToolRegistry.swift:55-97 fires post-action event
                              JSONL → swift_bridge → verifier
   │
   ▼  verifier/ensemble — L0 push → L1 cheap → L2 medium → (L3 LLM if confidence < 0.30)
weighted vote → confidence ≥ 0.50 → VERIFIED
   │
   ▼  state/causal_dag.py — record action → delta
   ▼  cache/writeback.py — heal selectors if drifted
   ▼  persist/durable_step.py — checkpoint
   ▼  visualizer_bus.py — emit step event for HUD/timeline
```

### Backward path — failure → recovery

```
verifier confidence < 0.50
   │
   ▼  recovery/classifier.py — 6-class enum
PERCEPTUAL | COGNITIVE | ACTUATION | ENVIRONMENTAL | RESOURCE | LOOP
   │
   ▼  recovery/orchestrator.py — fan out 5 branches in parallel
B1 rescroll+AX  B2 OCR+CGEvent  B3 world replan  B4 planner replan  B5 AppleScript
   │
   ▼  asyncio.wait(FIRST_COMPLETED) — first verified branch wins
   │   losers cancelled, logged to RL training buffer
   │
   ▼  circuit_breaker — if 3 consecutive failures on same target → escalate
   │
   ▼  bounded — max 2 cycles → escalate to user
```

### Continuous learning loop (background, always-on)

```
CGEvent tap (.listenOnly) on bg thread     [Swift, ghost-os pattern]
   │
   ▼  JSONL → learning/recorder.py
   ▼  learning/coalesce.py (CFRunLoopTimer 0.5s) → typeText action
   ▼  learning/recipe_synth.py → Recipe JSON {params, preconds, steps, on_failure}
   ▼  state/episodic.py → FAISS embed + index
   │
   ▼  next run: cognition/planner.py queries episodic before LLM call
                "last time we did this on this app" → adapt
```

---

## IPC boundary — Python ⇄ Swift

**One protocol, two channels.** JSONL line protocol over stdio (extending trycua's existing pattern from `daemon.py`-style harness).

```
┌────────────────────────┐         JSONL stdio         ┌─────────────────────┐
│  overlay (Python)      │  ────────────────────────►  │  cua-driver (Swift) │
│  ipc/swift_bridge.py   │  {"method":"ax.click",      │  ToolRegistry       │
│                        │   "params":{...},           │  receives, dispatches│
│                        │   "id":"<uuid>",            │  to AXInput,        │
│                        │   "session":"<id>"}         │  CGEvent, etc.      │
│                        │                             │                     │
│                        │  ◄────────────────────────  │  ToolRegistry:55-97 │
│                        │  {"event":"action_done",    │  emits post-action  │
│                        │   "id":"<uuid>",            │  event              │
│                        │   "result":{...},           │                     │
│                        │   "ax_notif":[...]}         │                     │
└────────────────────────┘                             └─────────────────────┘

┌────────────────────────┐         JSONL stdio         ┌─────────────────────┐
│  overlay (Python)      │  ────────────────────────►  │  visualizer (Swift) │
│  ipc/visualizer_bus.py │  {"event":"step",           │  GhostCursor lerps  │
│                        │   "tier":"T1",              │  ElementBox draws   │
│                        │   "channel":"C2",           │  HUD appends action │
│                        │   "target_bbox":[x,y,w,h],  │                     │
│                        │   "status":"verified"}      │                     │
└────────────────────────┘                             └─────────────────────┘
```

**Why JSONL stdio:**

- Already how trycua's CLI mode works → minimal new protocol surface
- Trivial to debug (one event = one line)
- No socket cleanup, no port allocation, no race on shutdown
- `browser-harness` proves the pattern works at scale

**SPI bridge calls** are Swift functions exposed as JSONL methods (e.g. `{"method": "skylight.event_post", "params": {...}}`). Python never links against SkyLight directly.

---

## Build-order dependencies

A blocks B = "B cannot ship without A."

```
                              ┌──────────────────┐
                              │ CORE (foundation)│
                              │  • fork repo     │
                              │  • overlay scaffold
                              │  • ipc/swift_bridge
                              │  • ToolRegistry  │
                              │    post-action hook
                              └────────┬─────────┘
                                       │
                  ┌────────────────────┼────────────────────┐
                  ▼                    ▼                    ▼
        ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
        │ profile/         │  │ state/graph      │  │ persist/         │
        │  classifier      │  │  (in-memory only │  │  session_writer  │
        │  capability_probe│  │   to start)      │  │  snapshot_io     │
        └────────┬─────────┘  └────────┬─────────┘  └──────────────────┘
                 │                     │
                 │            ┌────────┼────────┐
                 │            ▼        ▼        ▼
                 │       state/     state/    state/
                 │       causal_dag ring_buf  episodic
                 │            │
                 ▼            ▼
        ┌─────────────────────────────────┐
        │ translators/registry + base     │
        │  ┌──── t1_ax  (start here —    │
        │  │      most info-dense)       │
        │  ├──── t3_applescript          │
        │  ├──── t5_pixel  (simplest)    │
        │  ├──── t2_cdp                  │
        │  └──── t4_vision (Screen2AX +  │
        │         uitag SoM)             │
        └─────────────┬───────────────────┘
                      │
                      ▼
        ┌─────────────────────────────────┐
        │ verifier/                       │
        │  ┌──── axobserver  (PUSH —      │
        │  │      pre-subscribe pattern)  │
        │  ├──── nsworkspace, distnotif   │
        │  ├──── ensemble/l0_push         │
        │  ├──── ensemble/l1_cheap        │
        │  ├──── ensemble/l2_medium       │
        │  ├──── ensemble/weighted_vote   │
        │  └──── ensemble/l3_llm (last)   │
        └─────────────┬───────────────────┘
                      │
                      ▼  (translators + verifier together unlock racing)
        ┌─────────────────────────────────┐
        │ actions/                        │
        │  channel_registry, idempotency  │
        │  race_orchestrator              │
        │  channels/c1..c5                │
        └─────────────┬───────────────────┘
                      │
                      ▼  (racing without recovery is fragile)
        ┌─────────────────────────────────┐
        │ recovery/                       │
        │  classifier (6-class enum)      │
        │  branches/b1..b5                │
        │  orchestrator                   │
        │  circuit_breaker                │
        └─────────────┬───────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────────┐
   │ cache/  │  │ learning/│  │ cognition/   │
   │ writeback│ │ recorder │  │ planner +    │
   │ replay  │  │ recipe   │  │ ensemble +   │
   │ cassette│  │ synth    │  │ speculative  │
   └─────────┘  └────┬─────┘  └──────┬───────┘
                     │               │
                     ▼               │
              episodic memory ◄──────┘
                     │
                     ▼
              ┌──────────────────┐
              │ visualizer/      │
              │  ghost cursor    │
              │  HUD             │
              │  60fps recording │
              │  3D timeline     │
              │  counterfactual  │
              └──────────────────┘
                     │
                     ▼
              ┌──────────────────┐
              │ spi-bridge/      │
              │  skylight        │
              │  ax_remote       │
              │  endpoint sec    │
              │  dyld inject     │
              │  IMU             │
              └──────────────────┘
                     │
                     ▼
              ┌──────────────────┐
              │ persist/durable  │
              │  Inngest or      │
              │  LangGraph       │
              │  PostgresSaver   │
              └──────────────────┘
```

### Critical "blocks" relationships (top 8)

1. **`AppProfile` classifier blocks `translator registry`** — registry needs capability probe results to pick T1 vs T2 vs T3.
2. **`state/graph` blocks every translator** — translators write *into* the graph; nothing else makes sense.
3. **`AXObserver` push verifier blocks `actions/race_orchestrator`** — racing without verification is a coin flip.
4. **`idempotency tokens` block multi-channel firing** — without them, racing = double-clicks.
5. **`failure_classifier` blocks `recovery/branches`** — branches are typed by failure class.
6. **`recovery` blocks `cache/writeback`** — write-back is meaningless without a verified heal path.
7. **`learning/recorder` blocks `state/episodic`** — no recipes = no episodic memory to retrieve.
8. **`durable execution` is last** — wraps existing translator calls; only useful once translators are stable.

---

## Component boundaries — what talks to what

| Component | Reads from | Writes to | Talks to (API) |
|---|---|---|---|
| `cognition/*` | `state/graph`, `state/episodic` | `state/causal_dag` (intent) | LLM APIs (Opus, GPT-5, Apple FM) |
| `state/graph` | translators (incoming) | cognition, verifier, recovery | in-process only |
| `profile/classifier` | `~/.cua/profiles/<bundleID>.json`, capability probe | profile cache | translators (priority list) |
| `translators/t1_ax` | AX SPI via swift_bridge | `state/graph` | Swift cua-driver (AX) |
| `translators/t2_cdp` | CDP WebSocket | `state/graph` | Chrome/Electron remote debug |
| `translators/t3_applescript` | NSAppleScript subprocess | `state/graph` | OSAScript via Swift |
| `translators/t4_vision` | Screen2AX, uitag, OCR | `state/graph` | MLX models in-process |
| `translators/t5_pixel` | CGWindowList, dHash | `state/graph` | Swift CG bridge |
| `actions/race_orch` | `state/graph` (target) | `state/causal_dag` (token) | swift_bridge (each channel) |
| `verifier/axobserver` | AX notifications via swift_bridge | `state/graph` deltas | AXObserver in Swift |
| `verifier/ensemble` | push + L1/L2/L3 sources | confidence score → `actions/` | LLM API only at L3 |
| `recovery/orchestrator` | failure event from verifier | re-fires action via `actions/` | none direct |
| `cache/agent_cache` | `~/.cua/sessions/.../cassettes/` | healed selectors back to graph | filesystem |
| `learning/recorder` | CGEvent tap via swift_bridge | `learning/recipe_synth` | Swift CGEvent tap |
| `persist/session_writer` | every verified action | `~/.cua/sessions/<id>/*` | filesystem + durable engine |
| `visualizer/*` | event bus from overlay | NSPanel + Metal | self-contained Swift |
| `spi-bridge/*` | overlay calls | n/a | private Apple SPIs |
| `ipc/swift_bridge` | overlay JSONL | cua-driver stdin | cua-driver subprocess |

**One rule:** components never reach across the boundary. `cognition/` does not call `translators/` directly — it asks `actions/` for "perform this on element E" and trusts the State Bridge.

---

## Patterns to follow

### Pattern 1: Pre-subscribe, then fire

**What:** Subscribe to expected push events *before* firing the action.
**When:** Every single verified action.
**Why:** AX notifications fire in <1ms via Mach port — deterministic, no diff needed.
**Example:**

```python
# verifier/axobserver.py
async def expect(self, element, notifs: list[str]) -> EventFuture:
    fut = EventFuture()
    self._observer.subscribe(element, notifs, fut.set)
    return fut

# in actions/race_orchestrator.py
expected = await verifier.expect(target, ["AXValueChanged", "AXFocusedUIElement"])
await race(channels)
result = await asyncio.wait_for(expected, timeout=0.5)
```

### Pattern 2: One graph, many translators

**What:** Every translator writes the *same* `UIElement` shape into the graph.
**When:** Reading state from any source.
**Why:** Self-heal = "different translator, same graph entity" — only works if the entity is canonical.

### Pattern 3: Atomic idempotency token

**What:** Write a UUID into shared state before firing; channels skip if already set.
**When:** Every racing action.
**Why:** Prevents double-clicks when 2 channels both succeed.

### Pattern 4: Cheap-deterministic-first ladder

**What:** L0 push → L1 cheap (1-5ms) → L2 medium (50-200ms) → L3 LLM (300-800ms).
**When:** Always. Never start at L3.
**Why:** Papers 2601.00828 + 2412.14959 prove intrinsic LLM correction is 16-27% accurate.

### Pattern 5: JSONL stdio for IPC

**What:** One JSON object per line, `\n`-delimited, both directions.
**When:** Any Python ⇄ Swift call.
**Why:** Trivial to debug, no socket cleanup, matches trycua's existing CLI mode.

---

## Anti-patterns to avoid

### Anti-Pattern 1: Full recursive AX tree diff
**What:** Calling `AXUIElementCopyAttributeValues` recursively on Safari's web area.
**Why bad:** Confirmed 15-20s on Safari. Hangs the verifier.
**Instead:** Depth-limited (3 levels max) AX subtree at L2 only.

### Anti-Pattern 2: Direct cross-component imports
**What:** `cognition/planner.py` importing `translators/t1_ax`.
**Why bad:** Couples cognition to transport. Breaks "different translator, same graph entity."
**Instead:** Cognition asks `actions/` for an outcome. Actions picks the channel.

### Anti-Pattern 3: AX element ID as identity
**What:** Treating `AXUIElement` pointer-identity as stable.
**Why bad:** React/SwiftUI re-renders break this every keystroke.
**Instead:** `(role_path, label, bbox_centroid)` composite key in `state/fingerprint.py`.

### Anti-Pattern 4: Heavy AX polling
**What:** Walking AX tree at >30 Hz.
**Why bad:** cmux #2985 — stalls target app's main event loop.
**Instead:** AX rate-limit at translator level; cache 100ms windows.

### Anti-Pattern 5: Silent heal
**What:** Cache write-back without emitting event.
**Why bad:** Masks regressions; future debugging impossible.
**Instead:** Every heal emits `{"event":"heal", "from":..., "to":..., "reason":...}` to visualizer bus.

---

## Scalability considerations

| Concern | Single task | Long sessions (4hr) | All-day continuous |
|---|---|---|---|
| State graph size | unbounded ok | snapshot every 60s, prune nodes >5min stale | per-app subgraph eviction |
| Episodic memory | local FAISS | local FAISS | local FAISS, ok at this scale |
| 60fps recording | ok | ~50 GB/hr H.265 → rotate hourly | not recommended; downgrade to 15fps |
| 5-branch recovery cost | fine | bounded at 2 cycles | circuit breaker after 3 same-target |
| Durable steps | in-memory ok | LangGraph PostgresSaver | LangGraph PostgresSaver mandatory |

---

## Suggested phase structure (5 phases, standard granularity)

The roadmap orchestrator maps the 11-sprint sequence into 5 phases by collapsing tightly-coupled sprints. Each phase ends with a demo-able capability.

### Phase 1 — Foundation + State Bridge core (~10 days, Sprints 0+1+2)

**Goal:** A Python overlay that can read state from any Mac app and verify a click using push events + cheap deterministic checks.

**Scope:**
- Fork trycua/cua → `~/dev/cua-maximalist/`
- `overlay/` scaffold with `ipc/swift_bridge.py` (JSONL stdio)
- ToolRegistry.swift:55-97 emits structured event
- `state/graph.py` + causal_dag + ring_buffer (in-memory)
- `profile/classifier` with capability probe
- `verifier/axobserver.py` (pre-subscribe pattern)
- `verifier/ensemble/l1_cheap.py` (CGWindowList diff, NSPasteboard, dHash)

**Success criteria:**
- [ ] Click in Safari → AXValueChanged fires → recorded as verified
- [ ] State graph round-trips: probe Calculator → write entity → read it back
- [ ] AppProfile cache survives session restart
- [ ] L0+L1 ensemble verifies a click in <50ms
- [ ] No regressions to existing trycua MCP server

---

### Phase 2 — 5 Translators + Racing delivery (~12 days, Sprints 3 partial)

**Goal:** Drive any of trycua's covered apps via the *best* translator, racing channels with idempotency.

**Scope:**
- `translators/t1_ax`, `t3_applescript`, `t5_pixel` (in-process)
- `translators/t2_cdp` (browser-harness pattern)
- `translators/t4_vision` (Screen2AX + uitag SoM + OCR)
- `actions/channel_registry` + `race_orchestrator` + `idempotency`
- `actions/channels/c1..c5`
- AX rate-limit guard (cmux #2985 mitigation)

**Success criteria:**
- [ ] Click on Slack message: T2 CDP wins, others cancelled
- [ ] Click on Pages toolbar: T3 AppleScript wins
- [ ] Click on game canvas: T4 SoM wins
- [ ] No double-clicks across 100 racing fires (idempotency holds)
- [ ] Per-app translator selection matches association map for top 12 apps

---

### Phase 3 — Failure classifier + 5-branch recovery + Cache write-back (~10 days, Sprints 4+5)

**Goal:** When verification fails, the system never silently drops — it routes to recovery or escalates.

**Scope:**
- `recovery/classifier` (6-class enum)
- `recovery/branches/b1..b5` + `orchestrator`
- `recovery/circuit_breaker` (3 consecutive failures)
- `cache/agent_cache` + `replay` + `cassette` + `writeback`
- Bounded retries (max 2 cycles → escalate)
- Failed-branch logging → RL training buffer (write-only for now)

**Success criteria:**
- [ ] Inject a stale selector → cassette replay until break → live re-execute → write-back updates cache
- [ ] All 6 failure classes routed to correct recovery branch in unit tests
- [ ] Circuit breaker trips after 3 consecutive same-target failures
- [ ] User-facing escalation message after 2 recovery cycles

---

### Phase 4 — Cognition + Speculative + Continuous learning (~10 days, Sprints 6+8)

**Goal:** The system plans with multiple agents in parallel, predicts ahead, and learns from observed user actions.

**Scope:**
- `cognition/planner` (Opus async)
- `cognition/grounder` (UI-TARS MLX local)
- `cognition/verifier_llm` (V-Droid prefill)
- `cognition/world_model` (CUWM-style)
- `cognition/apple_fm` (local 3B classifier)
- `cognition/critic`
- `cognition/ensemble` (3-model vote: Opus + GPT-5 + Apple FM)
- `cognition/speculative` (Apple FM predicts N+1, N+2)
- `learning/recorder` (CGEvent tap .listenOnly)
- `learning/coalesce` (CFRunLoopTimer 0.5s)
- `learning/recipe_synth` → JSON
- `state/episodic` (FAISS local)
- Recipe replay engine

**Success criteria:**
- [ ] Speculative N+1 prediction hit rate ≥ 20%
- [ ] Recording 5min of work → produces valid Recipe JSON
- [ ] Episodic retrieval surfaces matching recipe before LLM call
- [ ] 3-model ensemble vote agrees on >80% of routine clicks
- [ ] Apple FM tier-0 classifier handles binary routing in <200ms

---

### Phase 5 — Visualizer + Private SPIs + Persistence (~13 days, Sprints 7+9+10+11)

**Goal:** Full transparency (ghost cursor, HUD, 60fps replay, counterfactual) plus private-SPI power-ups plus crash-resume durability.

**Scope:**
- `visualizer/` Swift target: NSPanel + GhostCursor + ElementBox + HUD + TimelineView
- SCContentFilter excludes overlay from own captures
- 60fps H.265 lossless screen recording (CoreMediaIO)
- Per-step state snapshot logging
- 3D timeline (X=time, Y=app, Z=action depth)
- Counterfactual replay engine
- `spi-bridge/SkyLightBridge.swift` — `SLEventPostToPid`
- `spi-bridge/AXRemoteBridge.swift` — `_AXObserverAddNotificationAndCheckRemote`
- `spi-bridge/ESBridge.swift` — Endpoint Security
- `spi-bridge/DYLDInject.swift` — Electron renderer hooks (SIP off)
- `spi-bridge/IMUReader.swift` — AppleSPUHIDDevice
- `persist/durable_step.py` — wrap each translator call (Inngest or LangGraph PostgresSaver)
- `persist/resume.py` — crash → resume from last verified step

**Success criteria:**
- [ ] Ghost cursor lerps to next click target visibly before fire
- [ ] HUD shows last 8 actions with tier badges (T1-T5 / C1-C5)
- [ ] Replay any past session reconstructs full state at every step
- [ ] Counterfactual: "what if branch B had won?" produces alternate timeline
- [ ] Kill -9 mid-task → resume picks up at last verified action
- [ ] Slack background automation works (AX remote SPI keeps tree alive)

---

### Why 5 phases, not 11 sprints

Standard granularity wants 5–7 phases that each ship a demo-able capability. The 11 sprints are correctly ordered but several are too small to be standalone milestones:

- **Sprints 0+1+2** → Phase 1 (no point showing state graph without verification)
- **Sprint 3** → Phase 2 (translators + racing land together; one without other is useless)
- **Sprints 4+5** → Phase 3 (recovery + cache write-back share the heal mental model)
- **Sprints 6+8** → Phase 4 (cognition + learning both produce/consume episodic memory)
- **Sprints 7+9+10+11** → Phase 5 (transparency, SPIs, durability are all "production polish")

If granularity were "complex" we'd split Phase 5 into two (visualizer alone, then SPIs+durable). If "minimal," we'd merge Phase 3 into Phase 2.

---

## Sources

- `~/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md` — 9-layer locked architecture (HIGH confidence)
- `~/thinker/research-clones/trycua-cua/libs/cua-driver/Sources/CuaDriverCore/` — Swift module organization (HIGH)
- `~/thinker/research-clones/browser-harness/src/browser_harness/` — flat Python overlay pattern (HIGH)
- `~/thinker/research-clones/skyvern/skyvern/forge/sdk/` — deep package structure for production CU (HIGH)
- `~/thinker/research-clones/ghost-os/Sources/GhostOS/` — Swift functional area split (HIGH)
- `/Users/akeilsmith/dev/cua-maximalist/.planning/PROJECT.md` — locked requirements + decisions (HIGH)
