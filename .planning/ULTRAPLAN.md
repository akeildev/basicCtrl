# ULTRAPLAN — finish cua-maximalist for full usage

> Goal: drive any Mac app, never silently fail, long-horizon, transparent.
> Estimate: 12-18h wall clock with 5 parallel sub-agents.

---

## §0 — North star (what "done" means)

```
G1  main.py boots cleanly + serves 6 healing tools to MCP Inspector
G2  One canary drives 3+ apps in ONE session: AX + CDP + Vision
G3  Every layer row in §3 audit shows ✓ + has CUA_RUN_E2E_X gate
G4  SIGKILL+resume passes (long-horizon proof)
G5  Visualizer sidecar live: ghost cursor + HUD visible during demo
G6  cua-trace + cua-monitor work — every event has trace_id
G7  Recovery actually fires + heals on real failure (not just dispatch)
G8  Smoke runs all gates green in <90s (excluding live e2e)
G9  Cognition ensemble runs IF API keys set (otherwise gracefully skipped)
```

---

## §1 — Pre-flight (BLOCK if fail)

```bash
scripts/preflight.sh — write this; covers:

REQUIRED (block if missing)
  [ ] cua-driver binary on PATH                      ✓ already
  [ ] Postgres :5432 ready                           ✓ already
  [ ] uv env intact + main.py imports                ✓ already
  [ ] mlx-vlm installed                              ✓ already
  [ ] ultralytics installed                          ✗ NEEDED
  [ ] UI-TARS-1.5-7B-4bit downloaded                 ✗ NEEDED
  [ ] TCC: Accessibility for Python                  ✗ user click
  [ ] TCC: Screen Recording for Python               ✗ user click
  [ ] TCC: Automation Python→TextEdit/Pages          ✗ user click

OPTIONAL (graceful skip)
  [ ] ANTHROPIC_API_KEY                              cognition only
  [ ] OPENAI_API_KEY                                 ensemble vote only
  [ ] SIP partial-off                                DTrace + ES only
  [ ] FocusMonitorApp (cua-driver fixture)           focus tests only
```

---

## §2 — Layer audit (current state, 26 rows)

```
LAYER                    STATUS   BLOCKER / NEEDS
─────────────────────────────────────────────────────────────
0  cua-driver Swift      ✓        -
1  main.py boots         ?        NEVER RUN END-TO-END
2  T1 AX                 ✓        live demo Calculator
3  T2 CDP                ?        no live test (needs chromium)
4  T3 AppleScript        ✓        live demo TextEdit
5  T4 Vision (uitag)     ✗        ultralytics missing
6  T5 Pixel (UI-TARS)    ✗        UI-TARS model missing
7  C1 SkyLight           partial  public CGEvent fallback only
8  C2 kAXPress           ✓        live demo
9  C3 CGEvent+cursor     ✓        race loser observed
10 C4 AppleScript        ✓        live TextEdit
11 C5 CDP Input          ?        no live test
12 L0 push verify        ✓        F9 fixed
13 L1 cheap diff         ✓        in race
14 L2 AX subtree         ?        exists, no e2e
15 L3 LLM verifier       ✗        STUB; Phase 4
16 B1 rescroll           partial  fails fast on non-scroll apps
17 B2 OCR-reground       ✗        depends on T4 (ultralytics)
18 B3 world-replan       ✗        STUB
19 B4 planner-requery    ✗        STUB
20 B5 AS fallback        partial  only SDEF apps
21 Cognition ensemble    ✗        no API keys (optional)
22 Visualizer sidecar    ?        socket not_found in logs
23 Durability Postgres   partial  no SIGKILL+resume e2e
24 Memory FAISS recall   ?        no recall e2e
25 CGEvent recorder      ?        sidecar not built
```

---

## §3 — Phase 0: Observability foundation (do FIRST, ~3h, me)

Without trace IDs + waterfall, every other phase flies blind. Build before any agent dispatch.

### 3.1 Trace ID propagation

**File:** `cua_overlay/observability/trace.py`

