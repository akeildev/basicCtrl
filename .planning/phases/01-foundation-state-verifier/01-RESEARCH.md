# Phase 1: Foundation + State + Verifier — Research

**Researched:** 2026-04-29
**Domain:** macOS 26 Accessibility SPI + push-event subscription + Pydantic state graph + LangGraph durable persistence + MCP proxy
**Confidence:** HIGH on the locked stack; MEDIUM on AppProfile probe heuristics; OPEN on a few CFRunLoop-bridge details that need a small spike during planning.

---

## Summary

Phase 1 builds the **foundation that every downstream phase depends on**. No translators yet, no actions, no LLM. Just three things wired correctly, in this order:

1. **Probe** any Mac app and write its capabilities into a cached `AppProfile`.
2. **Write** a typed state graph (`UIElement` Pydantic v2) keyed by stable composite identity (`role_path + label + bbox_centroid`) — never the raw `AXUIElement` ref.
3. **Verify** a click in **<50ms** via L0 push-event subscription (AXObserver on a Mach port) that was registered **before** the action fires, with L1 cheap-diff (CGWindowList + NSPasteboard.changeCount + dHash) as backup.

The critical insight from the canonical blueprint (`~/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md` L5): **subscribe before fire**. AXObserverAddNotification fires <1ms via Mach IPC — deterministic, free, and the entire L0+L1+L2+L3 ladder collapses if you skip it.

