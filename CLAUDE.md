<!-- GSD:project-start source:PROJECT.md -->
## Project

**basicCtrl — Self-Healing Autonomous Mac CU Framework**

A maximalist, self-healing, autonomous computer-use framework for macOS. Built as a Python overlay above `trycua/cua`'s Swift driver with full private-SPI access (SkyLight, Endpoint Security, DYLD injection). Drives any Mac app — native Cocoa, Electron, browser, Canvas, terminal, game — by automatically picking the right protocol per app, racing multiple action channels in parallel, verifying with deterministic ensembles before falling back to LLMs, and recovering from any failure via 5-branch parallel recovery. Local-only and experimental — no production, security, or App Store constraints.

For Akeil personally: maximum-power Mac control, fully transparent (ghost cursor + HUD + 60fps replay), continuously self-improving via CGEvent recording → recipe synthesis → episodic memory.

**Core Value:** **Autonomous control of any app on any Mac surface, with deterministic self-healing and full transparency — never silently fails, never gives up, never makes the user babysit.**

When everything else fails, the system picks the next translator, races recovery branches, replays from cassette, or asks the user. It never silently drops a task.

### Constraints

- **Platform**: macOS 26+ (Tahoe), Apple Silicon only — depends on FoundationModels framework + ANE-accelerated Vision + Apple's MLX
- **Trust model**: local-only, single-user (Akeil's Mac), full TCC grant (Accessibility, Screen Recording, Input Monitoring, Automation per-app)
- **SIP**: partial-off acceptable for DTrace + DYLD injection paths (these are optional/private-SPI tier)
- **Distribution**: never to App Store; never beyond Akeil's machine
- **Languages**: Python (overlay primary, ~1500-2500 LOC) + minimal Swift glue (Visualizer + SkyLight bridges, ~300 LOC)
- **Compatibility**: must continue to work alongside browser-harness (Akeil uses it daily)
- **Cost**: 5-branch recovery + ensemble LLM voting are expensive at Opus pricing — fine locally, never run in tight loops without bounded retries
- **macOS version risk**: Apple may close private SPIs in macOS 27+; drivers must degrade gracefully (registry skips unavailable channels)
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## TL;DR — pick this
## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why |
|---|---|---|---|
| **Python** | 3.12 | Overlay primary language | 3.13 free-threading still maturing on PyObjC; 3.12 is sweet spot for asyncio + structlog typing |
| **uv** | latest | Package manager + venv | 10-100x faster than pip; reproducible lockfile; what trycua already uses |
| **Swift** | 6.0 | Visualizer + SkyLight bridges + CGEvent tap | C-level interop with private SPIs; macOS 26 native; ~300 LOC total |
| **PyObjC** | 12.1 (Nov 2025) | Bridge to all macOS frameworks | Active, current, supports macOS 26 Tahoe; direct AX + Vision + AppKit access |
| **asyncio + anyio** | stdlib + 4.x | Race orchestrator + structured concurrency | `anyio.create_task_group` gives `FIRST_COMPLETED` with proper cancellation semantics that pure asyncio.wait botches; required for racing translators |
### Accessibility / AX Bindings — the hard call
| Technology | Version | Purpose | Decision |
|---|---|---|---|
| **PyObjC HIServices (raw)** | 12.1 | Primary AX SPI access | **CHOSEN** — direct `AXUIElementCreateApplication`, `AXUIElementCopyAttributeValue`, `AXObserverCreate`, private `_AXUIElementGetWindow` via dlsym |
| **atomacos** | 3.3.0 (May 2021) | Helper layer copy | **PARTIAL FORK** — copy useful helpers (NativeUIElement, BaseAXUIElement) into `overlay/ax/`, do NOT take dep |
| ~~pyatomac~~ | 2.0.7 (2018) | — | **REJECT** — last release 2018, pre-Sonoma, abandoned |
| ~~atomac~~ | 1.1.0 (2013) | — | **REJECT** — last release 2013, completely dead |
### AppleScript Bridge
| Choice | Decision |
|---|---|
| **py-applescript 1.0.3** (NSAppleScript via PyObjC, in-process) | **CHOSEN** |
| ~~subprocess osascript~~ | REJECT — fork+exec on every call, 50-200ms overhead, blocks event loop |
| ~~PyObjC OSAKit raw~~ | REJECT — more boilerplate than py-applescript wraps for zero benefit |
### On-Device VLM Grounding (the ANE pipeline)
| Tier | Model | Serving | Purpose |
|---|---|---|---|
| **Tier 0 (binary classify)** | Apple FM 3B | `apple-fm-sdk 0.1.1` | Routing decisions — "is this dialog modal?" "is element a text field?" — 50-200ms/token, free, ANE |
| **Tier 1 (grounding)** | **UI-TARS-1.5-7B (4-bit MLX)** | `mlx-vlm 0.4.4` | Primary grounder — pixel→element coords, parallel to planner |
| **Tier 1b (faster fallback)** | **ShowUI-2B (4-bit MLX)** | `mlx-vlm 0.4.4` | When UI-TARS-1.5 coord-quantization bug hits (mlx-vlm #330) — 2B model, 75% screenspot accuracy, smaller footprint |
| **Tier 2 (planner)** | Claude Opus 4 (cloud) | `anthropic` SDK | Cognition only, not grounding |
### Vision Framework via PyObjC
| Choice | Version | Why |
|---|---|---|
| **ocrmac** | 1.0.1 (Jan 2026) | Thin wrapper around `VNRecognizeTextRequest` + `VNImageRequestHandler` via pyobjc-framework-Vision |
| `pyobjc-framework-Vision` | 12.1 (transitive) | Direct `VNFeaturePrint` for template match, custom request types |
### CGEvent Tap (Continuous Learning Recorder)
| Choice | Verdict |
|---|---|
| **Swift CGEvent tap on bg DispatchQueue** | **CHOSEN** — `LearningRecorder.swift` from ghost-os pattern, IPC over unix socket to Python overlay |
| ~~PyObjC CGEvent tap on Python thread~~ | REJECT — CGEventTapCreate requires CFRunLoop on a real thread; Python's GIL + asyncio loop fights this; documented seg-faults in tensorflow/swift#224, real CGEventTaps from Python fail intermittently when the Python interpreter is GC-stopped |
### Image Hashing
| Choice | Version | Why |
|---|---|---|
| **ImageHash** | 4.3.2 (Feb 2025) | dHash, pHash, wHash — pure NumPy; ROI hashing trivial via PIL crop |
| **Pillow** | latest (transitive) | Required for ImageHash; also for fast PNG/JPEG encode of screenshots |
### Vector Store — Episodic Memory
| Choice | Verdict |
|---|---|
| **faiss-cpu 1.13.2** | **CHOSEN** — embedded library, 100k vectors in <100MB, no server, IndexFlatL2 trivial, IVFPQ when we hit 1M+ |
| ChromaDB 1.5.8 | REJECT — has a server runtime even in "in-process" mode; we don't need metadata filtering at Q-store scale (we filter on `(bundleID, task_class)` in Python before vector search) |
| LanceDB 0.30 | NOT RECOMMENDED — fine choice but adds Apache Arrow dep weight; FAISS is simpler for our scale |
### Structured Event Logging
| Choice | Verdict |
|---|---|
| **structlog 25.5.0** (Oct 2025) | **CHOSEN** — context binding via `contextvars` works correctly across asyncio task groups; native NDJSON renderer; ~25% faster than loguru on JSON; processor pipeline lets us inject Hoare-triple metadata at every log call |
| loguru 0.7.3 (Dec 2024) | REJECT — context propagation across asyncio is buggy (loguru #1083); slower JSON; over-eager file rotation defaults; "abandoned-ish" maintenance |
### NSPanel Transparent Overlay (Swift glue)
| Choice | Why |
|---|---|
| **Pure SwiftUI + AppKit hybrid in Swift sidecar** | NSPanel + SwiftUI hosting view; `.popUpMenu` level, `ignoresMouseEvents=true`, `canJoinAllSpaces`, `SCContentFilter excludingApplications: [self]` — verbatim from architecture doc L7 recipe |
| Talks to Python overlay via | unix socket NDJSON — overlay sends `{cmd: "ghost_cursor", x, y, t}`, `{cmd: "highlight", bbox, label, tier}`, `{cmd: "hud_action", text, status}` |
### Trace-Replay Cassettes
| Choice | Verdict |
|---|---|
| **Custom JSON Lines cassette** | **CHOSEN** — `cassettes/<task_hash>.jsonl`, one entry per step: `{step_idx, hoare_pre, action_canonical, hoare_post, screenshot_pHash, ax_subtree_hash, healed_selectors[]}` |
| vcrpy 8.1 | REJECT for this purpose — vcrpy is **HTTP-only**. Records HTTPX/requests calls. Useless for AX/CDP/AppleScript actions. |
| `pytest-recording` | REJECT — same reason, HTTP-only |
| traceops | REJECT — could not verify it exists as a Python package on PyPI as of 2026-04-29 (search returned nothing); the architecture doc cites it but it may be a pattern, not a library |
### Durable Execution
| Choice | Verdict |
|---|---|
| **`langgraph-checkpoint-postgres` 3.0.5** (March 2026) | **CHOSEN** — runs against a local Postgres (already on Akeil's Mac via `brew install postgresql`), `AsyncPostgresSaver.from_conn_string()`, autocommit + dict_row, persists graph state per node |
| Inngest 0.5.18 (Mar 2026) | REJECT — event-driven serverless model is wrong fit; needs Inngest dev server running; designed for backend jobs, not desktop CU loops; would force everything through HTTP step boundaries |
| Restate (March 2026) | REJECT — sidecar HTTP interceptor; same fit problem as Inngest; production-grade overkill for single-user local |
| Temporal | REJECT — full cluster setup; way too heavy |
- **Graph-shaped state matches our architecture** — translator → action → verifier is literally a LangGraph
- **Local Postgres** = zero new infra (already needed for FAISS metadata anyway)
- **Crash → resume from last checkpoint** works exactly like the architecture doc L8 spec
- Each translator call wraps as a node; Postgres row per state transition
- **Architecture doc explicitly lists this as one of two options** — pick the lighter one
### Browser CDP
| Choice | Source | Why |
|---|---|---|
| **cdp-use** (browser-harness's choice) | already vendored in browser-harness | Reuse — Akeil uses browser-harness daily, must remain compatible; CDP for Electron apps (Slack/Discord/VS Code/Cursor/Figma) is the same protocol |
| asyncio websockets | for raw frames | When cdp-use's typed wrappers don't expose what we need (private CDP methods) |
## Supporting Libraries
| Library | Version | Purpose | When to Use |
|---|---|---|---|
| **Pydantic** | v2 latest | Typed schemas (UIElement, ActionCanonical, HoarePre/Post, AppProfile, Recipe) | Everywhere — every state node, every cassette step, every IPC message |
| **httpx** | 0.27+ | Async HTTP for Anthropic / OpenAI / OpenRouter | Cognition layer LLM calls |
| **anthropic** | latest | Claude Opus planner | Sprint 6+ |
| **openai** | latest | GPT-5 ensemble vote | Sprint 6 (ensemble vote) |
| **transformers** | 4.50+ | Tokenizer for non-MLX paths | Fallback path only |
| **mlx** | 0.20+ (transitive of mlx-vlm) | Apple Silicon ML runtime | UI-TARS + ShowUI |
| **psycopg** | 3.x | Postgres async driver | langgraph-checkpoint-postgres needs it |
| **websockets** | 13.x | Raw CDP fallback | When cdp-use is too high-level |
| **rich** | latest | TTY pretty-print of action log during dev | Dev-only, not in HUD |
| **pytest** | 8.x | Test runner | Tests against tcc-disabled local apps |
| **pytest-asyncio** | 0.23+ | asyncio test fixtures | Async tests |
| **mypy** | 1.x | Type checking | Pydantic + structlog have full hints |
| **ruff** | latest | Linter + formatter | What trycua already uses |
## Development Tools
| Tool | Purpose | Notes |
|---|---|---|
| **uv** | Package manager | Already what trycua uses; 10-100× pip |
| **direnv** | Per-project env activation | TCC-grant-required env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) |
| **Postgres 16** (local brew) | Durable execution backend | `brew install postgresql@16 && brew services start postgresql@16` |
| **Xcode 26** | Required for apple-fm-sdk + Swift glue | macOS 26 SDK |
| **swift-format** | Format Swift sidecars | trycua's existing config |
| **Instruments** | Profiling Python ↔ Swift IPC | Critical for the racing translator timing |
## Installation
# Python overlay (uv-managed)
# Dev
# Local infra
# Models (one-time download to ~/.cache/huggingface)
# Apple FM (requires Xcode 26 + Apple Intelligence enabled)
# apple-fm-sdk pulls Swift framework headers — first import compiles bridge
# Swift sidecars (built once)
## Alternatives Considered
| Recommended | Alternative | When alternative makes sense |
|---|---|---|
| Raw PyObjC HIServices | atomacos | If you only need read-only AX (no `_AXObserverAddNotificationAndCheckRemote`); we need private SPIs, so raw |
| FAISS | LanceDB | If we ever need >1M episodic memories with metadata filter pushdown — not our scale |
| LangGraph PostgresSaver | Inngest | If this becomes a multi-user cloud service (it won't — local single-user is the constraint) |
| Swift CGEvent sidecar | PyObjC tap | Never — documented Python+CFRunLoop instability |
| structlog | loguru | If you want zero-config and don't care about asyncio context — not us |
| ImageHash dHash | OpenCV pHash | If we needed video / large-image hashing — overkill here |
| py-applescript (NSAppleScript) | subprocess osascript | Never — fork+exec cost destroys the racing-translator latency budget |
| UI-TARS-1.5 + ShowUI fallback | Pure ShowUI-2B | If UI-TARS coord bug becomes blocking; ShowUI alone trades ~5pp accuracy for stability |
| Custom cassette JSONL | vcrpy | Never for AX/CDP/AppleScript — vcrpy is HTTP-only |
## What NOT to Use
| Avoid | Why | Use Instead |
|---|---|---|
| **pyatomac 2.0.7** | Last release 2018-06-01 — abandoned, pre-Sonoma, won't compile against pyobjc 12 | Raw PyObjC HIServices + atomacos helpers (forked) |
| **atomac 1.1.0** | Last release 2013 — completely dead | Same as above |
| **subprocess osascript** | Fork+exec on every AS call = 50-200ms; blocks racing translator budget | py-applescript (NSAppleScript in-process) |
| **PyObjC CGEvent tap** | CFRunLoop fights asyncio loop, drops events under load | Swift sidecar over unix socket |
| **CALayer-based ghost cursor** | Documented WindowServer perf bug at >10 actions/sec | NSView.draw() (architecture doc L7) |
| **vcrpy / pytest-recording for cassettes** | HTTP-only; doesn't see AX/CDP/AppleScript actions | Custom JSON Lines cassette format |
| **Inngest / Restate / Temporal for durability** | Server runtime requirement; serverless event model is wrong fit for desktop CU loop | LangGraph PostgresSaver 3.0.5 |
| **ChromaDB for episodic memory** | Server-mode even in "embedded"; metadata filtering we don't need at this scale | faiss-cpu 1.13.2 |
| **loguru for action log** | Buggy contextvar propagation across asyncio task groups | structlog 25.5.0 |
| **Full recursive AX tree walks** | 15-20s on Safari (architecture hard rule) | depth-limited 3-level subtree (Vision framework crops) |
| **Intrinsic LLM self-correction** | 16-27% accuracy (papers 2601.00828, 2412.14959) | External oracle verifiers (L0-L3 ensemble) |
| **AppleScript at >1Hz** | 50-200ms blocks app event loop, destabilizes target apps | Use AS only as the slow channel in racing; staggered_race with 500ms head-start |
| **AX poll at >30 req/sec** | cmux #2985 — stalls target Cocoa app's main thread | Push-event subscription via AXObserver |
## Stack Patterns by Variant
- T2 CDP via `cdp-use` (relaunch with `--remote-debugging-port`)
- Verifier: CDP DOM mutation events + AX subtree backup
- Action: C5 CDP `Input.dispatchMouseEvent` (passes through iframes)
- T3 AppleScript via `py-applescript`
- Verifier: AX subtree + push events
- Action: C4 AppleScript (semantic) primary, C2 AX kAXPress secondary
- T1 AX via raw PyObjC HIServices
- Verifier: AXObserver push events (kAXValueChanged etc.)
- Action: C2 AX kAXPress, C1 SLEventPostToPid for HID
- T4 Vision OCR via `ocrmac` + Screen2AX synthetic tree (MacPaw, Sprint 4)
- T7 SoM via uitag (Apple Vision + YOLO11 MLX, Sprint 4)
- Verifier: pixel ROI dHash via ImageHash + L3 LLM fallback
- Action: C1 SLEventPostToPid (background, no cursor warp)
- T5 Pixel via `mlx-vlm` UI-TARS-1.5 grounding + clipboard side-channel
- Action: C3 CGEvent.postToPid with idempotency token
## Version Compatibility
| Package | Compatible With | Notes |
|---|---|---|
| `pyobjc==12.1` | macOS 11+, Python 3.9+ | Includes Vision, Accessibility, AppKit, Foundation framework wrappers all at 12.1 |
| `apple-fm-sdk==0.1.1` | macOS 26+, Python 3.10+, Xcode 26 SDK | Apple Intelligence must be ON; will hard-fail at import otherwise |
| `mlx-vlm==0.4.4` | Apple Silicon only, macOS 13+, Python 3.10+ | Pulls `mlx>=0.20` |
| `langgraph-checkpoint-postgres==3.0.5` | LangGraph 0.2+, Postgres 14+ | Requires `psycopg[binary]>=3.1` |
| `faiss-cpu==1.13.2` | Python 3.9-3.13 | macOS arm64 wheels work; no GPU FAISS on Mac (use CPU) |
| `structlog==25.5.0` | Python 3.9+ | Full asyncio + contextvars support |
| `ocrmac==1.0.1` | macOS 11+ | Pulls `pyobjc-framework-Vision` automatically |
| `py-applescript==1.0.3` | macOS any, Python 3.x | Pulls `pyobjc` |
| `ImageHash==4.3.2` | Python 3.7+ | Needs Pillow + numpy + scipy |
| `cdp-use` | (vendored in browser-harness) | Already version-pinned in browser-harness — match that |
## Sources
### Verified live (2026-04-29)
- [PyPI atomacos](https://pypi.org/project/atomacos/) — confirmed 3.3.0, last release 2021-05-24 (HIGH)
- [PyPI pyatomac](https://pypi.org/project/pyatomac/) — confirmed 2.0.7, last release 2018-06-01 (HIGH)
- [PyPI atomac](https://pypi.org/project/atomac/) — confirmed 1.1.0, last release 2013 (HIGH)
- [PyPI pyobjc 12.1](https://pypi.org/project/pyobjc/) — confirmed 12.1, 2025-11-14 (HIGH)
- [PyPI mlx-vlm 0.4.4](https://pypi.org/project/mlx-vlm/) — confirmed 0.4.4, 2026-04-04 (HIGH)
- [PyPI inngest 0.5.18](https://pypi.org/project/inngest/) — confirmed 0.5.18, 2026-03-11 (HIGH)
- [PyPI langgraph-checkpoint-postgres 3.0.5](https://pypi.org/project/langgraph-checkpoint-postgres/) — confirmed 3.0.5, 2026-03-18 (HIGH)
- [PyPI structlog 25.5.0](https://pypi.org/project/structlog/) — confirmed 25.5.0, 2025-10-27 (HIGH)
- [PyPI ImageHash 4.3.2](https://pypi.org/project/ImageHash/) — confirmed 4.3.2, 2025-02-01 (HIGH)
- [PyPI faiss-cpu 1.13.2](https://pypi.org/project/faiss-cpu/) — confirmed 1.13.2, 2025-12-24 (HIGH)
- [PyPI vcrpy 8.1.1](https://pypi.org/project/vcrpy/) — confirmed 8.1.1, 2026-01-04, HTTP-only (HIGH)
- [PyPI ocrmac 1.0.1](https://pypi.org/project/ocrmac/) — confirmed 1.0.1, 2026-01-08 (HIGH)
- [PyPI apple-fm-sdk 0.1.1](https://pypi.org/project/apple-fm-sdk/) — confirmed 0.1.1, 2026-03-08 (HIGH)
- [PyPI py-applescript 1.0.3](https://pypi.org/project/py-applescript/) — confirmed 1.0.3, 2022-01-23 (HIGH; API frozen)
### Official docs verified
- [Apple Foundation Models SDK for Python](https://apple.github.io/python-apple-fm-sdk/getting_started.html) — package name `apple-fm-sdk`, requires macOS 26 + Python 3.10 + Xcode 26 (HIGH)
- [PyObjC API Notes: HIServices](https://pyobjc.readthedocs.io/en/latest/apinotes/HIServices.html) — confirms accessibility surface (HIGH)
- [PyObjC API Notes: Vision](https://pyobjc.readthedocs.io/en/latest/apinotes/Vision.html) — confirms VNRecognizeTextRequest support (HIGH)
- [LangGraph Postgres Checkpointer reference](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver) — confirms async API (HIGH)
### Model availability
- [mlx-community/UI-TARS-1.5-7B-4bit](https://huggingface.co/mlx-community/UI-TARS-1.5-7B-4bit) — MLX-converted, mlx-vlm 0.1.25+ compatible (HIGH)
- [mlx-community/UI-TARS-1.5-7B-6bit](https://huggingface.co/mlx-community/UI-TARS-1.5-7B-6bit) — coord-quantization issue documented (MEDIUM)
- [showlab/ShowUI](https://github.com/showlab/ShowUI) — CVPR 2025 paper accepted; ShowUI-2B publicly available on HF; MLX conversion exists in community (MEDIUM — verify exact model card before download)
### Comparisons
- [Logging in Python: Top 6 Libraries (Better Stack 2026)](https://betterstack.com/community/guides/logging/best-python-logging-libraries/) — structlog vs loguru benchmarks (MEDIUM)
- [Durable Execution Patterns for AI Agents (Zylos Feb 2026)](https://zylos.ai/research/2026-02-17-durable-execution-ai-agents) — Inngest vs LangGraph vs Restate (MEDIUM)
- [FAISS vs LanceDB vs Chroma comparison](https://slashdot.org/software/comparison/Faiss-vs-LanceDB-vs-chroma/) — embedded library vs server tradeoff (MEDIUM)
### Architecture references (locked, in vault)
- `~/thinker/vault/research/basicCtrl-self-healing-framework-2026-04-29.md` — THE blueprint
- `~/thinker/vault/research/cua-autonomous-self-healing-framework-2026-04-29.md` — driver registry context
- `~/thinker/research-clones/trycua-cua/libs/cua-driver/` — Swift driver source
- `~/thinker/research-clones/ghost-os/` — CGEvent tap reference (LearningRecorder.swift:62-88)
### Negative claims verified
- vcrpy is HTTP-only (verified — has no AX/CDP/AppleScript surface; documentation confirms `requests`/`urllib3`/`httpx`/`aiohttp` interception only)
- pyatomac last release 2018-06-01 (verified via PyPI JSON API)
- atomac last release 2013-02-13 (verified via PyPI JSON API)
- atomacos last release 2021-05-24 (verified via PyPI JSON API)
- "traceops" — could not verify existence as a Python package on PyPI as of 2026-04-29; the architecture doc cite may refer to a pattern, not a library
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, or `.github/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

## Current Status & Next Step

**Milestone:** v1.0-released (2026-05-01)
**Phases:** 6 / 6 complete
**Plans:** 61 / 61 complete (100%)
**Tests:** 525+ unit, 27 integration, all green
**Status:** Post-v1.0 hardening — observability + Phase 4 cognition wire-up

See `.planning/STATE.md` and `.planning/MILESTONE-V1.0.md` for full state.

### Active work (post-v1.0 hardening)
Plan: `~/.claude/plans/ultraplan-finish-deep-stearns.md`

| Phase | Goal | Status |
|---|---|---|
| A | Truth-up + preflight + MCP boot proof | in progress |
| B | Phase 4 cognition wire (B3/B4 real, graceful disable) | pending |
| C | Observability CLIs + 5 new e2e gates | pending |
| D | verify-everything.sh + canary integration | pending |

### Standard Flow (legacy, per pre-v1.0 phase)
```
/gsd-discuss-phase N   →  N-CONTEXT.md  (decisions)
/gsd-plan-phase N      →  N-RESEARCH.md + N-PLAN.md  (tasks)
/gsd-execute-phase N   →  code + atomic commits per plan
/gsd-verify-work N     →  N-VERIFICATION.md  (UAT)
```

Shortcuts:
- `/gsd-progress` — where am I, what's next
- `/gsd-resume-work` — restore context after `/clear`
- `/gsd-next` — auto-route to next logical step
- `/gsd-fast` — trivial inline task, no planning overhead
- `/gsd-autonomous` — discuss → plan → execute all phases unattended (use with care)

### Where to find things
| Artifact | Path |
|---|---|
| Vision + decisions | `.planning/PROJECT.md` |
| All 79 requirements | `.planning/REQUIREMENTS.md` |
| Phase breakdown | `.planning/ROADMAP.md` |
| Tech stack (locked) | `.planning/research/STACK.md` |
| Architecture blueprint | `.planning/research/ARCHITECTURE.md` |
| Pitfall taxonomy (29) | `.planning/research/PITFALLS.md` |
| Feature inventory | `.planning/research/FEATURES.md` |
| Session state | `.planning/STATE.md` |
| Per-phase artifacts | `.planning/phases/NN-slug/` (created when phase starts) |

### Architecture canonical ref
`~/thinker/vault/research/basicCtrl-self-healing-framework-2026-04-29.md` — THE locked maximalist blueprint. Downstream agents MUST read before planning.

### Hard rules for any agent on this project
- **Never** edit Swift code under `libs/cua-driver/` — overlay only.
- **Never** run a full recursive AX tree walk (15-20s on Safari). Always depth-limited (3 levels max).
- **Never** poll AX at >20 calls/sec/pid (cmux #2985 stalls Cocoa main thread).
- **Always** subscribe AXObserver push notifications BEFORE the action fires.
- **Always** use deterministic ensemble first (L0→L1→L2). LLM (L3) only when ensemble confidence < 0.30.
- **Destructive actions** (submit/send/delete) — single-channel only, never raced.



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