```python
from contextlib import contextmanager
import structlog

@contextmanager
def trace(action_id: str, operation: str, **kwargs):
    """Bind trace context for the duration. Every log inside carries
    trace_id=action_id."""
    structlog.contextvars.bind_contextvars(
        trace_id=action_id, operation=operation, **kwargs
    )
    try:
        yield
    finally:
        structlog.contextvars.unbind_contextvars(
            "trace_id", "operation", *kwargs.keys()
        )
```

Wire at every MCP tool entry in `healing_tools.py`:

```python
async def click_with_healing(...):
    action_id = str(uuid.uuid4())
    with trace(action_id, "click_with_healing", label=label, bundle_id=bundle_id):
        ...
```

### 3.2 Per-layer event hooks

Add structured events at every layer boundary. Each costs ~5 LOC.

```
T1 AX walk:       walk.start, walk.depth_reached, walk.elements_visited, walk.end
T2 CDP:           cdp.session_attach, cdp.dom_query, cdp.input_dispatch
T3 AS:            as.compile, as.exec, as.return
T4 Vision:        vision.screenshot, uitag.detect, ocr.recognize, vision.match
T5 Pixel:         pixel.screenshot, uitars.prompt, uitars.complete, pixel.match
C1-C5 channels:   channel.claim_attempt, channel.fire_start, channel.fire_end
L0-L3 verifier:   verifier.tier_start, verifier.tier_signal, verifier.tier_end
Recovery:         recovery.classify, recovery.branch_attempt, recovery.terminal
Visualizer:       viz.send_attempt, viz.socket_connected, viz.frame_rendered
Memory:           memory.query, memory.match, memory.miss
Durability:       ckpt.commit_start, ckpt.commit_end, ckpt.state_hash
```

Total ~250 LOC across many files.

### 3.3 cua-trace CLI

**File:** `scripts/cua-trace`

```bash
$ cua-trace abc123
TRACE abc123 (click_with_healing label=Send)
─────────────────────────────────────────────────────────
[ +0.0ms]  tool.click_with_healing                label="Send"
[ +1.2ms]  classify.cache_hit                     bundle=com.slack
[ +2.5ms]  t2.resolve.start
[+45.1ms]  t2.cdp.dom_query elapsed=42.6ms        node=42
[+46.3ms]  axmgr.subscribe_pending                target=app_root
[+50.0ms]  l1.snapshot phash hash=4ms
[+52.0ms]  race.fan_out                           channels=[C5,C2,C1]
[+89.2ms]  axvaluechanged.received                notif=AXValueChanged
[+91.1ms]  tool.return                            verified=true

ANOMALIES
  - 39.6ms gap between t2.resolve.start and t2.cdp.dom_query
```

Reads `~/.cua/sessions/<sid>/action_log.ndjson`, filters by `trace_id`, sorts by `timestamp_ns`, prints waterfall, flags >10ms gaps + errors.

### 3.4 cua-monitor TUI

**File:** `scripts/cua-monitor`

```
┌─────────────── cua-monitor ──────── [F]ilter [T]ail [Q]uit ─┐
│ session: abc123  uptime: 02:14  actions: 47  verified: 93%   │
│ ───────────────────────────────────────────────────────────  │
│ LIVE                                                          │
│ [12:34:01] click_with_healing label=Send  T2/C5  142ms ✓     │
│ [12:34:02] type_with_healing  text=hi     T1/C2   89ms ✓     │
│ [12:34:04] click_with_healing label=Submit T1/C2  71ms ⚠heal │
│   └ B1_RESCROLL → fired → verified                            │
│                                                               │
│ TIMING (p50/p95/p99)                                          │
│   resolve:  14ms / 31ms / 78ms                                │
│   race:     22ms / 44ms / 91ms                                │
│   verify:   31ms / 47ms / 89ms                                │
└───────────────────────────────────────────────────────────────┘
```

Uses `rich.live.Live`. Reads from `/tmp/cua-trace-bus.sock` (live) OR file tail (fallback).

### 3.5 Live event bus

