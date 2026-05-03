# Stack Research — basicCtrl

**Domain:** Self-healing autonomous Mac CU framework — Python overlay above Swift driver
**Researched:** 2026-04-29
**Confidence:** HIGH (versions verified live against PyPI / official docs / Apple)
**Author note:** Versions current as of 2026-04-29. Architecture is locked. This is the **prescriptive build list** — pick this, not alternatives, unless flagged.

---

## TL;DR — pick this

```
Language       Python 3.12 + minimal Swift 6
Runtime        uv (fast pip)
AX bindings    raw PyObjC HIServices  + atomacos 3.3 (selective copy of helpers)
AppleScript    py-applescript (NSAppleScript via PyObjC, in-process)
Vision OCR     ocrmac 1.0.1 (VNRecognizeTextRequest wrapper)
CGEvent tap    Swift sidecar (.listenOnly bg thread) — NOT pyobjc
NSPanel HUD    Swift (SwiftUI + AppKit) — thin glue layer
Local VLM      mlx-vlm 0.4.4 + UI-TARS-1.5-7B-4bit + ShowUI-2B
Apple FM       apple-fm-sdk 0.1.1 (tier-0 classifier)
Vector store   FAISS (faiss-cpu 1.13.2)  for episodic memory
Image hash     ImageHash 4.3.2 (dHash) + Pillow
Logging        structlog (NDJSON to action_log.ndjson)
Durable exec   LangGraph PostgresSaver 3.0.5
Trace replay   Custom (vcrpy is HTTP-only — write our own cassette format)
Browser CDP    cdp-use (already in browser-harness, reuse)
Async runtime  asyncio + anyio (raise()-friendly task groups)
```

**Total Python deps: ~18 libs.** Total Swift LOC: ~300 (visualizer + SkyLight bridges + CGEvent tap sidecar).

---

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

**Why fork-and-copy not depend:** atomacos last release was 2021-05-24 — five years stale. It still works because PyObjC + AX SPI is stable, but it doesn't support the private SPIs we need (`_AXObserverAddNotificationAndCheckRemote`, `_AXUIElementGetWindow`). We need raw PyObjC + dlsym for those anyway. Best path: take atomacos's 30-line `NativeUIElement` wrapper as a starting point and own the code.

### AppleScript Bridge

| Choice | Decision |
|---|---|
| **py-applescript 1.0.3** (NSAppleScript via PyObjC, in-process) | **CHOSEN** |
| ~~subprocess osascript~~ | REJECT — fork+exec on every call, 50-200ms overhead, blocks event loop |
| ~~PyObjC OSAKit raw~~ | REJECT — more boilerplate than py-applescript wraps for zero benefit |

**Why:** NSAppleScript runs in-process on the Python AppKit run loop. py-applescript is thin (~200 LOC), translates Python types ↔ AppleScript automatically, persists compiled scripts across calls. Last release 2022-01-23 but the API is **frozen** — Apple hasn't changed NSAppleScript since 10.7. The "abandoned" red flag is misleading because there is nothing to update. Wrap in a tiny `staggered_race()` helper to give other channels a 500ms head start (research note in the architecture: AS lags state).

**Confidence:** HIGH. Direct verification: pyobjc 12.1 ships `Foundation.NSAppleScript` already; py-applescript just wraps it.

### On-Device VLM Grounding (the ANE pipeline)