**Primary recommendation:** Build the AXObserver bridge FIRST (it's the highest-risk integration), then state graph, then AppProfile classifier, then the L1 cheap-diff layer. The Calculator click demo exercises the full stack.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

CONTEXT.md does NOT exist for Phase 1. Per `.planning/STATE.md`:
> Phase 1: Ready to plan (CONTEXT.md not yet written; user picked Claude's discretion on all gray areas)

Therefore, all design decisions in this phase fall under **Claude's discretion**, constrained only by:

### Locked Decisions (from PROJECT.md, STACK.md, CLAUDE.md, ARCHITECTURE.md)

These are non-negotiable for Phase 1 and beyond:

1. **Stack is locked** (STACK.md). Use raw PyObjC HIServices + atomacos partial fork; py-applescript; ocrmac; structlog; FAISS; LangGraph PostgresSaver 3.0.5; Pydantic v2; ImageHash 4.3.2.
2. **No edits to `libs/cua-driver/` Swift code.** Phase 1 is Python overlay + minimal Swift glue (visualizer + sidecars only).
3. **Push-event subscription is primary verifier.** L0 → L1 → L2 → L3 ladder; never start at L3.
4. **AX rate-limit hard cap: 20 calls/sec/pid.** Token bucket at the wrapper layer (cmux #2985).
5. **AX subtree walks: depth ≤ 3 levels, ≤ 50 children/node, ≤ 500 total nodes.** Never recursive (Safari = 15-20s).
6. **Stable composite key, not AXUIElement ref:** `(role_path, label, AXIdentifier_if_present, bbox_centroid)` for state-graph identity.
7. **MCP server is proxy, not replacement.** trycua's existing FastMCP stays; we add a Python proxy that exposes new healing tools.
8. **`commit_docs: true`** — every artifact gets a git commit.
9. **`nyquist_validation: true`** — Validation Architecture section is mandatory below.

### Claude's Discretion (everything else)

Including but not limited to:
- Module layout under `overlay/` (e.g., `overlay/state/`, `overlay/verifier/`, `overlay/profile/`).
- AXObserver thread/CFRunLoop bridge pattern (DispatchQueue vs dedicated thread + `loop.call_soon_threadsafe`).
- Exact Pydantic field names (within constraints of architecture doc L2 schema).
- AppProfile probe heuristics (which signals to check, in what order, with what timeouts).
- Test framework (likely pytest given STACK.md's pytest 8.x + pytest-asyncio).
- Postgres connection string default (`postgresql://localhost:5432/cua_maximalist` per STACK.md).
- Whether to ship the L3 LLM contract as a no-op stub or fully omit it from Phase 1.

### Deferred Ideas (OUT OF SCOPE for Phase 1)

Per ROADMAP.md and REQUIREMENTS.md traceability table:

- **Translators (T1-T5)** — Phase 2.
- **Action channels (C1-C5) and racing** — Phase 2.
- **STATE-04 episodic memory (FAISS)** — Phase 4.
- **Recovery branches, failure classifier, cassette write-back** — Phase 3.
- **Cognition layer (Opus, GPT-5, Apple FM, UI-TARS)** — Phase 4.
- **Visualizer, ghost cursor, HUD, 60fps recording** — Phase 5.
- **Private SPIs (SkyLight, ES, DTrace, DYLD inject, IMU)** — Phase 6.
- **L3 LLM verifier real implementation** — Phase 4 (Phase 1 may include the contract/stub).
- **CGEvent tap learning recorder** — Phase 4.
- **Full crash-resume durability hardening** — Phase 6 (Phase 1 = scaffold + smoke test).
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| **CORE-01** | Fork trycua/cua to ~/dev/cua-maximalist with Python overlay scaffold above libs/cua-driver/ | §"Repository Topology" + §"uv + Postgres setup" |
| **CORE-02** | Hook into ToolRegistry.swift:55-97 post-action callback to emit structured events to Python overlay | §"ToolRegistry hook strategy" — verified file:line, NO Swift edit needed (proxy pattern) |
| **CORE-03** | Initialize app classifier — bundleID → AppProfile with capability probe (AX-rich? .sdef? CDP-port? Tauri/Wails?), cached per-bundle per-session | §"AppProfile capability probe" — full probe sequence with timeouts + cache schema |
| **STATE-01** | Typed-graph state model: UIElement{...all fields...} | §"State graph: UIElement schema" — Pydantic v2 model + composite key |
| **STATE-02** | Causal DAG of action → state delta | §"Causal DAG" — pre/post StateNode pair per action, edges typed |
| **STATE-03** | Temporal ring buffer (last 5 frames) | §"Ring buffer" — collections.deque(maxlen=5), in-memory only |
| **VERIFY-01** | AXObserver subscription manager — subscribe to kAXValueChanged etc. BEFORE action fires | §"AXObserver bridge" — full notif list + CFRunLoop bridge pattern |
| **VERIFY-02** | NSWorkspace + DistributedNotificationCenter + CDP DOM mutation + kqueue EVFILT_PROC subscriptions | §"Other push sources" — each source's threading model + asyncio bridge |
| **VERIFY-03** | Event aggregator with weighted vote per action class | §"Event aggregator" — weight table + threshold table per action class |
| **VERIFY-04** | L0 push events (0ms, already subscribed) — primary signal | §"L0 push verifier" — budget + observer wiring |
| **VERIFY-05** | L1 cheap diff (1-5ms) — CGWindowList diff, NSPasteboard.changeCount, pixel ROI dHash | §"L1 cheap-diff" — three sub-checks with PyObjC call patterns |
| **VERIFY-06** | L2 medium (50-200ms) — Vision OCR text diff (ROI), AX depth-limited subtree (3 levels MAX) | §"L2 medium" — ocrmac + bounded AX walker; Phase 1 includes scaffolding only |
| **VERIFY-07** | L3 LLM fallback (300-800ms) — only when ensemble confidence < 0.30 | §"L3 LLM contract" — Pydantic stub interface; real implementation Phase 4 |
| **PERSIST-01** | Each translator call wrapped as durable step (LangGraph PostgresSaver, local Postgres) | §"Durable execution scaffold" — minimal wrapper for Phase 1 (only verifier nodes durable) |
| **PERSIST-02** | ~/.cua/sessions/<id>/ structure | §"Session directory layout" — full tree creation at session start |
| **PERSIST-03** | Crash → resume from last verified step | §"Crash-resume scaffold" — Phase 1 demonstrates contract via smoke test |
| **MCP-01** | Maintain trycua/cua's existing MCP server surface | §"MCP proxy strategy" — option A (proxy), no Swift edits |
| **MCP-02** | Expose self-healing wrapper as MCP tools | §"MCP proxy strategy" — FastMCP composition |
</phase_requirements>

---

## Standard Stack

### Core (locked from STACK.md — DO NOT propose alternatives)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| **Python** | 3.12 | Overlay primary language | sweet spot for asyncio + PyObjC 12.1 + structlog typing [VERIFIED: STACK.md] |
| **uv** | latest | Package manager + venv | 10-100× pip; what trycua uses [VERIFIED: STACK.md] |
| **PyObjC** | 12.1 (Nov 2025) | Bridge to all macOS frameworks (AX, Vision, AppKit, Foundation) | Active, supports macOS 26 Tahoe [VERIFIED: pypi 2026-04-29] |
| **anyio** | 4.x | Structured concurrency / task groups | `create_task_group` has correct cancellation semantics that bare `asyncio.wait` botches [VERIFIED: STACK.md] |
| **Pydantic** | v2 latest | Typed schemas (UIElement, ActionCanonical, HoarePre/Post, AppProfile) | every state node + every IPC message [VERIFIED: STACK.md] |
| **structlog** | 25.5.0 (Oct 2025) | Structured NDJSON event logging | bind_contextvars + asyncio task-group context propagation [VERIFIED: pypi 2025-10-27] |
| **ImageHash** | 4.3.2 (Feb 2025) | dHash/pHash/wHash for L1 ROI verifier | pure NumPy, 64-bit hashes, Hamming compare [VERIFIED: pypi 2025-02-01] |
| **Pillow** | latest (transitive) | PNG/JPEG encode + crop for ROI hashing | required by ImageHash [VERIFIED: STACK.md] |
| **ocrmac** | 1.0.1 (Jan 2026) | VNRecognizeTextRequest wrapper | thin shim over pyobjc-framework-Vision [VERIFIED: pypi 2026-01-08] |
| **psycopg** | 3.x (binary) | Postgres async driver | required by langgraph-checkpoint-postgres [VERIFIED: STACK.md] |
| **langgraph-checkpoint-postgres** | 3.0.5 (Mar 2026) | AsyncPostgresSaver for durable step | persists graph state per node [VERIFIED: pypi 2026-03-18] |
| **langgraph** | 0.2+ (transitive) | Graph runtime for durable steps | required by checkpoint-postgres [VERIFIED: STACK.md compat table] |
| **mcp** | latest | MCP Python SDK (FastMCP) | trycua already uses `from mcp.server.fastmcp import FastMCP` [VERIFIED: trycua/libs/python/mcp-server/mcp_server/server.py:26] |

### Supporting (Phase 1 specific)

| Library | Version | Purpose | When |
|---------|---------|---------|------|
| **httpx** | 0.27+ | reserved for L3 LLM call (Phase 4); included for IPC HTTP if needed | scaffolding only in Phase 1 |
| **pytest** | 8.x | Test runner | every Phase 1 unit + integration test |
| **pytest-asyncio** | 0.23+ | async test fixtures | every async test |
| **mypy** | 1.x | Type checking on Pydantic + structlog | CI gate |
| **ruff** | latest | Linter + formatter | CI gate |
| **rich** | latest | TTY pretty-print of action log during dev | dev convenience only |

### Out of Phase 1 (locked stack but not used until later phases)

| Library | Phase | Why Not Phase 1 |
|---------|-------|-----------------|
| py-applescript 1.0.3 | Phase 2 | T3 translator |
| mlx-vlm 0.4.4 | Phase 4 | UI-TARS / ShowUI grounder |
| apple-fm-sdk 0.1.1 | Phase 4 | Tier-0 binary classifier |
| anthropic, openai SDKs | Phase 4 | Cognition layer |
| faiss-cpu 1.13.2 | Phase 4 | Episodic memory (STATE-04) |
| cdp-use | Phase 2 | T2 CDP translator |

**Installation (Phase 1 subset):**
```bash
uv venv --python 3.12
source .venv/bin/activate

uv pip install \
  pyobjc==12.1 \
  ocrmac==1.0.1 \
  ImageHash==4.3.2 \
  Pillow \
  structlog==25.5.0 \
  langgraph-checkpoint-postgres==3.0.5 \
  psycopg[binary] \
  pydantic \
  anyio \
  mcp \
  httpx \
  rich

uv pip install -D pytest pytest-asyncio mypy ruff

# Local infra (one-time)
brew install postgresql@16
brew services start postgresql@16
createdb cua_maximalist
```

**Version verification:** All versions listed are LIVE-VERIFIED in STACK.md as of 2026-04-29. Re-verify if Phase 1 starts >30 days later. [CITED: .planning/research/STACK.md "Sources / Verified live (2026-04-29)"]

---

## Repository Topology (CORE-01)

Per ARCHITECTURE.md L1-L18 and the locked component map:

```
~/dev/cua-maximalist/
├── libs/                              # UNTOUCHED — vendored from trycua/cua
│   └── cua-driver/                    # Swift driver, NEVER edit
│       └── Sources/CuaDriverServer/
│           └── ToolRegistry.swift     # post-action hook lives here (line 55-97)
├── libs/python/                       # UNTOUCHED — trycua's Python packages
│   └── mcp-server/                    # we PROXY this, do not modify
│
├── overlay/                           # OUR PYTHON CODE (Phase 1 builds the skeleton)
│   ├── __init__.py
│   ├── ipc/
│   │   ├── __init__.py
│   │   └── swift_bridge.py            # JSONL stdio to cua-driver subprocess (Phase 2 wires actions; Phase 1 wires events)
│   ├── ax/                            # raw PyObjC HIServices wrappers + atomacos forked helpers
│   │   ├── __init__.py
│   │   ├── element.py                 # AXUIElement wrapper
│   │   ├── observer.py                # AXObserver + CFRunLoop bridge ← KEY FOR PHASE 1
│   │   ├── rate_limit.py              # 20-tok/sec/pid token bucket
│   │   └── walker.py                  # depth-limited subtree walker (3 levels max)
│   ├── state/
│   │   ├── __init__.py
│   │   ├── graph.py                   # UIElement + edges
│   │   ├── causal_dag.py              # action → state delta
│   │   ├── ring_buffer.py             # last 5 frames
│   │   ├── fingerprint.py             # composite key (role_path + label + bbox_centroid)
│   │   └── snapshot.py                # serialize / restore
│   ├── profile/
│   │   ├── __init__.py
│   │   ├── classifier.py              # bundleID → AppProfile router
│   │   ├── capability_probe.py        # AX/AS/CDP/Tauri probe
│   │   └── cache.py                   # ~/.cua/profiles/<bundle>.json
│   ├── verifier/
│   │   ├── __init__.py
│   │   ├── axobserver.py              # subscribe-before-fire wrapper
│   │   ├── nsworkspace.py             # NSWorkspaceWillLaunchApplicationNotification etc.
│   │   ├── distnotif.py               # NSDistributedNotificationCenter
│   │   ├── kqueue_proc.py             # EVFILT_PROC for process exit
│   │   ├── aggregator.py              # weighted vote per action class
│   │   └── ensemble/
│   │       ├── __init__.py
│   │       ├── l0_push.py             # zero-latency push tier
│   │       ├── l1_cheap.py            # CGWindowList + Pasteboard + dHash
│   │       ├── l2_medium.py           # ocrmac + bounded AX walk (Phase 1: scaffold only)
│   │       ├── l3_llm.py              # Pydantic contract stub (Phase 4: implement)
│   │       └── weighted_vote.py
│   ├── persist/
│   │   ├── __init__.py
│   │   ├── session_writer.py          # ~/.cua/sessions/<id>/ tree
│   │   ├── snapshot_io.py
│   │   └── durable_step.py            # AsyncPostgresSaver wrapper (Phase 1 minimal)
│   ├── mcp_server.py                  # Python FastMCP that proxies trycua + adds healing tools
│   └── log.py                         # structlog setup → action_log.ndjson
│
├── tests/
│   ├── conftest.py                    # pytest-asyncio fixtures
│   ├── unit/
│   │   ├── test_state_graph.py
│   │   ├── test_fingerprint.py
│   │   ├── test_app_profile.py
│   │   ├── test_axobserver.py
│   │   └── test_aggregator.py
│   └── integration/
│       ├── test_calculator_click.py   # ← THE Phase 1 success demo
│       ├── test_session_persistence.py
│       └── test_mcp_proxy.py
│
├── pyproject.toml
├── uv.lock
└── CLAUDE.md
```

**Why flat under `overlay/` not deep package:** matches browser-harness's flat layout (which Akeil uses daily) per ARCHITECTURE.md L631 reference. Skyvern's deep `forge/sdk` is over-engineered for ~2000-LOC scope. [CITED: ARCHITECTURE.md L631]

**Module naming (Claude's discretion):** I recommend `overlay/` (not `cua_overlay/`) because:
- Matches the architecture doc's component map verbatim (ARCHITECTURE.md L31).
- Short import path (`from overlay.state.graph import UIElement`).
- Avoids namespace collision with hypothetical future `cua` package from trycua.

---

## ToolRegistry Hook Strategy (CORE-02)

### Verified location

`~/thinker/research-clones/trycua-cua/libs/cua-driver/Sources/CuaDriverServer/ToolRegistry.swift`

[VERIFIED: file read 2026-04-29] Lines 55-97 contain the `call(_:arguments:)` method:
- Line 61-62: monotonic start time captured (`clock_gettime_nsec_np(CLOCK_UPTIME_RAW)`).
- Line 64: `let result = try await handler.invoke(arguments)` — the action fires.
- Lines 66-94: post-action hook, gated on `RecordingSession.shared.isEnabled()` — currently invokes `RecordingSession.shared.record(...)` with toolName/args/pid/clickPoint/resultSummary.
- Line 34-45: `actionToolNames` set: `{click, right_click, drag, scroll, type_text, type_text_chars, press_key, hotkey, set_value, page}`.

### Hook strategy: PROXY, NOT EDIT

**The hard rule:** Phase 1 must NOT edit Swift code in `libs/cua-driver/`. So we cannot inject our event emitter into ToolRegistry directly.

**Two viable approaches:**

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **A. Python MCP proxy wraps trycua's MCP server** — our `overlay/mcp_server.py` registers all of trycua's tool names + emits a structured event before/after delegating to trycua's tool. | No Swift edit. Pure Python. Survives upstream rebases. | Doubles the IPC hop (Claude→our MCP→trycua MCP→cua-driver). Extra ~5-20ms per call. | **CHOSEN** for Phase 1 |
| B. Patch ToolRegistry.swift at build time via a post-checkout hook | Single-hop IPC | Forbidden (CLAUDE.md hard rule + brittle vs upstream) | REJECTED |
| C. DYLD_INSERT_LIBRARIES into the cua-driver process to swizzle ToolRegistry | True interception, no double-hop | SIP-off requirement; arm64e signing; Phase 6 tier | DEFERRED to Phase 6 |
| D. Read trycua's existing `RecordingSession` output stream | Already exists; line 86 calls `RecordingSession.shared.record` | RecordingSession is internal, no public stream out [VERIFIED: grep showed no public socket/file emit point] | NOT VIABLE |

**Approach A details — the proxy contract:**

```python
# overlay/mcp_server.py (sketch)
from mcp.server.fastmcp import FastMCP
from mcp.client.stdio import stdio_client  # spawns trycua's MCP as subprocess

server = FastMCP(name="cua-maximalist")

# 1. Spawn trycua's MCP server as a subprocess via stdio
trycua_client = await stdio_client(command="python", args=["-m", "mcp_server"])

# 2. Mirror every tycua tool, wrapping with verifier subscribe → invoke → emit
@server.tool()
async def click(ctx, **args):
    # PRE: subscribe AX notifications on target element BEFORE invoking
    expected = await verifier.expect(target=args["target"], notifs=["AXValueChanged"])
    # FIRE: delegate to trycua's MCP click tool
    result = await trycua_client.call_tool("click", args)
    # POST: wait for verifier or fall to L1
    confidence = await verifier.aggregate(expected, action_class="click")
    # LOG: append to action_log.ndjson
    structlog.get_logger().info("click_verified", confidence=confidence, ...)
    return result

# 3. Add new self-healing tools
@server.tool()
async def click_with_healing(ctx, **args):
    """New tool: includes Phase 3 recovery branches."""
    ...
```

**Reference for proxy pattern:** trycua's own MCP server uses FastMCP + ComputerAgent in its `serve()` function [VERIFIED: trycua/libs/python/mcp-server/mcp_server/server.py:118-170]. We use the same FastMCP class but spawn trycua as subprocess via `mcp.client.stdio`.

**OPEN QUESTION (planner to resolve):** trycua's MCP exposes `screenshot_cua` and `run_cua_task` at the high level [VERIFIED: server.py:124, 139] — those are AGENT-level tools, not primitive `click`/`type_text`. The primitive tools live in `cua-driver` Swift. Two options:

1. **(A1)** Proxy at the MCP level: our overlay only sees `screenshot_cua`/`run_cua_task` and adds event emission around them. Less granular but no Swift dependency.
2. **(A2)** Talk directly to `cua-driver` over its own MCP socket (it IS an MCP server itself per `import MCP` in ToolRegistry.swift L4). Granular per-tool hooks, but requires understanding trycua's transport binding.

**Recommendation:** A2 — `cua-driver` is itself an MCP server. We wrap its socket directly. This gives us per-tool hooks without Swift edits. The planner should verify by inspecting `trycua-cua/libs/cua-driver/Sources/CuaDriverServer/main.swift` (or equivalent entry point) to confirm the transport.

[CITED: trycua/libs/cua-driver/Sources/CuaDriverServer/ToolRegistry.swift:1-4 — confirms MCP import]

---

## AppProfile Capability Probe (CORE-03)

### What we're probing

Per architecture doc and PROJECT.md row "Initialize app classifier — bundleID → AppProfile":

| Capability | What it means | Probe method |
|------------|---------------|--------------|
| `ax_rich` | App exposes a usable AXUIElement tree (>0 children, kAXEnabled) | `AXUIElementCopyAttributeValue(app, kAXChildrenAttribute, ...)` returns >0 children within 200ms |
| `ax_observer_works` | AXObserver notifications actually fire (Pitfall 14: silently fails on web/Electron) | Subscribe to `kAXFocusedUIElementChanged`, fire a no-op AppleScript focus call, see if observer fires within 500ms |
| `applescript_sdef` | App has scripting dictionary (.sdef) | `[NSWorkspace URLForApplicationWithBundleIdentifier:]` → read Info.plist `NSAppleScriptEnabled` AND `OSAScriptingDefinition` keys |
| `cdp_port` | Electron app started with `--remote-debugging-port` and exposes localhost endpoint | poke `localhost:9222..9230/json/version` with 100ms timeout per port |
| `tauri_or_wails` | App is a Tauri/Wails app (has WKWebView but no .sdef and no CDP) | Info.plist contains `NSPrincipalClass = NSApplication` AND linked frameworks include `WebKit.framework` (via `otool -L` parse, cached) |
| `electron` | Bundle is Electron (look for `Electron Framework.framework` in `Frameworks/`) | filesystem stat at `<bundle>/Contents/Frameworks/Electron Framework.framework` |
| `bundle_path` | Resolved path on disk | `[NSWorkspace URLForApplicationWithBundleIdentifier:]` |
| `bundle_version` | Short version + build number | Info.plist `CFBundleShortVersionString` + `CFBundleVersion` (used to invalidate cache on upgrade — Pitfall 16) |
| `tcc_axenabled` | Process has Accessibility permission | `AXIsProcessTrusted()` (system-wide, not per-bundle) — recheck on every probe per Pitfall 24 |

### Probe sequence (with latency budget)

Run probes IN PARALLEL where possible — total budget **<500ms** per first-time bundle, **<5ms** on cached re-probe.

```python
async def probe(bundle_id: str, pid: int) -> AppProfile:
    # FAST CHECKS (sync, ~5ms each)
    bundle_path = NSWorkspace.shared.urlForApplicationWithBundleIdentifier(bundle_id)
    info_plist = parse_info_plist(bundle_path / "Contents/Info.plist")
    has_sdef = info_plist.get("OSAScriptingDefinition") is not None
    is_electron = (bundle_path / "Contents/Frameworks/Electron Framework.framework").exists()

    # PARALLEL ASYNC CHECKS (200ms timeout each)
    async with anyio.create_task_group() as tg:
        ax_task = tg.start_soon(probe_ax_rich, pid)
        cdp_task = tg.start_soon(probe_cdp_ports, pid) if is_electron else None
        observer_task = tg.start_soon(probe_observer_fires, pid)

    return AppProfile(
        bundle_id=bundle_id,
        bundle_version=info_plist.get("CFBundleShortVersionString"),
        ax_rich=ax_task.result(),
        ax_observer_works=observer_task.result(),
        applescript_sdef=has_sdef,
        cdp_port=cdp_task.result() if cdp_task else None,
        tauri_or_wails=detect_tauri(info_plist),
        electron=is_electron,
        probed_at=datetime.now(),
    )
```

### Cache schema

Per ARCHITECTURE.md L386: `~/.cua/profiles/<bundleID>.json`

```json
{
  "bundle_id": "com.apple.Calculator",
  "bundle_version": "10.16",
  "bundle_build": "26.4.30.1",
  "ax_rich": true,
  "ax_observer_works": true,
  "applescript_sdef": false,
  "cdp_port": null,
  "tauri_or_wails": false,
  "electron": false,
  "translator_priority": ["T1", "T3", "T5"],
  "probed_at": "2026-04-29T14:32:11Z",
  "probe_latency_ms": 312
}
```

**Cache invalidation:** if `bundle_version` OR `bundle_build` differs from cached, re-probe. Per Pitfall 16, schema drift breaks SQLite reads — apply same logic here for capabilities.

**Survives session restart:** the JSON is on disk, not in memory. Success criterion 3 satisfied. [CITED: ROADMAP.md Phase 1 success criterion 3]

### Pitfalls in the probe itself

- **Pitfall 14 (AX notifs fail on web/Electron):** the `ax_observer_works` check is what makes Phase 1 robust. If false, downstream Phase 2 routes to T2 CDP for verification on that bundle.
- **Pitfall 24 (TCC mid-session):** call `AXIsProcessTrusted()` on every probe, NOT just at startup.
- **Pitfall 8 (Electron CDP launch-only):** if `is_electron AND cdp_port == None`, the profile should record `cdp_available_after_relaunch=True` so Phase 2 can prompt user.

[ASSUMED] Tauri/Wails detection via WebKit.framework symbol presence — needs spike. There may be a more reliable signal (e.g., string match on bundle's main executable for "tauri" or "wails"). Planner: include 30-min spike to confirm heuristic.

---

## State Graph: UIElement Schema (STATE-01)

### Pydantic v2 model

Per ARCHITECTURE.md L40-49 schema and PROJECT.md STATE-01:

```python
# overlay/state/graph.py
from datetime import datetime
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field

class Bbox(BaseModel):
    x: float
    y: float
    w: float
    h: float

    @property
    def centroid(self) -> tuple[int, int]:
        # rounded to 4px grid for stable composite key
        return (round((self.x + self.w / 2) / 4) * 4,
                round((self.y + self.h / 2) / 4) * 4)

class Capability(str, Enum):
    PRESS = "press"            # kAXPressAction
    INCREMENT = "increment"    # kAXIncrement
    DECREMENT = "decrement"
    SHOWMENU = "show_menu"
    PICK = "pick"
    SET_VALUE = "set_value"
    FOCUS = "focus"

class Source(str, Enum):
    AX = "ax"           # T1
    CDP = "cdp"         # T2
    APPLESCRIPT = "as"  # T3
    OCR = "ocr"         # T4
    PIXEL = "pixel"     # T5

class UIElement(BaseModel):
    # Identity (composite key — NEVER raw AXUIElement ref)
    role: str                         # AXButton, AXWindow, AXTextField, ...
    role_path: str                    # "AXApplication/AXWindow[0]/AXGroup/AXButton[3]"
    label: str                        # AXTitle / AXLabel / AXValue (whichever non-empty, in priority order)
    ax_identifier: Optional[str] = None  # AXIdentifier if present (most stable signal)
    bbox: Bbox

    # Capabilities & state
    value: Optional[str] = None
    enabled: bool = True
    focused: bool = False
    capabilities: list[Capability] = Field(default_factory=list)
    confidence: float = 1.0           # 0.0-1.0, lowered when L2 truncated etc.
    source: list[Source] = Field(default_factory=list)  # T1+T4 means both saw it

    # Reserved for later phases (Phase 4+)
    visual_embedding: Optional[bytes] = None  # FAISS vector — Phase 4 STATE-04
    ocr_text: Optional[str] = None             # set by T4 ocrmac in Phase 2
    pixel_hash: Optional[str] = None           # dHash hex of bbox crop

    # Causal links (filled by causal_dag.py — STATE-02)
    caused_by: Optional[str] = None            # ActionCanonical.id
    causes: list[str] = Field(default_factory=list)

    # Episodic ref (Phase 4)
    episodic_ref: Optional[str] = None

    # History (filled by ring_buffer.py — STATE-03)
    history_ids: list[str] = Field(default_factory=list)  # last 5 prior versions of this element

    # Metadata
    discovered_at: datetime
    last_seen_at: datetime
    pid: int
    bundle_id: str
    window_id: int

    @property
    def composite_key(self) -> str:
        """Stable identity that survives app restart, React re-renders.

        Order of preference per AX-tree paper 2603.20358:
        1. AXIdentifier (most stable)
        2. role_path + label
        3. role + bbox_centroid (fallback)
        """
        if self.ax_identifier:
            return f"axid:{self.bundle_id}:{self.ax_identifier}"
        if self.role_path and self.label:
            return f"path:{self.bundle_id}:{self.role_path}:{self.label}"
        cx, cy = self.bbox.centroid
        return f"bbox:{self.bundle_id}:{self.role}:{cx}:{cy}"
```

### Composite key strategy (CRITICAL)

Per Pitfall 13 and the architecture doc anti-pattern 3:

> **Anti-Pattern 3: AX element ID as identity** — Treating `AXUIElement` pointer-identity as stable is wrong. React/SwiftUI re-renders break this every keystroke. Use `(role_path, label, bbox_centroid)` composite key.

**Tier ladder for `composite_key` (10-tier locator hierarchy from AX-tree paper 2603.20358, simplified to 3 tiers for Phase 1):**

| Tier | Key | When stable | When unstable |
|------|-----|-------------|---------------|
| 1 | `AXIdentifier` | App developer set it explicitly (rare on macOS, common on iOS-derived Catalyst) | App didn't set it |
| 2 | `role_path + label` | Stable across re-renders if label is stable text (button title, menu item) | Dynamic labels (e.g., counters), localized strings change |
| 3 | `role + bbox_centroid` (4px grid) | Element is in a fixed grid layout | Resizable windows, flex/auto-layout |

**Phase 1 implementation:** all three tiers; `composite_key` returns the highest-tier non-null value. Phase 3 cache write-back upgrades stale tier-3 keys to tier-2 when AX subtree reveals stable role_path.

**Why 4px grid for bbox_centroid:** retina pixel jitter on bbox computation can be ±2px; 4px bucketing absorbs this without losing locality. [ASSUMED] — needs validation in integration test (probe Calculator buttons twice, assert bbox_centroid stable).

**Collision strategy:** if two siblings have identical (role, label, ax_identifier=None), the role_path includes a sibling index `AXButton[3]` — that disambiguates. The walker emits sibling index on every node by default. Per ARCHITECTURE.md L469.

### Edges

Per architecture doc L46:

```python
class EdgeKind(str, Enum):
    CONTAINS = "contains"      # parent → child (AX hierarchy)
    ENABLES = "enables"        # focus on input → submit button enabled
    TRIGGERS = "triggers"      # click button → opens window
    PRECEDES = "precedes"      # in ring buffer, t-1 → t

class Edge(BaseModel):
    src: str   # composite_key
    dst: str   # composite_key
    kind: EdgeKind
    timestamp_ns: int
```

`ENABLES` and `TRIGGERS` are filled by causal_dag.py (STATE-02) AFTER an action's pre/post snapshot. Phase 1 only writes `CONTAINS` and `PRECEDES` (filled by walker and ring_buffer respectively).

### State graph store

In-memory Phase 1 (per ARCHITECTURE.md L286 — "in-memory only to start"). Two dicts:

```python
class StateGraph:
    nodes: dict[str, UIElement] = {}     # composite_key → UIElement
    edges: list[Edge] = []
    ring: deque[StateNode] = deque(maxlen=5)  # last 5 frames (STATE-03)
```

Persistence (PERSIST-01) snapshots this dict to `~/.cua/sessions/<id>/snapshot.json` via `state/snapshot.py`. Postgres durability (LangGraph) is reserved for the action+verify graph nodes, not the UI element store (too chatty).

[CITED: ARCHITECTURE.md L491 "State graph size: snapshot every 60s, prune nodes >5min stale"]

---

## Causal DAG (STATE-02)

Per architecture doc L47:

```python
# overlay/state/causal_dag.py
class ActionCanonical(BaseModel):
    """The Pydantic contract for an action — canonical across all tiers/channels."""
    id: str                  # UUID monotonic — also used as idempotency token
    step_idx: int            # monotonic per-session counter
    kind: Literal["READ", "MUTATE"]   # speculation-safety per Pitfall 22
    target_key: str          # UIElement.composite_key
    action_type: str         # "click", "type", "scroll", "set_value"
    payload: dict            # action-specific args
    tier: Optional[Literal["T1","T2","T3","T4","T5"]] = None  # filled by translator (Phase 2)
    channel: Optional[Literal["C1","C2","C3","C4","C5"]] = None
    timestamp_ns: int
    session_id: str

class HoarePre(BaseModel):
    """Pre-condition assertion before action fires."""
    target_key: str
    target_exists: bool
    target_enabled: bool
    target_role: str
    role_compatible: bool        # role ∈ A.compatible_roles
    frontmost_app: str
    no_blocking_modal: bool      # Pitfall 25
    timestamp_ns: int

class HoarePost(BaseModel):
    """Post-condition (verifier output)."""
    target_key: str
    confidence: float            # weighted vote across L0+L1+L2+L3
    tier_signals: dict[str, float]   # {"L0": 0.8, "L1": 0.3, "L2": None, "L3": None}
    verified: bool               # confidence ≥ 0.50
    healed_to: Optional[str]     # if cache write-back replaced the locator
    timestamp_ns: int
```

**Causal edge writing (Phase 1):**

```python
# Before action: capture state snapshot S_pre (subset of state graph touching target)
# After action: capture S_post
# Diff: nodes that appeared, disappeared, or changed
# For each changed node: causal_dag.add_edge(src=action.id, dst=node.composite_key, kind=TRIGGERS)
# For new node: causal_dag.add_edge(src=action.id, dst=node.composite_key, kind=TRIGGERS)
```

**Phase 1 scope:** Phase 1 doesn't fire actions of its own — but the smoke test (Calculator click) DOES fire one. The test asserts that:
1. Pre-snapshot taken before fire (HoarePre populated).
2. Push event observed within 50ms (HoarePost.tier_signals["L0"] > 0).
3. Causal edge `(action.id) --TRIGGERS-> (button.composite_key)` written to `causal_dag`.

---

## Temporal Ring Buffer (STATE-03)

Per architecture doc L48 and PROJECT.md STATE-03:

```python
# overlay/state/ring_buffer.py
from collections import deque

class TemporalRingBuffer:
    """Last 5 frames of state graph snapshots, in-memory only (not Postgres)."""
    def __init__(self, maxlen: int = 5):
        self.frames: deque[StateSnapshot] = deque(maxlen=maxlen)

    def push(self, snapshot: StateSnapshot) -> None:
        self.frames.append(snapshot)
        # PRECEDES edges: t-1 → t for each shared composite_key
        if len(self.frames) > 1:
            self._link_precedes(self.frames[-2], self.frames[-1])
```

**Why deque(maxlen=5):** O(1) append, automatic eviction, thread-safe-ish (but we wrap in asyncio.Lock for the writer).

**Why in-memory only:** snapshotting 5 full state graphs to Postgres on every action would be ~5MB/sec of writes for a busy session. Per ARCHITECTURE.md L491, prune > 5min stale. Postgres is reserved for verified-action checkpoints, not raw frames.

---

## Push-Event Verifier (VERIFY-01..03)

This is **the most architecturally critical part of Phase 1**. Per PROJECT.md key decision: "Push-event subscription as primary verifier — fires <1ms via Mach port, no before/after snapshot needed; deterministic; production systems all miss this."

### AXObserver Bridge

#### The threading problem

PyObjC's `AXObserverCreate` requires a `CFRunLoop` to deliver callbacks. Asyncio owns the main thread's event loop. Bridging the two reliably is the single hardest integration task in Phase 1.

**Two patterns:**

| Pattern | How | Pros | Cons |
|---------|-----|------|------|
| **A. Dedicated CFRunLoop thread + asyncio.Queue bridge** | Spawn `threading.Thread(target=lambda: CFRunLoopRun())`. AXObserver callbacks fire on that thread. Each callback calls `loop.call_soon_threadsafe(queue.put_nowait, event)` to hand off to asyncio. | Proven pattern (used by atomacos, MacPaw Screen2AX, ghost-os). Stable across PyObjC versions. | Two threads to coordinate. Slight overhead per event (~5-50µs for `call_soon_threadsafe`). |
| B. libdispatch (`dispatch_get_main_queue`) | Register observer on a serial dispatch queue. PyObjC has limited dispatch support. | macOS-native | PyObjC's `dispatch_*` bindings are incomplete. Risk of seg-fault on macOS 26. [ASSUMED — needs spike] |

**Recommended:** Pattern A. It's what every working Python AX implementation uses (atomacos's `BaseAXUIElement` — to be partially forked per STACK.md).

**Reference implementation sketch:**

```python
# overlay/ax/observer.py
import threading
from CoreFoundation import CFRunLoopRun, CFRunLoopGetCurrent, kCFRunLoopDefaultMode, CFRunLoopAddSource
from HIServices import (
    AXObserverCreate,
    AXObserverAddNotification,
    AXObserverGetRunLoopSource,
)

class AXEventBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue()
        self.observers: dict[int, AXObserver] = {}  # pid → AXObserver
        self._thread: threading.Thread | None = None
        self._cfrunloop = None

    def start(self) -> None:
        ready = threading.Event()
        def _runloop_target():
            self._cfrunloop = CFRunLoopGetCurrent()
            ready.set()
            CFRunLoopRun()  # blocks
        self._thread = threading.Thread(target=_runloop_target, daemon=True)
        self._thread.start()
        ready.wait(timeout=2.0)  # wait for CFRunLoop to be live

    def subscribe(self, pid: int, element, notifications: list[str], action_id: str) -> SubscriptionHandle:
        observer = self._get_or_create_observer(pid)
        for notif in notifications:
            err = AXObserverAddNotification(observer, element, notif, action_id)
            # err handling: kAXErrorNotificationAlreadyRegistered means we already listen — ok
            ...
        return SubscriptionHandle(...)

    def _on_notification(self, observer, element, notif_name, user_info):
        # CALLBACK FIRES ON CFRunLoop THREAD — NOT asyncio thread!
        event = AXEvent(
            pid=...,
            element_key=...,
            notif=notif_name,
            user_info=user_info,
            event_ts_ns=time.monotonic_ns(),
            action_id=user_info,  # we passed action_id as the refcon
        )
        self.loop.call_soon_threadsafe(self.queue.put_nowait, event)
```

#### Pre-subscribe pattern (the secret weapon)

Per ARCHITECTURE.md L408-426 Pattern 1:

```python
# verifier/axobserver.py
class AXObserverManager:
    async def expect(self, target: UIElement, notifs: list[str], action_id: str, timeout_ms: int = 500) -> EventFuture:
        """Subscribe to expected push events BEFORE firing the action.

        Returns a future that resolves when ANY of the notifications fires
        (or rejects on timeout).

        CRITICAL: caller MUST await this BEFORE calling action.fire().
        Otherwise stale notifications from before subscription can race the verifier.
        """
        fut = asyncio.get_running_loop().create_future()
        sub = self._bridge.subscribe(
            pid=target.pid,
            element=target.ax_element,
            notifications=notifs,
            action_id=action_id,
        )
        sub.subscription_ts_ns = time.monotonic_ns()  # for stale-event filtering (Pitfall 28)

        # Filter callback: only resolve future if event is post-subscription AND action_id matches
        def _filter(event: AXEvent):
            if event.event_ts_ns < sub.subscription_ts_ns + 5_000_000:  # 5ms guard
                return  # stale notification — discard
            if event.action_id != action_id:
                return  # someone else's event
            if not fut.done():
                fut.set_result(event)

        sub.set_filter(_filter)
        return fut
```

**Why the 5ms guard:** Pitfall 28 — stale notifications from in-flight kAXValueChanged events that happened ~50ms BEFORE our action can race the verifier. The architecture doc explicitly mitigates this.

#### Notifications subscribed (per VERIFY-01)

Per PROJECT.md VERIFY-01:

| Notification | When it fires | Used for |
|--------------|---------------|----------|
| `kAXValueChanged` | text/value of an element changed | type, set_value, calculator click result |
| `kAXFocusedUIElementChanged` | focus moved to a different element | tab key, click that focuses input |
| `kAXWindowCreated` | new window appeared | dialog opened, new tab |
| `kAXTitleChanged` | window or element title changed | navigation, document save |
| `kAXLayoutChanged` | element bbox changed | scroll, resize |
| `kAXSelectedTextChanged` | text selection changed | type-to-replace, drag-select |
| `kAXSelectedRowsChanged` | table/list selection changed | list click |

[CITED: PROJECT.md L48 / VERIFY-01]

### Other push sources (VERIFY-02)

| Source | Threading | asyncio bridge | Used for |
|--------|-----------|----------------|----------|
| **NSWorkspace notifications** | NSNotificationCenter on main thread (or any registered queue) | Register on a dedicated NSOperationQueue; callback uses `call_soon_threadsafe` | App launch/quit, frontmost app change |
| **NSDistributedNotificationCenter** | System-wide IPC, delivered on main thread | same pattern | iCloud sync, system events |
| **CDP DOM mutation events** | WebSocket frames on asyncio task | Native asyncio (no bridge needed) | Phase 2 wires this; Phase 1 defines event contract |
| **kqueue EVFILT_PROC** | kernel kqueue fd | `loop.add_reader(fd, callback)` — pure asyncio | Process exit (NOTE_EXIT) |

**Phase 1 scope:** wire AXObserver fully (it's the primary signal), wire NSWorkspace lightly (just frontmost-app changes), define CDP DOM event contract as Pydantic schema (no implementation), wire kqueue EVFILT_PROC for the demo (so we know if Calculator quits mid-test).

### Event Aggregator (VERIFY-03)

Per PROJECT.md VERIFY-03 — "Event aggregator with weighted vote per action class":

```python
# verifier/aggregator.py
class WeightedVote:
    """Per-action-class weighting of which signals count."""
    # weights are deliberate — based on architecture doc + research papers
    WEIGHTS: dict[str, dict[str, float]] = {
        "click": {
            "ax.value_changed": 0.6,
            "ax.focused_changed": 0.4,
            "cdp.dom_modified": 0.6,    # for web/Electron
            "l1.window_diff": 0.3,
            "l1.pixel_dhash": 0.3,
        },
        "type": {
            "ax.value_changed": 0.8,
            "ax.selected_text_changed": 0.5,
            "cdp.dom_attribute_modified": 0.7,
            "l1.pasteboard_unchanged": 0.1,  # negative signal: pasteboard didn't move
        },
        "scroll": {
            "ax.layout_changed": 0.7,
            "l1.window_diff": 0.5,
            "l1.pixel_dhash": 0.4,
        },
        "set_value": {
            "ax.value_changed": 0.9,
        },
        # ... per ToolRegistry.actionToolNames
    }

    def aggregate(self, action_class: str, signals: dict[str, float]) -> float:
        """Returns confidence in [0.0, 1.0]. ≥ 0.50 = VERIFIED."""
        weights = self.WEIGHTS.get(action_class, {})
        total_weight = sum(weights.values())
        weighted_sum = sum(signals.get(k, 0.0) * w for k, w in weights.items())
        return weighted_sum / total_weight if total_weight else 0.0
```

**Threshold:** confidence ≥ 0.50 → VERIFIED. Confidence < 0.30 → escalate to L3 (Phase 4). 0.30-0.50 → tentative, log for review.

[CITED: ARCHITECTURE.md L172-173 — "weighted vote → confidence ≥ 0.50 → VERIFIED"]

[ASSUMED] specific weight values — these are starting heuristics. Phase 1 demos with these; production values will be tuned in Phase 3 against real failure data.

---

## L0..L3 Latency Ladder (VERIFY-04..07)

### L0: Push events (0-1ms target)

Already covered above. AXObserver future + CDP DOM event future + kqueue future all wait on the same `asyncio.Queue` consumer.

**Budget:** 0ms (events stream while action is firing). The "wait" is `await asyncio.wait_for(expected, timeout=0.5)` after fire.

### L1: Cheap diff (1-5ms target)

Per VERIFY-05 and PROJECT.md L1 spec, three sub-checks run in parallel:

#### L1a: CGWindowList diff

```python
# verifier/ensemble/l1_cheap.py
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGWindowListExcludeDesktopElements,
    kCGNullWindowID,
)

def cgwindowlist_snapshot() -> dict[int, dict]:
    """Returns {window_id: {title, owner_pid, bounds, level}}."""
    info = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID,
    )
    return {w["kCGWindowNumber"]: {
        "title": w.get("kCGWindowName", ""),
        "owner_pid": w.get("kCGWindowOwnerPID"),
        "bounds": w.get("kCGWindowBounds"),
        "level": w.get("kCGWindowLayer"),
    } for w in info}

def cgwindowlist_diff(before: dict, after: dict) -> dict:
    return {
        "added": [k for k in after if k not in before],
        "removed": [k for k in before if k not in after],
        "title_changed": [k for k in after if k in before and after[k]["title"] != before[k]["title"]],
    }
```

**Latency:** ~1-2ms on a ~50-window system. [VERIFIED: PyObjC/Quartz CGWindowListCopyWindowInfo is documented sub-ms]

#### L1b: NSPasteboard.changeCount

```python
from AppKit import NSPasteboard

def pasteboard_change_count() -> int:
    return NSPasteboard.generalPasteboard().changeCount()
```

**Latency:** <1ms (atomic int read). Used for cmd-c/cmd-v actions and side-channel signals (T5 pixel translator uses clipboard side-channel for value extraction in Phase 2).

#### L1c: Pixel ROI dHash

```python
import imagehash
from PIL import Image

def roi_dhash(screenshot: Image.Image, bbox: Bbox, size: int = 8) -> imagehash.ImageHash:
    """ROI is bbox_centroid ± 50px crop, dHash 8x8 = 64-bit fingerprint."""
    cx, cy = bbox.centroid
    crop = screenshot.crop((cx - 50, cy - 50, cx + 50, cy + 50))
    return imagehash.dhash(crop, hash_size=size)

def dhash_changed(before: imagehash.ImageHash, after: imagehash.ImageHash, threshold: int = 5) -> bool:
    """Hamming distance threshold; 5 bits of 64 = ~8% change."""
    return abs(before - after) > threshold
```

**Screenshot source:** `SCScreenshotManager.captureImage` (modern path) with retry-once fallback per Pitfall 12 (#870 regression). For Phase 1 demo, we can also use `CGDisplayCreateImageForRect` directly — it's deprecated but reliable.

**Latency:** screenshot capture ~5-15ms; crop+hash ~1-2ms. **Total L1c is ~10-20ms** — over budget. **Mitigation:** cache the screenshot once per L1 invocation; share between L1c and L2 OCR. Or capture only the ROI rectangle directly via `CGWindowListCreateImage` with bounds.

[CITED: STACK.md "ImageHash 4.3.2 — dHash, pHash, wHash — pure NumPy; ROI hashing trivial via PIL crop"]

### L2: Medium (50-200ms target)

Per VERIFY-06:

#### L2a: Vision OCR text diff (ROI)

```python
from ocrmac import ocrmac

def l2_ocr_diff(roi_image: Image.Image, expected_text: str | None) -> tuple[float, str]:
    """Returns (confidence, ocr_text). If expected_text matches, high confidence."""
    annotations = ocrmac.OCR(roi_image).recognize()
    text = " ".join(a[0] for a in annotations)
    if expected_text and expected_text in text:
        return (0.9, text)
    return (0.3, text)
```

**Latency:** 50-200ms typical for a 100x100 ROI on macOS 26 with ANE. [VERIFIED: STACK.md §"Vision Framework via PyObjC"]

#### L2b: AX depth-limited subtree

```python
# overlay/ax/walker.py
def walk_subtree(element, max_depth: int = 3, max_children: int = 50, max_nodes: int = 500) -> list[UIElement]:
    """Depth-first AX walk with HARD CAPS. Never recursive without limits.

    Per Pitfall 3: full recursive on Safari = 15-20s. Caps prevent that.
    """
    nodes = []
    def _walk(elem, depth: int):
        if len(nodes) >= max_nodes:
            return  # cap hit, mark truncated=True elsewhere
        if depth > max_depth:
            return
        children = AXUIElementCopyAttributeValue(elem, kAXChildrenAttribute, ...)
        for i, child in enumerate(children[:max_children]):
            nodes.append(_axelem_to_uielement(child, role_path=f"{elem.role_path}/{child.role}[{i}]"))
            _walk(child, depth + 1)
    _walk(element, 0)
    return nodes
```

**Phase 1 scope:** the walker exists and is unit-tested. The L2 verifier code path is wired. But the Calculator demo MUST NOT trigger L2 (success criterion 4) — L0+L1 alone verify in <50ms.

### L3: LLM fallback (300-800ms target)

Per VERIFY-07:

```python
# verifier/ensemble/l3_llm.py
class L3Contract(Protocol):
    """LLM verifier contract — Phase 4 implements; Phase 1 stubs."""
    async def verify(self, screenshot: bytes, expected: HoarePost, actual_signals: dict) -> tuple[float, str]: ...

class L3Stub:
    """Phase 1: returns (0.0, 'L3 not implemented in Phase 1') — never called if L0+L1 pass."""
    async def verify(self, *_, **__) -> tuple[float, str]:
        raise RuntimeError("L3 LLM verifier is Phase 4 — Phase 1 should never reach this path")
```

**Phase 1 scope:** the stub exists and unit tests assert that the Calculator demo NEVER calls it. If L3 is reached in Phase 1, that's a bug — the L0/L1 wiring is wrong.

### Confidence aggregation rule

Per architecture doc L173:

```
verified = aggregator.aggregate(action_class, signals) ≥ 0.50
escalate_to_l3 = aggregator.aggregate(action_class, signals) < 0.30
```

**0.30 threshold reasoning:** weighted vote on push events alone yields ~0.6 if all expected events fire; ~0.3 if half fire. Below 0.3 means most signals failed = real disagreement = needs LLM. [ASSUMED] — needs validation in Phase 4 against real failure data; Phase 1 just hardcodes 0.30.

---

## AX Rate Limiting (Pitfall 2 / cmux #2985)

Per PROJECT.md hard rule: "Never poll AX at >20 calls/sec/pid (cmux #2985 stalls Cocoa main thread)."

### Token-bucket implementation

```python
# overlay/ax/rate_limit.py
import asyncio
import time

class TokenBucket:
    """20 tokens/sec/pid hard cap."""
    def __init__(self, rate_per_sec: float = 20.0, capacity: int = 20):
        self.rate = rate_per_sec
        self.capacity = capacity
        self.tokens: dict[int, float] = {}        # pid → current tokens
        self.last_refill: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, pid: int) -> bool:
        """Returns True if token granted, False if rate-limited (caller should fall to cache)."""
        async with self._lock:
            now = time.monotonic()
            self.tokens.setdefault(pid, self.capacity)
            self.last_refill.setdefault(pid, now)
            elapsed = now - self.last_refill[pid]
            self.tokens[pid] = min(self.capacity, self.tokens[pid] + elapsed * self.rate)
            self.last_refill[pid] = now
            if self.tokens[pid] >= 1.0:
                self.tokens[pid] -= 1
                return True
            return False  # caller should fail-open with cached value
```

**Used by:** `ax/element.py` wrapper around every `AXUIElementCopyAttributeValue` call. If `acquire()` returns False:
1. Return last cached value with `confidence -= 0.2` (per Pitfall 2 prevention rule 5).
2. Log structured event `ax.rate_limited` with pid + bundle_id for triage.

**Why 20, not 30:** the saturation point is 30/sec (cmux #2985); 20 leaves headroom for parallel verifier branches each making AX calls.

[CITED: .planning/research/PITFALLS.md Pitfall 2 prevention rule 1]

### Coalescing reads

Per Pitfall 2 prevention rule 2: "any AX walk within a 100ms window returns the cached subtree."

```python
class AXReadCache:
    """100ms TTL cache per (pid, element_key, attribute)."""
    TTL_MS = 100

    async def read(self, pid: int, element_key: str, attribute: str) -> Any:
        key = (pid, element_key, attribute)
        if key in self.cache and (time.monotonic() - self.cache[key].ts) * 1000 < self.TTL_MS:
            return self.cache[key].value
        value = await self._raw_read(pid, element_key, attribute)
        self.cache[key] = CachedValue(value=value, ts=time.monotonic())
        return value
```

---

## Modal Alert Detection (Pitfall 25)

Per PROJECT.md mitigated pitfalls: P25 (modal alert blocks AX).

```python
# overlay/state/modal_probe.py
async def has_blocking_modal(pid: int) -> Optional[UIElement]:
    """Pre-action probe. Returns the modal element if found, None otherwise.

    Per Pitfall 25: scan AX tree for top-level dialog/sheet roles. If found, raise.
    """
    app = AXUIElementCreateApplication(pid)
    windows = await ax_read_cache.read(pid, app, kAXWindowsAttribute)
    for window in windows[:10]:  # cap windows checked
        is_modal = await ax_read_cache.read(pid, window, kAXModalAttribute)
        if is_modal:
            return _axelem_to_uielement(window, role_path="AXApplication/AXWindow[modal]")
    return None
```

**Used by:** every `HoarePre` check. If `has_blocking_modal()` returns non-None, the pre-condition `no_blocking_modal` is False, action does NOT fire.

**Push-event path:** also subscribe to `kAXWindowCreated` on every monitored pid. If a window appears mid-session, check `kAXModalAttribute`. If True, surface it.

[CITED: PITFALLS.md Pitfall 25]

---

## TCC Revocation Detection (Pitfall 24)

```python
# overlay/profile/tcc.py
from HIServices import AXIsProcessTrusted

class TCCMonitor:
    async def check(self) -> bool:
        return AXIsProcessTrusted()

    async def on_revocation(self):
        """Surface actionable URL, pause agent, save checkpoint."""
        url = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        structlog.get_logger().error("tcc_revoked", action_url=url)
        # Phase 1: structlog event + sys.exit(2). Phase 5+ adds NSPanel UI prompt.
```

**Polled at:** every probe + at every translator-call surface (per Pitfall 24 prevention rule 1). Cheap (microseconds).

---

## Persistence Scaffold (PERSIST-01..03)

### Session directory layout (PERSIST-02)

Per ARCHITECTURE.md L124-130:

```
~/.cua/sessions/<session_id>/         # session_id = UUID4 at session start
├── snapshot.json                     # last full StateGraph snapshot (atomic write)
├── action_log.ndjson                 # structlog NDJSON, every Hoare triple
├── checkpoints/                      # resumable mid-task state (LangGraph)
│   └── <step_idx>.json
├── recipes/                          # Phase 4: ghost-os recipe JSON (Phase 1: empty dir)
├── cassettes/                        # Phase 3: Stagehand-style replay tapes (Phase 1: empty dir)
├── recordings/                       # Phase 5: 60fps H.265 (Phase 1: empty dir)
├── heals.ndjson                      # Phase 3: heal events (Phase 1: empty file)
└── profile_snapshot/                 # cached AppProfile bundles touched in this session
    └── com.apple.Calculator.json
```

**`session_writer.py` creates this tree at session start:**

```python
import os, uuid
from pathlib import Path

class SessionWriter:
    def __init__(self, base: Path = Path.home() / ".cua" / "sessions"):
        self.session_id = str(uuid.uuid4())
        self.dir = base / self.session_id
        for sub in ("checkpoints", "recipes", "cassettes", "recordings", "profile_snapshot"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        (self.dir / "heals.ndjson").touch()
```

### LangGraph PostgresSaver wrapper (PERSIST-01)

Per STACK.md decision and PROJECT.md key decision: "LangGraph PostgresSaver wraps every translator call as durable step."

**Phase 1 scope:** minimal — only the verifier loop's checkpoint, not full graph state. Demonstrates that the checkpoint contract works.

```python
# overlay/persist/durable_step.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
import psycopg

CONN_STRING = "postgresql://localhost:5432/cua_maximalist"

class DurableExecutor:
    def __init__(self):
        self.checkpointer: AsyncPostgresSaver | None = None

    async def setup(self):
        self.checkpointer = await AsyncPostgresSaver.from_conn_string(CONN_STRING).__aenter__()
        await self.checkpointer.setup()

    async def checkpoint(self, session_id: str, step_idx: int, hoare_pre: HoarePre, action: ActionCanonical, hoare_post: HoarePost):
        config = {"configurable": {"thread_id": session_id, "checkpoint_id": str(step_idx)}}
        state = {
            "step_idx": step_idx,
            "pre": hoare_pre.model_dump(),
            "action": action.model_dump(),
            "post": hoare_post.model_dump(),
        }
        await self.checkpointer.aput(config, state, metadata={}, new_versions={})
```

[CITED: STACK.md "Durable Execution" + LangGraph PostgresSaver async API reference]

### Crash-resume scaffold (PERSIST-03)

```python
# overlay/persist/resume.py
async def resume_from_checkpoint(session_id: str) -> ResumeContext | None:
    """If session crashed mid-task, restore state from last checkpoint."""
    config = {"configurable": {"thread_id": session_id}}
    checkpoint = await checkpointer.aget(config)
    if not checkpoint:
        return None  # fresh session
    return ResumeContext(
        last_step_idx=checkpoint.get("step_idx", -1),
        last_verified_action=ActionCanonical(**checkpoint["action"]),
        snapshot_path=Path.home() / ".cua" / "sessions" / session_id / "snapshot.json",
    )
```

**Phase 1 demo for PERSIST-03:** smoke test `tests/integration/test_session_persistence.py`:
1. Start session, fire one verified click, confirm checkpoint row in Postgres.
2. Kill the Python process (`os.kill(os.getpid(), SIGKILL)`).
3. Restart, call `resume_from_checkpoint(session_id)`, assert `last_step_idx == 0`.

---

## MCP Proxy (MCP-01, MCP-02)

### Strategy: Approach A2 (per ToolRegistry hook discussion above)

Wrap `cua-driver`'s MCP server (the Swift one that has ToolRegistry) at the transport layer. Add new tools alongside passthrough.

```python
# overlay/mcp_server.py
from mcp.server.fastmcp import FastMCP
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

PROXY = FastMCP(name="cua-maximalist")

# Spawned at startup (Phase 1 may also support attaching to running cua-driver)
trycua_params = StdioServerParameters(command="cua-driver", args=["--mcp"])

async def main():
    async with stdio_client(trycua_params) as (read, write):
        async with ClientSession(read, write) as upstream:
            await upstream.initialize()
            tools = await upstream.list_tools()

            # MCP-01: mirror every upstream tool with verifier wrap
            for tool in tools:
                _register_proxied_tool(PROXY, upstream, tool)

            # MCP-02: register new healing tools
            _register_healing_tools(PROXY, upstream)

            await PROXY.run_stdio_async()

def _register_proxied_tool(proxy: FastMCP, upstream: ClientSession, tool):
    @proxy.tool(name=tool.name, description=tool.description)
    async def _wrapped(**args):
        # PRE: subscribe via verifier
        action_id = uuid.uuid4().hex
        target = _resolve_target(args)
        if target and target.role in CLICKABLE_ROLES:
            expected = await axobserver.expect(target, ["AXValueChanged", "AXFocusedUIElementChanged"], action_id)
        # FIRE: delegate
        result = await upstream.call_tool(tool.name, arguments=args)
        # POST: aggregate
        if target:
            confidence = await aggregator.aggregate(action_class=tool.name, signals={...})
        # LOG
        return result

def _register_healing_tools(proxy: FastMCP, upstream: ClientSession):
    @proxy.tool()
    async def click_with_healing(target_key: str, instruction: str = ""):
        """Phase 3 will fully implement; Phase 1: same as upstream click + log + verify."""
        ...
```

**Compatibility verification:** trycua's existing tests at `tests/test_mcp_server_streaming.py` and `tests/test_mcp_server_session_management.py` must still pass when run against the proxy. Phase 1 success criterion 6: "Existing trycua MCP server surface still works."

**Smoke test:** `tests/integration/test_mcp_proxy.py`:
1. Start proxy, list tools — assert all of trycua's tools appear PLUS `click_with_healing`.
2. Call `screenshot_cua` — assert PNG bytes returned (passthrough works).
3. Call `click_with_healing` against Calculator button — assert it verifies in <50ms.

---

## Architecture Patterns

### Recommended Project Structure

See §"Repository Topology" above.

### Pattern 1: Pre-subscribe, then fire

**What:** Subscribe to expected push events BEFORE firing the action. Store `subscription_ts_ns`. Filter incoming events: `event_ts_ns >= subscription_ts_ns + 5_000_000` AND `event.action_id == action.id`.
**When:** Every verified action.
**Why:** AXObserver fires <1ms via Mach port — deterministic, no diff, no polling. Pitfall 28 (stale notifications) mitigated by both ts and action_id filtering.
**Source:** ARCHITECTURE.md L408-426 Pattern 1 [CITED]

### Pattern 2: Composite key as identity

**What:** UIElement.composite_key returns highest-tier non-null of (axid → role_path+label → role+bbox_centroid). Cache key, comparison key, edge endpoint, never raw AXUIElement ref.
**When:** Reading state from any source. Writing edges. Cache lookup.
**Why:** AXUIElement refs are pid-scoped + invalidate on app restart + React/SwiftUI re-renders. Composite key survives.
**Source:** ARCHITECTURE.md L469 Anti-Pattern 3 [CITED]

### Pattern 3: One graph, many sources

**What:** Every translator (when Phase 2 lands) writes the same `UIElement` shape into the graph. UIElement.source[] tracks which translators saw it.
**When:** Reading state from any source.
**Why:** Self-heal = "different translator, same graph entity" — only works if the entity is canonical.
**Source:** ARCHITECTURE.md L429 Pattern 2 [CITED]

### Pattern 4: Cheap-deterministic-first ladder

**What:** L0 push → L1 cheap (1-5ms) → L2 medium (50-200ms) → L3 LLM (300-800ms). Never start at L3.
**When:** Always.
**Why:** Papers 2601.00828 + 2412.14959 prove intrinsic LLM correction is 16-27% accurate.
**Source:** ARCHITECTURE.md L442 Pattern 4 [CITED]

### Pattern 5: AsyncIO + CFRunLoop bridge via dedicated thread

**What:** Spawn `threading.Thread(target=lambda: CFRunLoopRun())`. All AX/NSWorkspace observers register on that thread. Events posted to asyncio.Queue via `loop.call_soon_threadsafe`.
**When:** Any PyObjC notification observer.
**Why:** Asyncio owns main thread; CFRunLoop callbacks need a CFRunLoop thread. Bridging via Queue is the only documented stable pattern.
**Source:** atomacos `BaseAXUIElement` pattern + ghost-os `LearningRecorder.swift:62-88` (Swift parallel) + this research [CITED]

### Anti-patterns to Avoid

| # | Anti-pattern | Why bad | Use instead |
|---|--------------|---------|-------------|
| 1 | Full recursive AX subtree walk | 15-20s on Safari (Pitfall 3) | Depth-limited (3 levels max, 50 children, 500 nodes) |
| 2 | AXUIElement pointer as identity | React/SwiftUI re-renders break this every keystroke (Pitfall 13) | Composite key (axid → role_path+label → bbox_centroid) |
| 3 | Heavy AX polling >30/sec | cmux #2985 stalls target Cocoa main thread (Pitfall 2) | Token bucket 20/sec/pid + push events first |
| 4 | PyObjC CGEvent tap on Python thread | CFRunLoop fights GIL (STACK.md REJECT) | Swift sidecar (Phase 4) |
| 5 | subprocess osascript | 50-200ms fork+exec (Pitfall 5) | py-applescript NSAppleScript in-process (Phase 2) |
| 6 | Silent heal | Masks regressions (Pitfall 20) | Phase 3 emits HealEvent NDJSON |
| 7 | Direct cross-component imports (cognition→translators) | Couples cognition to transport | Cognition→actions; actions picks channel |

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| AX bindings | Custom HIServices SWIG/ctypes wrapper | **PyObjC 12.1** + selectively forked atomacos helpers | PyObjC is the only maintained, current-on-macOS-26 binding [CITED: STACK.md] |
| AppleScript subprocess | osascript fork+exec | (Phase 2: py-applescript) | 50-200ms fork+exec; py-applescript is in-process NSAppleScript |
| OCR | tesseract / hand-roll Vision wrapper | **ocrmac 1.0.1** | thin shim over VNRecognizeTextRequest; already handles RTL/CJK |
| Image hashing | hand-roll dHash | **ImageHash 4.3.2** | pure NumPy dHash/pHash/wHash; tested |
| Structured logs | print() / json.dumps lines | **structlog 25.5.0** | bind_contextvars across asyncio task groups; NDJSON renderer |
| Cassette format | reach for vcrpy | (Phase 3: custom JSONL) | vcrpy is HTTP-only; doesn't see AX/CDP/AppleScript |
| Durable execution | hand-roll checkpoints | **langgraph-checkpoint-postgres 3.0.5** | proven pattern; AsyncPostgresSaver |
| MCP server | hand-roll MCP transport | **mcp** Python SDK (FastMCP) | what trycua uses; prefab transport |
| AsyncIO task groups | bare `asyncio.wait` | **anyio 4.x** `create_task_group` | anyio has correct cancellation semantics for FIRST_COMPLETED |
| State graph store | networkx / igraph | dict + Pydantic model | scale is small (in-memory, <1000 nodes); networkx adds dep weight |

**Key insight:** Phase 1 has 18 deps total. Every "build it ourselves" temptation makes the foundation more fragile and adds maintenance debt. The locked stack picks the smallest set of well-maintained libraries that cover the surface.

---

## Common Pitfalls (Phase 1 specific — 6 BLOCKERs to mitigate)

### Pitfall P2: AX rate-limit / cmux #2985

**What goes wrong:** >30 AX calls/sec/pid saturates target app's main thread. Slack freezes, looks like our agent crashed it.
**Why it happens:** Eager AX walks during verification + parallel branches each making AX calls.
**How to avoid:** 20 tok/sec/pid token bucket at the wrapper layer; 100ms read-cache; push events first (no polling).
**Warning signs:** `kAXErrorCannotComplete` (-25204); AX call latency >100ms; target app spinning beachball.
[CITED: PITFALLS.md Pitfall 2]

### Pitfall P3: Full recursive AX = 15-20s on Safari

**What goes wrong:** `AXUIElementCopyAttributeValue(AXChildren)` recursively on Safari's webarea returns thousands of DOM-mirrored AX nodes.
**Why it happens:** Naive subtree walk that doesn't cap depth.
**How to avoid:** HARD CAPS — depth ≤ 3, children ≤ 50, total ≤ 500. Walker emits `truncated=true` flag if any cap hit; verifier confidence reduced.
**Warning signs:** L2 verify latency >2s on web/Electron apps.
[CITED: PITFALLS.md Pitfall 3]

### Pitfall P14: AX notifs fail on Chrome/Safari web content (sandboxed)

**What goes wrong:** AXObserverAddNotification on web content silently drops because renderer is sandboxed. Notifications never fire.
**Why it happens:** Web content runs in a sandboxed renderer process; public AX SPI can't reach it.
**How to avoid:** AppProfile `ax_observer_works` probe at session start. If False, route L0 to CDP DOM mutations (Phase 2) for that bundle. Phase 1 detects and logs the limitation.
**Warning signs:** L0 verifier never fires for web/Electron content.
[CITED: PITFALLS.md Pitfall 14]

### Pitfall P24: TCC permission revoked mid-session

**What goes wrong:** User toggles Accessibility OFF. AX calls return `kAXErrorAPIDisabled`. Capture returns empty.
**Why it happens:** macOS treats TCC as user-controllable runtime state.
**How to avoid:** `AXIsProcessTrusted()` probe at every translator call surface (not just startup); on revocation surface action URL, save checkpoint, pause.
**Warning signs:** `kAXErrorAPIDisabled` errors appearing.
[CITED: PITFALLS.md Pitfall 24]

### Pitfall P25: Modal alert blocks AX silently

**What goes wrong:** System update dialog or app modal appears. AX actions queue silently behind it. Agent thinks it's working.
**Why it happens:** macOS keeps the modal at top of window order; AX calls succeed-but-have-no-effect.
**How to avoid:** Pre-action modal probe (`HoarePre.no_blocking_modal`); subscribe `kAXWindowCreated` push event; bundle blocklist for known modal sources.
**Warning signs:** Action verifies nothing; AX values unchanged after fire.
[CITED: PITFALLS.md Pitfall 25]

### Pitfall P28: Stale notification races verifier

**What goes wrong:** L0 push event fires from a stale notification (kAXValueChanged from 50ms BEFORE our action). Verifier "passes" before action lands.
**Why it happens:** Observer subscriptions buffer events; in-flight notifs from before subscription register can race.
**How to avoid:** Record `subscription_ts_ns` on subscribe; discard events with `event_ts < subscription_ts + 5ms`. Tag every action with action_id (UUID); only count events whose userInfo carries matching action_id.
**Warning signs:** Verifier passes <1ms after fire (faster than physically possible).
[CITED: PITFALLS.md Pitfall 28]

---

## Code Examples

### Calculator click verified in <50ms (the Phase 1 demo)

```python
# tests/integration/test_calculator_click.py
import asyncio
import pytest
import time

from overlay.profile.classifier import AppProfile, classify
from overlay.state.graph import StateGraph, UIElement
from overlay.verifier.axobserver import AXObserverManager
from overlay.verifier.aggregator import WeightedVote
from overlay.persist.session_writer import SessionWriter

@pytest.mark.asyncio
async def test_calculator_click_verifies_in_under_50ms():
    """Phase 1 success criteria 1, 2, 4."""
    # SETUP
    session = SessionWriter()
    structlog.contextvars.bind_contextvars(session_id=session.session_id)

    # Launch Calculator
    pid = launch_app("com.apple.Calculator")
    await asyncio.sleep(0.5)  # let it settle

    # CORE-03: probe + cache AppProfile
    profile = await classify(bundle_id="com.apple.Calculator", pid=pid)
    assert profile.ax_rich is True
    assert profile.ax_observer_works is True

    # STATE-01,02: probe and write the "5" button into state graph
    graph = StateGraph()
    five_button = await probe_button(pid, label="5")
    graph.upsert(five_button)
    assert five_button.composite_key.startswith("path:com.apple.Calculator:")

    # round-trip test (success criterion 2)
    same_button = graph.get(five_button.composite_key)
    assert same_button.composite_key == five_button.composite_key

    # VERIFY-01,04: subscribe BEFORE fire
    observer_mgr = AXObserverManager(loop=asyncio.get_running_loop())
    action_id = "test-click-001"
    expected = await observer_mgr.expect(
        target=five_button,
        notifs=["AXValueChanged", "AXFocusedUIElementChanged"],
        action_id=action_id,
    )

    # FIRE — Phase 1 has no translators yet, so we use raw CGEvent for the test
    t_start = time.monotonic()
    fire_cgevent_click(five_button.bbox.centroid)

    # WAIT for L0 push event
    try:
        event = await asyncio.wait_for(expected, timeout=0.05)  # 50ms hard cap
        l0_signal = 1.0
    except asyncio.TimeoutError:
        l0_signal = 0.0

    # VERIFY-05: L1 cheap-diff in parallel (Phase 1 demos as backup)
    l1_signals = await l1_cheap.run(target=five_button)

    # VERIFY-03: weighted vote
    aggregator = WeightedVote()
    confidence = aggregator.aggregate("click", {
        "ax.value_changed": l0_signal,
        "l1.window_diff": l1_signals.window_diff_score,
        "l1.pixel_dhash": l1_signals.dhash_changed_score,
    })

    elapsed_ms = (time.monotonic() - t_start) * 1000

    # SUCCESS CRITERIA
    assert confidence >= 0.5, f"verifier failed: {confidence}"
    assert elapsed_ms < 50, f"latency {elapsed_ms}ms > 50ms budget"
```

### AppProfile cache survives session restart (success criterion 3)

```python
@pytest.mark.asyncio
async def test_appprofile_cache_persists():
    pid = launch_app("com.apple.Calculator")
    profile1 = await classify("com.apple.Calculator", pid)
    cache_path = Path.home() / ".cua" / "profiles" / "com.apple.Calculator.json"
    assert cache_path.exists()

    # Simulate session restart by clearing in-memory cache
    classify.cache_clear()

    # Re-probe should hit the disk cache (no new probe latency)
    t = time.monotonic()
    profile2 = await classify("com.apple.Calculator", pid)
    elapsed = (time.monotonic() - t) * 1000

    assert profile2.bundle_version == profile1.bundle_version
    assert elapsed < 5, f"cache hit took {elapsed}ms — should be <5ms"
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| atomac / pyatomac | raw PyObjC HIServices + selective atomacos fork | 2018+ (atomac dead 2013, pyatomac dead 2018) | Forces hand-roll of NativeUIElement wrappers but unlocks private SPIs |
| Pre-action LLM verification | Post-action deterministic ensemble | 2025-2026 (papers 2601.00828, 2412.14959) | LLM verification only on ensemble disagreement |
| Polling AX trees | Push-event subscription (AXObserver) | "Always but rarely used" — production systems all miss this | Sub-1ms verification, no thread saturation |
| Full recursive AX walk | Depth-limited (3 levels) | Always but commonly violated | 15-20s → <50ms on Safari |
| AX element pointer as identity | Composite key (axid → role_path+label → bbox_centroid) | Always; React/SwiftUI made the bug visible | Cache hits work across re-renders |
| vcrpy / subprocess osascript / loguru | Custom JSONL cassettes / py-applescript / structlog | 2025-2026 stack maturity | Lower latency, async-correct |
| Hand-roll durable execution | LangGraph PostgresSaver | LangGraph 0.2+ (2025+) | Crash-resume from last verified step |

**Deprecated/outdated:**
- `pyatomac 2.0.7` (2018) — last release pre-Sonoma, won't compile against PyObjC 12. [VERIFIED: STACK.md]
- `atomac 1.1.0` (2013) — completely dead. [VERIFIED: STACK.md]
- `subprocess osascript` for AppleScript — fork+exec 50-200ms. Use NSAppleScript via py-applescript (Phase 2). [CITED: PITFALLS.md Pitfall 5]
- `NSWindow.sharingType = .none` for hiding overlay from capture — broken on macOS 15+. Use `SCContentFilter(excludingWindows:)` (Phase 5). [CITED: PITFALLS.md Pitfall 10]
- `intrinsic LLM self-correction` — 16-27% accuracy. Use external oracle ensemble. [CITED: papers 2601.00828, 2412.14959]

---

## Project Constraints (from CLAUDE.md)

CLAUDE.md directives that the planner MUST verify compliance with:

1. **Hard rule: never edit Swift code under `libs/cua-driver/`.** Phase 1 is Python overlay only.
2. **Hard rule: never run a full recursive AX tree walk** (15-20s on Safari). Always depth-limited (3 levels max).
3. **Hard rule: never poll AX at >20 calls/sec/pid** (cmux #2985 stalls Cocoa main thread).
4. **Hard rule: always subscribe AXObserver push notifications BEFORE the action fires.**
5. **Hard rule: deterministic ensemble first (L0→L1→L2). LLM (L3) only when ensemble confidence < 0.30.** Phase 1 must NEVER reach L3 in the Calculator demo.
6. **Hard rule: destructive actions (submit/send/delete) — single-channel only, never raced.** Phase 1 doesn't fire destructive actions, but the Pydantic types must enforce this from day 1.
7. **GSD workflow enforcement:** all file edits go through `/gsd-execute-phase`. Direct edits forbidden.
8. **Communication style (akeil's profile):** Short sentences, ≤15 words, answer-first, visuals-friendly. Apply to docs and stderr/log output.

---

## Assumptions Log

> Claims tagged `[ASSUMED]` in this research that need user/spike confirmation before becoming locked decisions.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 4px grid for bbox_centroid is sufficient for stable composite keys | State graph | composite_key collisions; cache misses; mitigation: integration test probes Calculator twice |
| A2 | Tauri/Wails detection via WebKit.framework presence is reliable | AppProfile probe | mis-classify Tauri as native AppKit → wrong translator priority; mitigation: 30-min spike on a real Tauri sample |
| A3 | Token-bucket rate (20/sec/pid) is correct vs cmux's 30 saturation point | AX rate-limit | too aggressive → unnecessary slowdown; too loose → app freeze; mitigation: cmux #2985 thread cite + integration test |
| A4 | Aggregator weights (0.6/0.4/0.3 for click signals) are reasonable starting values | VERIFY-03 | Phase 1 demo passes/fails by confidence; mitigation: tune in Phase 3 against real failure data |
| A5 | 0.30 threshold for L3 escalation is right | Confidence aggregation | too low → silent failures masked as VERIFIED; too high → expensive L3 calls; mitigation: Phase 4 calibration |
| A6 | Pattern A (dedicated CFRunLoop thread) is more reliable than Pattern B (libdispatch) on macOS 26 | AXObserver bridge | Pattern A is well-trodden; Pattern B may fail; mitigation: choose A, optionally spike B in parallel |
| A7 | 5ms guard for stale notification filtering is sufficient | Push-event verifier | stale events leak through → false-positive verification; mitigation: record event_ts_ns at high resolution + tune in real test |
| A8 | The proxy approach (A2) wraps cua-driver's MCP transport directly | MCP-01,02 | if cua-driver doesn't expose its own MCP socket, must fall back to A1 (proxy at agent level); mitigation: planner verifies via reading `cua-driver/Sources/CuaDriverServer/main.swift` (or equivalent) before locking the design |

**If this table is empty:** All claims in this research were verified or cited — no user confirmation needed. **It is NOT empty.** The planner should triage A1-A8 in the discuss-phase or via short spikes during planning.

---

## Open Questions (RESOLVED)

All planning-blocking questions resolved during /gsd-plan-phase. Items marked **DEFERRED** are explicitly out of Phase 1 scope and are tracked for Phase 2.

### Q1: cua-driver's MCP transport binding

**What we know:** ToolRegistry.swift uses `import MCP` [VERIFIED: line 4]. The MCP package is the upstream Swift MCP SDK.
**What's unclear:** Does cua-driver run as a standalone MCP server (own stdio/socket) OR is it loaded as a library by trycua's Python `mcp_server`?
**Recommendation:** Planner reads `~/thinker/research-clones/trycua-cua/libs/cua-driver/Sources/CuaDriverServer/main.swift` (or `Package.swift` to find the executable target) to confirm. Then locks A1 vs A2 proxy strategy.

**RESOLVED:** Plan 08 confirms cua-driver ships a standalone `cua-driver mcp` executable using StdioTransport (per `~/thinker/research-clones/trycua-cua/Sources/CuaDriverCLI/Commands/CuaDriverCommand.swift` and trycua's `mcp_server/server.py` pattern). Plan 08 Task 1 spawns it via `mcp.client.stdio.stdio_client` from the Python overlay's MCP proxy. Strategy = A2 (proxy at MCP-transport level).

### Q2: Pydantic discriminated union for ActionCanonical?

**What we know:** ActionCanonical needs a `kind: Literal["READ", "MUTATE"]` for speculation safety (Pitfall 22). It also needs typed `payload` per `action_type`.
**What's unclear:** Use a single `ActionCanonical` class with `payload: dict` (loose), OR `ActionCanonical = Union[ClickAction, TypeAction, ScrollAction, ...]` discriminated union (typed)?
**Recommendation:** Discriminated union per `action_type`. mypy + Pydantic v2 validate. Phase 2 translators read `action.payload.x` with full type safety.

**RESOLVED:** Plan 01 Task 3 locks `ActionCanonical` as a single Pydantic model with `kind: Literal["READ","MUTATE"]` and `payload: dict` (loose). Discriminated unions per `action_type` are Phase 2 work — Phase 1 only needs the kind gate and the dict for forward-compat. The HoarePre + HoarePost contracts ARE strict though.

### Q3: Where does the asyncio loop run?

**What we know:** `python -m overlay.mcp_server` is the entry point. asyncio loop runs on main thread. CFRunLoop runs on a dedicated thread.
**What's unclear:** Does FastMCP's `run_stdio_async()` own the main loop, or do we need to compose with our own?
**Recommendation:** FastMCP exposes `run_stdio_async()` as the top-level coroutine [VERIFIED: trycua/mcp_server/server.py uses `await server.run_stdio_async()` pattern]. We `asyncio.run(main())` where main starts the AX bridge thread, sets up Postgres, then awaits FastMCP.

**RESOLVED:** Plan 08 Task 1 wires this exactly as the recommendation said: `asyncio.run(main())` is the entry point; `main()` starts AXEventBridge (CFRunLoop dedicated thread) + AXObserverManager dispatcher task + DurableExecutor (Postgres) + spawns the upstream cua-driver via stdio_client; then `await server.run_stdio_async()` blocks on the proxy's stdio loop.

### Q4: NDJSON action_log format vs cassette format

**What we know:** action_log.ndjson is the live event stream; cassettes are the verified-step replay tape (Phase 3).
**What's unclear:** Should action_log entries include all 4 tier signals + raw observer events, or just the aggregated HoarePost?
**Recommendation:** Include both — the NDJSON has `{step_idx, hoare_pre, action, hoare_post, raw_signals: {...}, observer_events: [...]}`. Cassettes (Phase 3) extract the durable subset.

**RESOLVED:** Plan 07 (SessionWriter) writes the full superset to `~/.cua/sessions/<session_id>/action_log.ndjson`: `{step_idx, hoare_pre, action, hoare_post, raw_signals, observer_events, elapsed_ms}`. Cassette JSONL extraction is Phase 3 (downstream consumer of the same NDJSON file).

### Q5: AppProfile probe timeouts

**What we know:** Total budget <500ms first-probe.
**What's unclear:** Per-probe timeouts to avoid one slow probe blocking total. AS .sdef parse can be 100-300ms on first call (loads OSAKit framework).
**Recommendation:** Each probe wrapped with `asyncio.wait_for(probe, timeout=0.2)`; on timeout, mark capability `unknown` and re-probe later in session. Cache the unknown state to avoid re-probing on every call.

**RESOLVED:** Plan 02 Task 2 caps each capability probe at `asyncio.wait_for(probe, timeout=0.2)` (200ms per probe), runs the probes in parallel via `anyio.create_task_group`, and falls open to `unknown` on per-probe timeout (cached so the session does not re-probe in a tight loop). Total first-probe budget remains <500ms.

### A1: 4px grid for bbox_centroid

**RESOLVED:** Plan 01 Task 2 implements `Bbox.centroid` as `(round((x + w/2) / 4) * 4, round((y + h/2) / 4) * 4)` (the 4px-grid rounding). Plan 09 Task 2 includes `test_state_graph_roundtrip` which double-probes Calculator's "5" button across 1-3px jitter and asserts identical composite_key (Test 9 in Plan 01 Task 2 covers the unit case directly).

### A2: Tauri/Wails detection via WebKit.framework

**DEFERRED:** Plan 02 Task 2 implements the heuristic and emits a structlog warning when it fires (`tauri_or_wails_heuristic_fired`). 30-min spike on a real Tauri app is scheduled for Phase 2; Plan 02 returns `unknown`-flavored output (i.e. flags `tauri_or_wails=True`) for Tauri-shaped bundles for now. Mis-classification risk is bounded because translator priority falls back to T4/T5 (Vision/Pixel) when AX/AS/CDP all degrade.

### A3: Token-bucket rate (20/sec/pid)

**RESOLVED:** Plan 03 Task 1 sets `TokenBucket(rate_per_sec=20.0, capacity=20)`. cmux #2985 thread cited in PITFALLS.md (saturation at 30/sec). Test `test_initial_burst_grants_20` and `test_21st_call_in_first_second_returns_false` verify both the headroom and the cap.

### A4: Aggregator weight values

**RESOLVED:** Plan 05 Task 2 ships the starting heuristics + present-signal renormalization in `WeightedVote.aggregate()`. Phase 3 tunes against real failure data; Phase 1 demo passes deterministically because Calculator click reliably emits `ax.value_changed` (which alone clears 0.50 under renormalization).

### A5: 0.30 L3 escalation threshold

**RESOLVED:** Plan 05 exports `L3_ESCALATE_THRESHOLD = 0.30` and Plan 06 Task 3 enforces the ladder. Phase 4 calibration is on the roadmap; Phase 1 Calculator demo asserts L3 is never reached.

### A6: Pattern A (CFRunLoop thread) vs Pattern B (libdispatch)

**DEFERRED:** Plan 04 Task 1 commits to Pattern A — dedicated `threading.Thread` running `CFRunLoopRun()`, with cross-thread handoff via `loop.call_soon_threadsafe(queue.put_nowait, event)`. This is the well-trodden path. An optional libdispatch spike is tracked for Phase 2 if Pattern A shows latency or stability issues; nothing in Phase 1 forces Pattern B.

### A7: 5ms guard for stale notifications

**RESOLVED:** Plan 04 Task 1 sets `_GUARD_NS = 5_000_000` (5ms) in `cua_overlay/verifier/axobserver.py`. Test `test_filter_drops_pre_subscription_events` exercises the boundary with 2ms (drops) and 6ms (keeps) deltas.

### A8: Proxy approach (A2 over A1)

**RESOLVED:** See Q1 above. Plan 08 verifies cua-driver exposes a standalone `cua-driver mcp` stdio executable; A2 (transport-level proxy) locks in.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| macOS 26 (Tahoe) | All Phase 1 | ✓ (project constraint) | 26.x | none — hard requirement |
| Apple Silicon | mlx-vlm (Phase 4); not Phase 1 | ✓ (project constraint) | M-series | none |
| Python 3.12 | overlay | TBD (planner verifies) | TBD | install via uv |
| uv | Package manager | TBD | TBD | brew install uv |
| Postgres 16 | langgraph-checkpoint-postgres | TBD | TBD | brew install postgresql@16 |
| Xcode 26 | apple-fm-sdk (Phase 4); not Phase 1 | TBD | TBD | required by Phase 4 only |
| TCC: Accessibility | AXObserver, AXUIElementCopyAttributeValue | TBD (per-process grant) | — | hard requirement; user grants once |
| TCC: Screen Recording | L1 dHash via SCScreenshotManager | TBD | — | fallback: CGWindowListCreateImage (deprecated but works) |
| TCC: Input Monitoring | Phase 4 CGEvent tap; not Phase 1 | TBD | — | required by Phase 4 only |

**Missing dependencies with no fallback:** None — Phase 1 deps all installable.

**Missing dependencies with fallback:** Screen Recording TCC — can fall to deprecated CGWindowListCreateImage if user hasn't granted. Phase 1 demo doesn't strictly need screen capture if we skip L1c (pixel dHash) and rely only on L1a + L1b — Calculator click should verify via AXValueChanged alone.

**Planner action:** Phase 1 plan #1 (the foundation/scaffold task) should run a one-time `make doctor` script that verifies all of the above and prints a checklist.

---

## Validation Architecture

> Required per `workflow.nyquist_validation: true` in `.planning/config.json`.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ [VERIFIED: STACK.md] |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) — Wave 0 creates |
| Quick run command | `uv run pytest tests/unit -x --tb=short` |
| Full suite command | `uv run pytest -x --tb=short` |
| Async marker | `@pytest.mark.asyncio` (auto-mode in pytest-asyncio config) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| **CORE-01** | Repo scaffold exists with overlay/ tree | smoke | `uv run pytest tests/unit/test_scaffold.py -x` | ❌ Wave 0 |
| **CORE-02** | MCP proxy lists trycua tools + adds healing tools | integration | `uv run pytest tests/integration/test_mcp_proxy.py::test_list_tools -x` | ❌ Wave 0 |
| **CORE-03** | AppProfile probe + cache for Calculator | integration | `uv run pytest tests/integration/test_app_profile.py::test_calculator_profile -x` | ❌ Wave 0 |
| **CORE-03** | AppProfile cache survives session restart | integration | `uv run pytest tests/integration/test_app_profile.py::test_cache_persists -x` | ❌ Wave 0 |
| **STATE-01** | UIElement composite_key is stable across re-probe | unit | `uv run pytest tests/unit/test_fingerprint.py::test_stable_composite_key -x` | ❌ Wave 0 |
| **STATE-01** | UIElement Pydantic round-trip | unit | `uv run pytest tests/unit/test_state_graph.py::test_pydantic_roundtrip -x` | ❌ Wave 0 |
| **STATE-02** | Causal DAG records TRIGGERS edge after action | integration | `uv run pytest tests/integration/test_causal_dag.py::test_click_triggers_edge -x` | ❌ Wave 0 |
| **STATE-03** | Ring buffer caps at 5 frames | unit | `uv run pytest tests/unit/test_ring_buffer.py::test_maxlen -x` | ❌ Wave 0 |
| **VERIFY-01** | AXObserver subscribed BEFORE action fires | integration | `uv run pytest tests/integration/test_axobserver.py::test_pre_subscribe -x` | ❌ Wave 0 |
| **VERIFY-01** | AXValueChanged fires for Calculator click | integration | `uv run pytest tests/integration/test_calculator_click.py::test_axvalue_changed -x` | ❌ Wave 0 |
| **VERIFY-02** | NSWorkspace frontmost-app change observed | integration | `uv run pytest tests/integration/test_nsworkspace.py::test_frontmost_change -x` | ❌ Wave 0 |
| **VERIFY-02** | kqueue EVFILT_PROC fires on app exit | integration | `uv run pytest tests/integration/test_kqueue_proc.py::test_app_exit -x` | ❌ Wave 0 |
| **VERIFY-03** | Aggregator returns ≥0.5 for full-signal click | unit | `uv run pytest tests/unit/test_aggregator.py::test_click_full_signal -x` | ❌ Wave 0 |
| **VERIFY-03** | Stale notif filter discards <5ms events | unit | `uv run pytest tests/unit/test_aggregator.py::test_stale_filter -x` | ❌ Wave 0 |
| **VERIFY-04,05** | **Calculator click verified in <50ms** (the key demo) | end-to-end | `uv run pytest tests/integration/test_calculator_click.py::test_under_50ms -x` | ❌ Wave 0 |
| **VERIFY-04,05** | Verify works WITHOUT L2/L3 reaching | integration | `uv run pytest tests/integration/test_calculator_click.py::test_l2_l3_not_invoked -x` | ❌ Wave 0 |
| **VERIFY-06** | Walker caps depth at 3 / children at 50 / nodes at 500 | unit | `uv run pytest tests/unit/test_walker.py::test_caps -x` | ❌ Wave 0 |
| **VERIFY-07** | L3 stub raises if reached in Phase 1 | unit | `uv run pytest tests/unit/test_l3.py::test_stub_raises -x` | ❌ Wave 0 |
| **AX rate-limit** | Token bucket caps at 20/sec/pid | unit | `uv run pytest tests/unit/test_rate_limit.py::test_20_per_sec_cap -x` | ❌ Wave 0 |
| **Pitfall P25** | Modal alert blocks pre-action | integration | `uv run pytest tests/integration/test_modal_probe.py::test_blocks_action -x` | ❌ Wave 0 |
| **Pitfall P24** | TCC revocation surfaces error + URL | unit | `uv run pytest tests/unit/test_tcc.py::test_revoke_message -x` | ❌ Wave 0 |
| **PERSIST-01** | Postgres checkpointer writes row per verified step | integration | `uv run pytest tests/integration/test_durable_step.py::test_checkpoint_row -x` | ❌ Wave 0 |
| **PERSIST-02** | ~/.cua/sessions/<id>/ tree created at start | unit | `uv run pytest tests/unit/test_session_writer.py::test_tree_created -x` | ❌ Wave 0 |
| **PERSIST-03** | Crash → resume picks up last step | integration (manual: SIGKILL) | `uv run pytest tests/integration/test_session_persistence.py::test_resume_after_kill -x` | ❌ Wave 0 |
| **MCP-01** | Existing trycua tests still pass via proxy | regression | `cd libs/python/mcp-server && uv run pytest -x` | ✓ (upstream tests exist) |
| **MCP-02** | New healing tool callable from MCP client | integration | `uv run pytest tests/integration/test_mcp_proxy.py::test_healing_tool -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit -x --tb=short` (~5 sec, no real apps)
- **Per wave merge:** `uv run pytest -x --tb=short` (~30-60 sec, includes Calculator integration tests)
- **Phase gate:** Full suite green AND `uv run pytest tests/integration/test_calculator_click.py::test_under_50ms -x` passes 10/10 runs

### Wave 0 Gaps

- [ ] `pyproject.toml` — pytest config + asyncio mode + dependencies
- [ ] `tests/conftest.py` — shared fixtures: `pytest_asyncio`, `session_dir` (tmp), `postgres_test_db`, `calculator_pid`
- [ ] `tests/unit/test_scaffold.py` — minimal smoke
- [ ] `tests/integration/test_calculator_click.py` — THE phase 1 demo
- [ ] All other test files listed above (one per requirement-behavior pair)
- [ ] Framework install: `uv pip install -D pytest pytest-asyncio mypy ruff`
- [ ] `make doctor` script — environment check (Python, Postgres, TCC permissions)

---

## Sources

### Primary (HIGH confidence)
- `~/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md` — THE blueprint, 9-layer locked architecture, code-level steals
- `.planning/PROJECT.md` — locked vision + key decisions
- `.planning/REQUIREMENTS.md` — 79 requirements, 18 mapped to Phase 1
- `.planning/ROADMAP.md` — Phase 1 success criteria + dependencies
- `.planning/research/STACK.md` — locked tech stack with PyPI live verification (2026-04-29)
- `.planning/research/ARCHITECTURE.md` — component map + IPC seam + build order + patterns + anti-patterns
- `.planning/research/PITFALLS.md` — 29 pitfalls with severity + prevention; Phase 1 owns 6 BLOCKERs
- `~/thinker/research-clones/trycua-cua/libs/cua-driver/Sources/CuaDriverServer/ToolRegistry.swift` — file:line confirmed
- `~/thinker/research-clones/trycua-cua/libs/python/mcp-server/mcp_server/server.py` — FastMCP usage pattern verified
- CLAUDE.md — project hard rules

### Secondary (MEDIUM confidence — verified against official sources)
- [PyPI structlog 25.5.0](https://pypi.org/project/structlog/) — 2025-10-27 [verified via STACK.md]
- [PyObjC API Notes: HIServices](https://pyobjc.readthedocs.io/en/latest/apinotes/HIServices.html) — accessibility surface confirmed
- [PyObjC API Notes: Vision](https://pyobjc.readthedocs.io/en/latest/apinotes/Vision.html) — VNRecognizeTextRequest confirmed
- [LangGraph PostgresSaver async API reference](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver) — API surface confirmed
- AX-tree paper arXiv 2603.20358 — 10-tier locator hierarchy
- Decomposing Self-Correction arXiv 2601.00828 — intrinsic LLM correction = 16-27%
- cmux issue #2985 — AX rate-limit / main-thread saturation

### Tertiary (LOW confidence — needs validation)
- 4px grid for bbox_centroid stability — **A1 in Assumptions Log**
- Tauri/Wails detection heuristic — **A2 in Assumptions Log**
- Aggregator weights (0.6/0.4/0.3 starting values) — **A4 in Assumptions Log**
- 0.30 confidence threshold for L3 escalation — **A5 in Assumptions Log**

---

## Metadata

**Confidence breakdown:**

| Area | Level | Reason |
|------|-------|--------|
| Standard stack | HIGH | Locked in STACK.md; PyPI versions live-verified 2026-04-29 |
| Module layout | HIGH | Matches ARCHITECTURE.md component map verbatim |
| ToolRegistry hook | HIGH | file:line confirmed via direct read; proxy approach safe |
| AppProfile probe | MEDIUM | Probe heuristics partially assumed (A2); needs spike |
| State graph schema | HIGH | Pydantic v2 model maps directly to architecture doc L40-49 |
| Composite key strategy | HIGH | AX-tree paper 2603.20358 + ARCHITECTURE.md L469 [CITED] |
| AXObserver bridge | MEDIUM | Pattern A is well-trodden; libdispatch alternative could be spiked |
| L0+L1 latency budget | HIGH | Math: AXObserver <1ms + CGWindowList ~2ms + dHash ~10ms = <50ms |
| MCP proxy | MEDIUM | Approach A2 needs cua-driver MCP transport verification (Q1) |
| Persistence | HIGH | LangGraph PostgresSaver well-documented + locked stack |
| Validation Architecture | HIGH | All 18 requirements mapped to specific test files + commands |

**Research date:** 2026-04-29
**Valid until:** 2026-05-29 (30 days — stack is stable, but PyPI versions worth re-verifying if planning slips)
**Phase 1 scope:** ~1500-2000 LOC Python; 18 requirements; ~5 days estimated per ARCHITECTURE.md "Sprint 0+1+2" mapping.

---

*Research consumed by:* `gsd-planner` for `.planning/phases/01-foundation-state-verifier/01-PLAN.md`
*Open questions for discuss-phase or planner spike:* Q1 (cua-driver MCP transport), Q5 (per-probe timeouts), A2 (Tauri detection), A6 (libdispatch spike).