**File:** `cua_overlay/observability/bus.py`

structlog processor that ALSO writes each event to `/tmp/cua-trace-bus.sock` if subscribers exist. cua-monitor connects to this for real-time view without file polling lag.

### 3.6 CUA_DEBUG=1 mode

```python
# When set: log level=debug, all hooks fire, bus enabled
# When unset: log level=info, bus disabled, hooks fire but at debug level
```

### Phase 0 deliverable

```
PR: feat(observability): trace IDs + cua-trace CLI + cua-monitor TUI
~600 LOC, 3 new tests
```

---

## §4 — Phase 0.5: Boot main.py (do SECOND, ~2h, me)

Before parallel agents — verify the integration point actually works.

### 4.1 MCP Inspector test

```bash
# Install once
npm install -g @modelcontextprotocol/inspector

# Run
mcp-inspector uv run cua-maximalist-mcp --cwd /Users/akeilsmith/dev/cua-maximalist
```

Browser opens. Click "List Tools". Assert all 6 healing tools appear.

### 4.2 First real call

In Inspector: call `click_with_healing(x=100, y=100, bundle_id="com.apple.calculator", label="5")`. Assert response has `verified: true`.

### 4.3 Surface boot-time F-bugs

Likely candidates (each is a possible F-bug):
- DurableExecutor schema not initialized → write `scripts/init_postgres.sh`
- AX bridge race during startup → add startup probe
- Upstream cua-driver subprocess silent failure → add stderr capture
- Visualizer socket connection retry → add backoff

### Phase 0.5 deliverable

```
PR: fix(mcp): boot main.py end-to-end + first real MCP tool call
N F-bugs documented + fixed
```

---

## §5 — Phase 1: 5 parallel sub-agents (~4-6h wall clock)

Each agent gets:
- Worktree (isolation: "worktree")
- Focused prompt
- Findings file: `.planning/agent-reports/AGENT-N-FINDINGS.md`
- Acceptance criteria
- One e2e test minimum

I dispatch all 5 in one message (parallel). Integrate sequentially.

### Agent 1 — Vision stack (T4/T5 universal fallback)

**Goal:** T4+T5 work on a non-AX app.

```
Tasks:
  1. uv add ultralytics
  2. Download UI-TARS-1.5-7B-4bit (huggingface_hub)
  3. CUA_RUN_E2E_VISION_CHESS gate:
       launch Chess.app, click "New Game", click pawn at e2
       assert: T4 detection_count > 0, T5 grounded coords, click landed
  4. CUA_RUN_E2E_VISION_FIGMA gate (or any non-AX app)
  5. Add T4/T5 trace hooks (vision.*, uitars.*)
  6. Surface F-bugs, fix
  7. AGENT-1-VISION.md with: trace dump, F-bugs found, ratio Retina handling

Acceptance: 2 live e2e green; T4 detection_count > 0 in trace.
```

### Agent 2 — CDP / Electron stack

**Goal:** T2 + C5 work against real Chrome.

```
Tasks:
  1. CUA_RUN_E2E_CDP_CHROMIUM gate:
       spawn chromium subprocess --remote-debugging-port=9222
       navigate to example.com, click "More information…" link
       assert: T2 won race, C5 dispatched, URL changed
  2. CDP-specific trace events (request_id, frame_id, target session)
  3. Surface F-bugs, fix
  4. STRETCH: Slack-mac via cdp_after_relaunch=True
  5. AGENT-2-CDP.md

Acceptance: chromium e2e green; trace shows T2 won + C5 fired.
```

### Agent 3 — Durability + crash recovery

**Goal:** SIGKILL+resume works.

```
Tasks:
  1. Verify scripts/init_postgres.sh exists + works
  2. CUA_RUN_E2E_DURABILITY gate:
       8-step task (Calculator AC, 1, 2, 3, +, 4, 5, =)
       SIGKILL Python after step 4
       restart, assert resume_from_crash() returns at step 5
       assert Postgres state has step_idx=4 committed
  3. ckpt.* trace events
  4. Surface F-bugs, fix
  5. AGENT-3-DURABILITY.md

Acceptance: SIGKILL test green; ckpt commits in trace; <2s resume.
```