| Tier | Model | Serving | Purpose |
|---|---|---|---|
| **Tier 0 (binary classify)** | Apple FM 3B | `apple-fm-sdk 0.1.1` | Routing decisions — "is this dialog modal?" "is element a text field?" — 50-200ms/token, free, ANE |
| **Tier 1 (grounding)** | **UI-TARS-1.5-7B (4-bit MLX)** | `mlx-vlm 0.4.4` | Primary grounder — pixel→element coords, parallel to planner |
| **Tier 1b (faster fallback)** | **ShowUI-2B (4-bit MLX)** | `mlx-vlm 0.4.4` | When UI-TARS-1.5 coord-quantization bug hits (mlx-vlm #330) — 2B model, 75% screenspot accuracy, smaller footprint |
| **Tier 2 (planner)** | Claude Opus 4 (cloud) | `anthropic` SDK | Cognition only, not grounding |

**Why mlx-vlm:** It's the only mature MLX-native VLM serving stack on Apple Silicon. v0.4.4 (April 2026) has UI-TARS-1.5 + ShowUI-2B + Qwen2.5-VL conversions in `mlx-community/`. Pre-quantized 4-bit and 6-bit models drop into Mac unified memory directly via memory-mapped weights — no GPU transfer cost.

**Why both UI-TARS and ShowUI:** UI-TARS-1.5 SOTA but has a known coord-quantization bug on certain screen geometries (mlx-vlm issue #330 confirmed). ShowUI-2B is the fallback — half the params, 5x faster on element localization, lower coord-bug risk.

**Confidence:** HIGH for mlx-vlm + UI-TARS, MEDIUM for ShowUI MLX conversion availability (verify model card on first use, fall back to PyTorch+MPS if MLX conversion broken).

**Apple FM SDK:** `pip install apple-fm-sdk` v0.1.1 (released March 8, 2026). Requires macOS 26 + Apple Intelligence enabled + Xcode 26 SDK. Caveat from the architecture doc: 4096 ctx limit, 50% hallucinated params on complex schemas → **binary/small-enum decisions only**.

### Vision Framework via PyObjC

| Choice | Version | Why |
|---|---|---|
| **ocrmac** | 1.0.1 (Jan 2026) | Thin wrapper around `VNRecognizeTextRequest` + `VNImageRequestHandler` via pyobjc-framework-Vision |
| `pyobjc-framework-Vision` | 12.1 (transitive) | Direct `VNFeaturePrint` for template match, custom request types |

**Why ocrmac for OCR + raw PyObjC for everything else:** ocrmac handles the boilerplate (NSImage, request handler, observation parsing, RTL/CJK) for OCR specifically. For `VNFeaturePrint` (template match in L1 verifier) + `VNDetectRectanglesRequest` (bbox for SoM grounding), drop directly to `pyobjc-framework-Vision` — ocrmac doesn't cover these.

**Confidence:** HIGH.

### CGEvent Tap (Continuous Learning Recorder)

**DECISION: Swift sidecar, NOT pyobjc.**

| Choice | Verdict |
|---|---|
| **Swift CGEvent tap on bg DispatchQueue** | **CHOSEN** — `LearningRecorder.swift` from ghost-os pattern, IPC over unix socket to Python overlay |
| ~~PyObjC CGEvent tap on Python thread~~ | REJECT — CGEventTapCreate requires CFRunLoop on a real thread; Python's GIL + asyncio loop fights this; documented seg-faults in tensorflow/swift#224, real CGEventTaps from Python fail intermittently when the Python interpreter is GC-stopped |

**Why Swift sidecar:** ghost-os already proved the pattern (LearningRecorder.swift:62-88). The tap MUST be on a real Cocoa run loop (`CFRunLoopAddSource`) so that timing is microsecond-stable. Putting it in Python means CFRunLoop integration via PyObjC's `objc.runConsumer` which competes with asyncio. The tap drops events when the Python loop is busy. **A 50-line Swift sidecar that emits NDJSON to a unix socket is the right answer.**

Sidecar interface: `/tmp/cua-learning.sock` — one JSON event per line, Python reads via `asyncio.open_unix_connection`.

**Confidence:** HIGH (architecture doc + ghost-os reference + research on CFRunLoop+GIL conflict).

### Image Hashing

| Choice | Version | Why |
|---|---|---|
| **ImageHash** | 4.3.2 (Feb 2025) | dHash, pHash, wHash — pure NumPy; ROI hashing trivial via PIL crop |
| **Pillow** | latest (transitive) | Required for ImageHash; also for fast PNG/JPEG encode of screenshots |

**Why dHash:** difference-hash is research-validated as faster than pHash and tolerant to scaling/compression — exactly what L1 verifier needs (1-3ms target, run in tight loop). 64-bit hashes Hamming-distance compare. Drop into the L1 cheap diff layer next to `NSPasteboard.changeCount`.

**Confidence:** HIGH.

### Vector Store — Episodic Memory

**DECISION: FAISS (faiss-cpu 1.13.2)**, not LanceDB or ChromaDB.

| Choice | Verdict |
|---|---|
| **faiss-cpu 1.13.2** | **CHOSEN** — embedded library, 100k vectors in <100MB, no server, IndexFlatL2 trivial, IVFPQ when we hit 1M+ |
| ChromaDB 1.5.8 | REJECT — has a server runtime even in "in-process" mode; we don't need metadata filtering at Q-store scale (we filter on `(bundleID, task_class)` in Python before vector search) |
| LanceDB 0.30 | NOT RECOMMENDED — fine choice but adds Apache Arrow dep weight; FAISS is simpler for our scale |

**Why FAISS:** The architecture doc explicitly calls out `FAISS local` (Sprint 8). Episodic memory keys are `(app, task_class, state_fingerprint)` — Python dict lookup → bucket → FAISS subindex. We don't need a "vector database" — we need a **library**. FAISS won the comparison years ago for embedded Python search and stays winning. C++ core, pickle the index between sessions.

**Confidence:** HIGH.

### Structured Event Logging

**DECISION: structlog**, not loguru.

| Choice | Verdict |
|---|---|
| **structlog 25.5.0** (Oct 2025) | **CHOSEN** — context binding via `contextvars` works correctly across asyncio task groups; native NDJSON renderer; ~25% faster than loguru on JSON; processor pipeline lets us inject Hoare-triple metadata at every log call |
| loguru 0.7.3 (Dec 2024) | REJECT — context propagation across asyncio is buggy (loguru #1083); slower JSON; over-eager file rotation defaults; "abandoned-ish" maintenance |

**Why structlog:** The action_log.ndjson is the audit trail of every Hoare triple — must be deterministic, structured, async-safe. structlog's `bind_contextvars()` lets us attach `session_id`, `step_idx`, `tier_badge` once and have every nested log line carry it. Output goes through `structlog.processors.JSONRenderer()` directly to `~/.cua/sessions/<id>/action_log.ndjson`.

**Confidence:** HIGH.

### NSPanel Transparent Overlay (Swift glue)

| Choice | Why |
|---|---|
| **Pure SwiftUI + AppKit hybrid in Swift sidecar** | NSPanel + SwiftUI hosting view; `.popUpMenu` level, `ignoresMouseEvents=true`, `canJoinAllSpaces`, `SCContentFilter excludingApplications: [self]` — verbatim from architecture doc L7 recipe |
| Talks to Python overlay via | unix socket NDJSON — overlay sends `{cmd: "ghost_cursor", x, y, t}`, `{cmd: "highlight", bbox, label, tier}`, `{cmd: "hud_action", text, status}` |

**Critical gotcha:** Use `NSView.draw()` for ghost cursor, NOT CALayer. There's a documented WindowServer perf bug with CALayer-based cursor overlays (architecture doc L7 + mac-computer-use ref). Drop frames at >10 actions/sec.

**Confidence:** HIGH (verified recipe in architecture doc).

### Trace-Replay Cassettes

**DECISION: Write a custom cassette format, do NOT reach for vcrpy.**

| Choice | Verdict |
|---|---|
| **Custom JSON Lines cassette** | **CHOSEN** — `cassettes/<task_hash>.jsonl`, one entry per step: `{step_idx, hoare_pre, action_canonical, hoare_post, screenshot_pHash, ax_subtree_hash, healed_selectors[]}` |
| vcrpy 8.1 | REJECT for this purpose — vcrpy is **HTTP-only**. Records HTTPX/requests calls. Useless for AX/CDP/AppleScript actions. |
| `pytest-recording` | REJECT — same reason, HTTP-only |
| traceops | REJECT — could not verify it exists as a Python package on PyPI as of 2026-04-29 (search returned nothing); the architecture doc cites it but it may be a pattern, not a library |

**Why custom:** Stagehand's `AgentCache.ts:573-624` is the proven model and **it's a custom format, not a library**. The "broken-step → live re-execute → write-back" pattern needs domain-specific keys (`bundleID`, `role_path`, AX-tree-hash) that no generic library provides. ~150 LOC of custom code + structlog for the writer + Pydantic for the schema. Keep cassette files alongside the action log:

```
~/.cua/sessions/<id>/
  cassettes/
    bundle.com.apple.mail__compose_email__a3f7.jsonl
    bundle.com.figma.Desktop__export_frame__91bc.jsonl
```

**Schema (Pydantic v2):**
```python
class CassetteStep(BaseModel):
    step_idx: int
    timestamp_ns: int
    pre: HoarePre
    action: ActionCanonical  # tier (T1-T5), channel (C1-C5), payload
    post: HoarePost
    selectors: list[Selector]  # original + healed
    screenshot_phash: str
    ax_subtree_hash: str
```

**Confidence:** MEDIUM-HIGH — pattern from Stagehand is proven; "no off-the-shelf library" is a defensible negative claim (vcrpy/pytest-recording verified HTTP-only).

### Durable Execution

**DECISION: LangGraph PostgresSaver 3.0.5**, not Inngest, not Restate.

| Choice | Verdict |
|---|---|
| **`langgraph-checkpoint-postgres` 3.0.5** (March 2026) | **CHOSEN** — runs against a local Postgres (already on Akeil's Mac via `brew install postgresql`), `AsyncPostgresSaver.from_conn_string()`, autocommit + dict_row, persists graph state per node |
| Inngest 0.5.18 (Mar 2026) | REJECT — event-driven serverless model is wrong fit; needs Inngest dev server running; designed for backend jobs, not desktop CU loops; would force everything through HTTP step boundaries |
| Restate (March 2026) | REJECT — sidecar HTTP interceptor; same fit problem as Inngest; production-grade overkill for single-user local |
| Temporal | REJECT — full cluster setup; way too heavy |

**Why LangGraph PostgresSaver:**
- **Graph-shaped state matches our architecture** — translator → action → verifier is literally a LangGraph
- **Local Postgres** = zero new infra (already needed for FAISS metadata anyway)
- **Crash → resume from last checkpoint** works exactly like the architecture doc L8 spec
- Each translator call wraps as a node; Postgres row per state transition
- **Architecture doc explicitly lists this as one of two options** — pick the lighter one

**Setup:**
```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
checkpointer = await AsyncPostgresSaver.from_conn_string(
    "postgresql://localhost:5432/basicctrl"
).__aenter__()
await checkpointer.setup()
```

**Confidence:** HIGH.

### Browser CDP

| Choice | Source | Why |
|---|---|---|
| **cdp-use** (browser-harness's choice) | already vendored in browser-harness | Reuse — Akeil uses browser-harness daily, must remain compatible; CDP for Electron apps (Slack/Discord/VS Code/Cursor/Figma) is the same protocol |
| asyncio websockets | for raw frames | When cdp-use's typed wrappers don't expose what we need (private CDP methods) |

The architecture doc says: *"`cdp-use` is only for `CDPClient.send_raw`. Prefer raw CDP strings over typed wrappers."* Honor that.

**Confidence:** HIGH.

---

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

---

## Development Tools

| Tool | Purpose | Notes |
|---|---|---|
| **uv** | Package manager | Already what trycua uses; 10-100× pip |
| **direnv** | Per-project env activation | TCC-grant-required env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`) |
| **Postgres 16** (local brew) | Durable execution backend | `brew install postgresql@16 && brew services start postgresql@16` |
| **Xcode 26** | Required for apple-fm-sdk + Swift glue | macOS 26 SDK |
| **swift-format** | Format Swift sidecars | trycua's existing config |
| **Instruments** | Profiling Python ↔ Swift IPC | Critical for the racing translator timing |

---

## Installation

```bash
# Python overlay (uv-managed)
uv venv --python 3.12
source .venv/bin/activate

uv pip install \
  pyobjc==12.1 \
  ocrmac==1.0.1 \
  py-applescript==1.0.3 \
  apple-fm-sdk==0.1.1 \
  mlx-vlm==0.4.4 \
  faiss-cpu==1.13.2 \
  ImageHash==4.3.2 \
  Pillow \
  structlog==25.5.0 \
  langgraph-checkpoint-postgres==3.0.5 \
  psycopg[binary] \
  pydantic \
  httpx \
  anthropic \
  openai \
  anyio \
  websockets

# Dev
uv pip install -D pytest pytest-asyncio mypy ruff rich

# Local infra
brew install postgresql@16
brew services start postgresql@16
createdb basicctrl

# Models (one-time download to ~/.cache/huggingface)
huggingface-cli download mlx-community/UI-TARS-1.5-7B-4bit
huggingface-cli download mlx-community/ShowUI-2B-4bit  # verify availability first

# Apple FM (requires Xcode 26 + Apple Intelligence enabled)
# apple-fm-sdk pulls Swift framework headers — first import compiles bridge
python -c "import apple_fm_sdk; print('FM SDK ready')"

# Swift sidecars (built once)
cd swift/
xcodebuild -scheme CuaSidecar -configuration Release
```

---

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

---

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

---

## Stack Patterns by Variant

**If targeting Electron app (Slack/Discord/VS Code/Figma/Cursor/Notion):**
- T2 CDP via `cdp-use` (relaunch with `--remote-debugging-port`)
- Verifier: CDP DOM mutation events + AX subtree backup
- Action: C5 CDP `Input.dispatchMouseEvent` (passes through iframes)

**If targeting Apple 1P / .sdef app (Mail/Calendar/Notes/Safari/iWork/Finder):**
- T3 AppleScript via `py-applescript`
- Verifier: AX subtree + push events
- Action: C4 AppleScript (semantic) primary, C2 AX kAXPress secondary

**If targeting modern AppKit / SwiftUI / Catalyst native:**
- T1 AX via raw PyObjC HIServices
- Verifier: AXObserver push events (kAXValueChanged etc.)
- Action: C2 AX kAXPress, C1 SLEventPostToPid for HID

**If targeting canvas / WebGL / opaque (Figma canvas / Blender / games):**
- T4 Vision OCR via `ocrmac` + Screen2AX synthetic tree (MacPaw, Sprint 4)
- T7 SoM via uitag (Apple Vision + YOLO11 MLX, Sprint 4)
- Verifier: pixel ROI dHash via ImageHash + L3 LLM fallback
- Action: C1 SLEventPostToPid (background, no cursor warp)

**If targeting truly opaque (Warp terminal, custom-drawn):**
- T5 Pixel via `mlx-vlm` UI-TARS-1.5 grounding + clipboard side-channel
- Action: C3 CGEvent.postToPid with idempotency token

---

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

**Critical:** all PyObjC framework wrappers (`pyobjc-framework-*`) must be the **same version** (12.1) — they share C-extension ABI. Pin them all explicitly or let `pyobjc==12.1` pull them transitively.

---

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

---

*Stack research for: basicCtrl (self-healing autonomous Mac CU)*
*Researched: 2026-04-29*
*Architecture: locked. Versions: live-verified. Confidence: HIGH on libraries, MEDIUM on ShowUI MLX availability.*