### Agent 4 — Recovery branches B3/B4 + L3 verifier

**Goal:** unstub world-replan + planner-requery; (optional) wire L3.

```
Tasks:
  1. EITHER implement B3 (world-replan: re-classify app + re-resolve)
     OR document as Phase 4-deferred with explicit no-op contract
  2. EITHER implement B4 (planner-requery: ask LLM to suggest alternate target)
     OR document as Phase 4-deferred
  3. CUA_RUN_E2E_RECOVERY_REAL gate:
       induce failure (mock verifier verified=False once)
       assert B1 fires (rescroll attempted)
       assert recovery_succeeded if rescroll worked
  4. IF API keys set: replace L3Stub with L3LLMVerifier
       fire on confidence 0.30-0.50 zone
       per-oracle confidence in trace
  5. AGENT-4-RECOVERY.md

Acceptance: real failure → recovery → re-fired action verified.
```

### Agent 5 — Visualizer + Memory + Recorder

**Goal:** transparency + learning loop.

```
Tasks:
  1. Build Swift visualizer sidecar (libs/visualizer/)
       NSPanel transparent overlay, ghost cursor + HUD
       SCContentFilter excludingApplications=[self]
       Listens on /tmp/cua-visualizer.sock for NDJSON
  2. Auto-launch from main.py if available
  3. CUA_RUN_E2E_VISUALIZER gate:
       run a click, assert socket connected + frame rendered
  4. CUA_RUN_E2E_MEMORY gate:
       run task, assert episodic recipe written to FAISS
       re-run similar task, assert recall short-circuits at least 1 step
  5. CGEvent recorder Swift sidecar (libs/recorder/):
       captures user manual clicks
       Python synthesizer indexes to FAISS as recipes
  6. viz.* + memory.* trace events
  7. AGENT-5-VIZ-MEMORY.md

Acceptance: visualizer socket connects in test; memory recall e2e green.
```

---

## §6 — Phase 2: Integration canary (~3h, me)

After all 5 agents return + integrate.

### 6.1 Multi-app canary

**File:** `tests/integration/test_canary_multi_app.py`

```python
# CUA_RUN_E2E_CANARY=1
@pytest.mark.asyncio
async def test_drives_three_apps_in_one_session():
    """Boot main.py via subprocess. Drive Calculator (AX) +
    chromium (CDP) + Chess (Vision) via the actual MCP tool surface.
    Assert every step verified or recovered."""
```

### 6.2 Smoke gates expanded

```
./scripts/smoke.sh                                  current
+ all new CUA_RUN_E2E_* gates from agents
+ CUA_RUN_E2E_CANARY=1 (runs all)
```

### 6.3 verify-everything.sh

```bash
# Runs preflight, then every gate. Reports per-gate status.
# Exits non-zero on any failure with which gate failed.
```

---

## §7 — Phase 3: Trycua upstream contributions (~2h, me, optional)

Only after main work lands.

```
PR 1: AX-readiness probe pattern (we use it; their tests don't)
Issue 1: AXObserverAddNotification refcon dedupe (our F9)
PR 2: Contribute cua-trace + cua-monitor as opt-in toolkit
Adopt: their FocusMonitorApp into our integration tests
```

---

## §8 — Phase 4: Human playbook (~1.5h, you)

Things I cannot do autonomously.

### 8.1 One-time setup (~15 min)

```bash
# TCC permissions
# System Settings → Privacy & Security
#   Accessibility       → +Add Python (.venv/bin/python3)
#   Screen Recording    → +Add Python
#   Automation          → Python → TextEdit, Pages, Calculator, Chess

# Optional API keys
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

### 8.2 Per-track validation (~45 min)

```
TRACK 1 (Vision):
  [ ] CUA_RUN_E2E_VISION_CHESS=1 ./scripts/smoke.sh
  [ ] Watch Chess: ghost cursor before click? pawn moved?

TRACK 2 (CDP):
  [ ] CUA_RUN_E2E_CDP_CHROMIUM=1 ./scripts/smoke.sh
  [ ] Chromium opened? Link clicked? URL changed?

TRACK 3 (Durability):
  [ ] CUA_RUN_E2E_DURABILITY=1 ./scripts/smoke.sh
  [ ] Calculator state recovered after SIGKILL?

TRACK 4 (Recovery):
  [ ] CUA_RUN_E2E_RECOVERY_REAL=1 ./scripts/smoke.sh

TRACK 5 (Visualizer):
  [ ] CUA_RUN_E2E_VISUALIZER=1 ./scripts/smoke.sh
  [ ] Did you SEE the ghost cursor + HUD overlay during run?
```

### 8.3 Real-world acceptance (~30 min)

```
1. Wire cua-maximalist into Claude Code MCP config (see §6 of earlier draft)
2. Restart Claude Code
3. Ask: "Use cua-maximalist to compute 17*23 in Calculator,
        then open TextEdit and write the answer in math.txt"
4. Watch:
     - Terminal: cua-monitor (live trace)
     - Mac screen (visualizer overlay)
5. Pass:
     - math.txt exists with "391"
     - Every step verified or recovered in trace
     - No silent failures
```

---

## §9 — Risk register

```
RISK                              MITIGATION
─────────────────────────────────────────────────────────────────
Calculator AX flakiness           Use TextEdit/Pages for new tests;
                                  AX-readiness probe gates existing
Sub-agent merge conflicts         Worktrees per agent; sequential
                                  integration with rebase
UI-TARS coord-quantization bug    Fall back to ShowUI-2B (mlx-vlm
 (mlx-vlm #330)                   community model)
TCC dialog blocking tests         Preflight detects; user grants
                                  before agent dispatch
F-bugs surface late               Each agent's findings file MUST
                                  include trace dump
trycua/cua upstream changes       Vendored; intentional bumps only
SIP-required SPIs (DTrace, ES)    Graceful skip; user opt-in
LangGraph schema migration        scripts/init_postgres.sh idempotent
Visualizer screen capture loop    SCContentFilter excludingApps=[self]
                                  prevents recursive capture
NSPanel z-order on macOS 26       Test with .popUpMenu level; fallback
                                  to .floating
```

---

## §10 — Execution order + estimate

```
HOUR  PHASE                                        WHO
──────────────────────────────────────────────────────────────────
0     §1 preflight (verify state)                  me
0-3   §3 observability foundation                  me
3-5   §4 boot main.py (Phase 0.5)                  me
5-11  §5 5 agents in parallel                      5 sub-agents
11-14 §6 integration canary                        me
14-15 §8 human playbook walkthrough                you
15-16 §6.3 verify-everything.sh                    me
16-18 §7 trycua upstream PRs (optional)            me
```

Wall clock: ~16h with full parallelism, +2h buffer for F-bugs = ~18h.

If sub-agents fail or surprise: each agent's findings file is independent. I patch up gaps in Phase 2.

---

## §11 — What user provides

```
ABSOLUTE MINIMUM TO START:
  - "go" command
  - TCC permissions clicked (~5 min)

OPTIONAL (unlocks more tests):
  - ANTHROPIC_API_KEY
  - OPENAI_API_KEY
  - SIP partial-off
  - Chess.app installed (for vision e2e)
  - Pages with a doc open (for AppleScript e2e)
```

---

## §12 — Acceptance gate (final)

```
G1  ✓  main.py boots + 6 tools registered
G2  ✓  canary drives 3+ apps in one session
G3  ✓  every layer row green + has gate
G4  ✓  SIGKILL+resume passes
G5  ✓  visualizer ghost cursor visible
G6  ✓  every event has trace_id
G7  ✓  recovery fires + heals on real failure
G8  ✓  smoke <90s green
G9  ✓  cognition runs IF keys set, else skip
```

When all 9 hold: cua-maximalist is ready for real-world use.
