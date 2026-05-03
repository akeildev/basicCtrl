# Phase 2: Translators + Racing - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Source:** /research-driven (4-sub-agent fan-out, 2026-04-30)

<domain>
## Phase Boundary

Phase 2 ships 5 protocol translators (T1 AX / T2 CDP / T3 AppleScript / T4 Vision/uitag/ocrmac / T5 Pixel) and 5 racing action channels (C1 SkyLight-as-public-CGEvent / C2 AX kAXPress / C3 CGEvent.postToPid / C4 AppleScript / C5 CDP Input.dispatchMouseEvent), with atomic idempotency tokens, per-action-class race policy, and AppleScript stagger. Phase 1's verifier decides race winners; state graph receives writes from all translators.

**In scope (Phase 2):**
- All 5 translators T1-T5 implemented as Python modules under `basicctrl/translators/`
- All 5 channels C1-C5 implemented as Python modules under `basicctrl/actions/channels/`
- Race orchestrator (`asyncio.wait(FIRST_COMPLETED)` + cancellation)
- Atomic idempotency token storage (in-memory dict + NDJSON trace)
- Per-action-class race policy enforcement (read/focus/scroll/hover race; type/set_value/drag/destructive single-channel)
- AppleScript 500ms stagger
- AX rate-limit guard (already in place from Phase 1; translators must use it)
- MCP surface extension: `click_with_healing` adds race_policy params; new sibling tools for type/scroll/set_value/destructive
- Top-12 app association map + AppProfile classifier integration

**Out of scope (defer to other phases):**
- Failure classifier + 5-branch recovery → Phase 3
- Cassette write-back / heal selectors → Phase 3
- Cognition + ensemble vote + speculative → Phase 4
- Continuous learning (CGEvent tap recorder) → Phase 4
- Visualizer (ghost cursor + HUD + 60fps recording) → Phase 5
- Swift SkyLight bridge (real `SLEventPostToPid`) → Phase 6 (Phase 2 uses public CGEvent.postToPid as C1 implementation; SkyLight is a no-op upgrade later)
- DYLD inject into running Electron renderers → Phase 6
- Durable LangGraph PostgresSaver wrap of every translator call → Phase 6 (Phase 1 has baseline durability; Phase 2 doesn't add cross-call durability)
- Screen2AX synthetic AX tree → deferred until Phase 3 spike or skipped (research repo, conflicts with our pyobjc 12.1)

</domain>

<decisions>
## Implementation Decisions

### Translator Stack (T1-T5)

- **D-01:** T1 AX translator wraps Phase 1's `basicctrl.ax.*` (TokenBucket rate limiter, depth-limited walker, AXObserver bridge, modal probe, typed errors). T1 is in-process Python via PyObjC HIServices — no Swift IPC needed. No new AX primitives in Phase 2.
- **D-02:** T2 CDP translator takes `cdp-use==1.4.5` as a direct project dependency (PyPI, MIT, last upload 2026-02-22, maintained by `browser-use` org — same upstream as browser-harness). Confirmed via local read of `/Users/akeilsmith/browser-harness/pyproject.toml` and `/Users/akeilsmith/browser-harness/daemon.py:6` (`from cdp_use.client import CDPClient`). Electron uses identical CDP wire format per https://www.electronjs.org/docs/latest/api/debugger ("alternate transport for Chrome's remote debugging protocol").
- **D-03:** T2 CDP translator does NOT vendor or runtime-import browser-harness. Browser-harness is a flat-script tool (`py-modules = ["run", "helpers", "daemon", "admin"]` — no package), uses hard-coded `/tmp/bu-{NAME}.sock`, designed for one-shot CLI invocation, not in-process import. basicCtrl must coexist with browser-harness — both call cdp-use directly, neither owns the other.
- **D-04:** T3 AppleScript translator uses `py-applescript==1.0.3` (in-process NSAppleScript via PyObjC OSAKit) on a dedicated `concurrent.futures.ThreadPoolExecutor(max_workers=2)`. Never `osascript` subprocess. Per Pitfall P5 (50-200ms baseline) and `macOS26-Agent/Conversation.swift:245-248` (NSAppleScript on detached background thread can hang waiting for AppleEvent reply — must NOT run on main asyncio loop thread).
- **D-05:** T4 Vision translator ships `uitag==0.6.0` (PyPI 2026-04-09, MIT, https://github.com/laywens/uitag — Apple Vision + YOLO11 MLX, 90.8% ScreenSpot-Pro coverage) + `ocrmac==1.0.1` (PyPI 2026-01-08, already in Phase 1 dependencies). uitag's `from uitag import run_pipeline` returns `PipelineResult` with `Detection` dataclass (label, x, y, w, h, confidence, source, som_id, element_type) → adapt directly to UIElement.
- **D-06:** T4 does NOT include MacPaw/Screen2AX in Phase 2. Reasons: (a) NOT on PyPI (research repo at https://github.com/MacPaw/Screen2AX), (b) last commit 2025-07-23 = 8 months stale, (c) pinned `pyobjc==10.3.1` conflicts with our `pyobjc==12.1`, (d) heavy deps (ultralytics, torch 2.6, transformers 4.48, opencv, streamlit). uitag covers the same use case (synthetic UIElement from screenshot) with maintained code.
- **D-07:** T5 Pixel translator uses `CGWindowList` + `pyobjc-framework-Quartz` for screen reads and `imagehash==4.3.2` dHash for pixel ROI hashing (already in Phase 1). For element coordinate resolution on non-AX apps, T5 delegates to T4's uitag pipeline.
- **D-08:** Translator dependency conflict — uitag's pyproject requires `transformers>=5.0.0`; CLAUDE.md stack notes Phase 4 may want `transformers 4.50+` for fallback paths. Pin `transformers>=5.0.0` for Phase 2 (uitag is the load-bearing dep); Phase 4 may install side-by-side via uv extras if 4.x is needed. Verify no mlx-vlm 0.4.4 conflict at install time.

### Race Orchestrator + Channels (C1-C5)

- **D-09:** Race policy is **per-action-class**, encoded on `ActionCanonical.action_type` and validated by a Pydantic enum + module-level dispatch table. The `Literal["READ","MUTATE"]` kind field already pinned in Phase 1's `basicctrl/state/causal_dag.py:35` is the speculation-safety gate; Phase 2 adds a separate orthogonal `RacePolicy` enum at the channel-orchestrator level.
- **D-10:** RACE allowlist (multiple channels fire concurrently with idempotency token):
  - `click_button` / `click` (locked)
  - `focus` (locked)
  - `scroll_to_position` (absolute coords — idempotent)
  - `hover` (idempotent — both channels deliver mouseover to same element, no state risk)
- **D-11:** SINGLE-CHANNEL allowlist (one channel only, picked by AppProfile.translator_priority):
  - `submit` / `send` / `delete` / `confirm` (locked, P1)
  - `type_into_focused` (each channel inserts text → race = duplicate chars)
  - `set_value` (replace semantics; AX kAXValue and AS "set value" can disagree on focus side-effects)
  - `drag_and_drop` (stateful: down → move → up; two C3 streams = chaos)
  - `scroll_by_delta` (deltas compound across channels)
  - `key_combo_destructive`: cmd+s, cmd+enter, cmd+w, cmd+z (mutates document/undo stack)
- **D-12:** SAFE-RACE key combos (race allowed):
  - `cmd+c`, `cmd+v` (NSPasteboard.changeCount races are tolerable; clipboard ops are idempotent reads/writes — verified L1 NSPasteboard.changeCount diff in Phase 1 ensemble)
- **D-13:** Race orchestrator is `anyio.create_task_group` with `FIRST_COMPLETED` semantics (the typed wrapper from CLAUDE.md stack §"asyncio + anyio"). Plain asyncio.wait `FIRST_COMPLETED` botches cancellation; anyio task group is correct.
- **D-14:** Channel-translator binding is **soft, not strict**. Default mapping: T1→C2 (kAXPress), T2→C5 (CDP Input.dispatch), T3→C4 (AppleScript), T4→C1 (CGEvent), T5→C3 (CGEvent). Translators can request alternate channels (e.g. T1 selects target via AX but fires via C1 if AX press fails P25 modal probe). The orchestrator picks the channel; translator picks the target.
- **D-15:** AppleScript stagger window = **500ms default, tunable per-recipe**. Recipes carry an optional `as_class: "fast" | "slow"` field. "fast" (e.g. `tell to activate`) uses 0ms stagger. "slow" (e.g. `set value of text field 1`) uses 500ms. Default = 500ms when unspecified. Per Pitfall P5 (50-200ms baseline + std-dev safety) and `macOS26-Agent` AppleEvent hang documentation.

### Idempotency

- **D-16:** Idempotency tokens are stored in **process-local `dict[token_id, ChannelClaim]` guarded by `asyncio.Lock`** + written to **SessionWriter NDJSON trace** for post-mortem and Phase 4 cassette replay. NOT SQLite WAL (overkill for single-process Python overlay; LangGraph Postgres handles graph-level durability separately). The dict is authoritative for live race; the NDJSON is for replay only.
- **D-17:** Token written **BEFORE any channel fires**. Channels read the dict at the start of their fire path; if `claimed=true`, return `Cancelled` immediately. Token format: `{action_id, claimed_at_ns, claimed_by_channel}`.
- **D-18:** OS-level kill-switch — for C1/C3 (CGEvent post-to-pid), each channel's coroutine checks `cancel_event.is_set()` immediately before the syscall. ~50µs window remains but the surface shrinks. AppleEvent at C4 is uncancellable mid-flight; AS stagger (D-15) pushes it past most race windows.
- **D-19:** Idempotency receipts (post-action de-dup) — verifier records `(target_axid, action_kind, ts)` in a 2-second ring buffer. A second post on the same target+kind within 2s is logged as `near_miss_duplicate` and dropped at the verifier.

### App Classifier + Top-12 Association Map

- **D-20:** Phase 1's `basicctrl.profile.classifier.AppProfile.translator_priority` (already shipped) is extended in Phase 2 with a **bundled top-12 association map** at `basicctrl/profile/known_apps.py`. The map is a static dict; classifier consults it BEFORE running capability probes (cache-hit path), so well-known apps skip probe latency.
- **D-21:** Top-12 map (verified bundleIDs via local `defaults read` 2026-04-30):

  | bundle_id | name | electron | sdef | priority | notes |
  |---|---|---|---|---|---|
  | `com.apple.calculator` | Calculator | no | no | T1, T4 | Phase 1 baseline |
  | `com.apple.iWork.Pages` | Pages | no | YES | T3, T1, T4 | iWork canvas non-AX, AS for text/styles |
  | `com.apple.iWork.Numbers` | Numbers | no | YES | T3, T1, T4 | grid via AS |
  | `com.apple.iWork.Keynote` | Keynote | no | YES | T3, T1, T4 | slide canvas non-AX |
  | `com.apple.mail` | Mail | no | YES | T1, T3, T4 | toolbar AX-rich |
  | `com.apple.iCal` | Calendar | no | YES | T1, T3, T4 | sdef = `iCal.sdef` |
  | `com.apple.Notes` | Notes | no | YES | T1, T3, T4 | — |
  | `com.apple.reminders` | Reminders | no | YES | T1, T3, T4 | lowercase `reminders` |
  | `com.apple.Safari` | Safari | no | YES | T1, T3 | full AX walk = 15-20s (P3) |
  | `com.tinyspeck.slackmacgap` | Slack | YES | no | T2 (manual relaunch), T4, T5 | P8 — port 9222 needs `--args --remote-debugging-port=9222` |
  | `com.todesktop.230313mzl4w4u92` | Cursor | YES | no | T2, T4, T5 | todesktop random ID |
  | `md.obsidian` | Obsidian | YES | no | T2, T4, T5 | P8 |

- **D-22:** Bonus map entries (not top-12 but useful — added to known_apps.py):
  - `com.apple.systempreferences` (System Settings) → T1
  - `com.apple.Terminal` → T1, T3 (`Terminal.sdef`)
  - `com.apple.Music` → T1, T3 (`com.apple.Music.sdef`)
  - `com.google.Chrome` → T2, T1
  - `com.apple.Chess` → T4, T5 (no .sdef, Metal board — used as Phase 2 game-canvas test target)
- **D-23:** Discord (`com.hnc.Discord`), Notion (`notion.id`), Linear (CFBundleIdentifier UNVERIFIED — likely `com.linear.LinearMac` per docs) are NOT in the bundled map. They fall through to live capability probe. Akeil's machine doesn't have Linear installed; first probe writes the cache.
- **D-24:** P8 mitigation (Electron CDP launch-only) — classifier surfaces `cdp_available_after_relaunch=true` for Slack/Cursor/Obsidian. Phase 2 healing tool prompts user once with a one-time relaunch dialog: *"Slack must restart to enable T2 CDP racing. Restart now? (Saves your state, restores your tabs.)"* Never silent relaunch. Per `slack.engineering` docs, Slack renderer is multi-process (1 helper per workspace) — when CDP attaches, must filter for the workspace renderer page, not GPU/utility helpers.

### Test Surface (3 success-criteria race winners)

- **D-25:** **T2 CDP wins** test — Slack, manually relaunched with `pkill Slack; open -a "Slack" --args --remote-debugging-port=9222`. Test target: a message row in DMs-to-self channel; selector `[data-qa="message_container"]`. Verify CDP `DOM.querySelector` returns >0 nodes, then C5 `Input.dispatchMouseEvent` at element box. T1/T3/T4/T5 channels fire in parallel and are cancelled when CDP DOM mutation event fires (Phase 1 verifier).
- **D-26:** **T3 AppleScript wins** test — Pages 14 (iWork 2026.x). Test verb: `tell application "Pages" : tell document 1 : make new paragraph style with properties {name:"BoldTest", font name:"Helvetica", font size:14, bold:true} : end tell : end tell`. Why: paragraph styles are first-class AS objects (verified stable since iWork '09 via iworkautomation.com + Apple Discussions thread 250493541). Toolbar buttons themselves are NOT cleanly addressable in Pages's sdef (P12-style limit). T1/T2/T4/T5 lose: T2 has no CDP, T1 AX racks slower than committed AS state, T4/T5 ground but lose to AS verification.
- **D-27:** **T4 SoM + T5 CGEvent fires** test — Apple Chess.app (`/System/Applications/Chess.app`, bundleID `com.apple.Chess`). No .sdef, Metal-rendered 3D board, deterministic 8x8 geometry. Test sequence: click square e2 → screenshot dHash → click square e4 → screenshot dHash → confirm pawn moved. Coords resolved via uitag SoM grounder (T4) → C3 CGEvent.postToPid (T5). Why Chess over Steam alternatives: pre-installed on every macOS (zero install + zero auth + CI-trivial), free + signed + sandboxed, no Steam dep.

### MCP Surface Evolution

- **D-28:** Phase 2 MCP surface uses **option (a)** — extend `click_with_healing` and add domain-named sibling tools. Verified pattern across `modelcontextprotocol/servers/filesystem` (14 separate tools, one per verb), `CursorTouch/Windows-MCP` (Click/Type/Scroll/Move/Shortcut/Wait — exact match for our shape), and Anthropic's own engineering guidance ("too many tools or overlapping tools can also distract agents", https://www.anthropic.com/engineering/writing-tools-for-agents). Reject polymorphic `act(ActionCanonical)` (loses tool-name signal, drops LLM selection accuracy per RAG-MCP arxiv:2505.03275 — 13.62% baseline at N=1100, drops markedly at N>100). Reject `race_*` + `single_channel_*` doubling (10 tools where 5+param does the same job).
- **D-29:** Phase 2 MCP tool list (5 new + 1 extended = 6 total new):
  - `click_with_healing(x, y, bundle_id, pid, label, race_policy="auto", prefer_tier=None, prefer_channel=None)` (extended from Phase 1)
  - `type_with_healing(text, bundle_id, pid, target_label, race_policy="auto", ...)` — single-channel by default per D-11
  - `scroll_with_healing(direction, amount, bundle_id, pid, race_policy="auto", ...)` — race for absolute, single for delta per D-10/D-11
  - `set_value_with_healing(target_label, value, bundle_id, pid, race_policy="auto", ...)` — single-channel by default
  - `send_destructive(target_label, bundle_id, pid)` — single-channel by name; no `race_policy` param (encodes safety in tool name); for submit/send/delete actions
  - `key_combo_with_healing(combo, bundle_id, pid, race_policy="auto", ...)` — orchestrator picks race vs single per D-11/D-12 lookup
- **D-30:** `race_policy` parameter values: `"auto"` (server picks via classifier — DEFAULT), `"race"` (force race; overrides denylist with caller-acknowledged risk), `"single_channel"` (force single; safe override). Phase 2 keeps `auto` aligned with D-09..D-12 dispatch table.
- **D-31:** Total MCP tool count after Phase 2: ~10 (5 new healing tools + 1 destructive + ~4 inherited from trycua via proxy). Well under RAG-MCP ~30 sweet-spot threshold.

### Claude's Discretion

The following are technical implementation details where Claude has flexibility (no user opinion captured):
- Internal module structure under `basicctrl/translators/<t>` and `basicctrl/actions/channels/<c>` — follow Phase 1's per-feature sub-package pattern
- Race orchestrator's exact cancellation propagation order (anyio details)
- pytest fixture composition for the 3 test apps (Slack relaunch helper, Pages AS bootstrap, Chess.app launcher)
- Exact `RacePolicy` enum field names and Pydantic v2 validator wiring
- Telemetry — counter names for race wins per (tier, channel, bundle_id)
- Logging schema for `near_miss_duplicate` + `cdp_relaunch_offered` events

### Folded Todos

None — no pending todos matched Phase 2 scope (gsd-tools `todo match-phase 2` returned 0).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Architecture (locked, in vault)
- `~/thinker/vault/research/basicCtrl-self-healing-framework-2026-04-29.md` — THE locked maximalist blueprint (Phase 2 sections: Translators L3, Actions L4)
- `~/thinker/vault/research/cua-autonomous-self-healing-framework-2026-04-29.md` — driver registry context

### Project planning (in repo)
- `.planning/PROJECT.md` — Vision, key decisions, constraints
- `.planning/REQUIREMENTS.md` — TRANS-01..05, ACT-01..04 (Phase 2 v1 reqs)
- `.planning/ROADMAP.md` §"Phase 2" — Goal + success criteria + pitfalls mitigated
- `.planning/research/ARCHITECTURE.md` §"Component map" §"Build-order dependencies" — Translator + actions placement
- `.planning/research/PITFALLS.md` — P1 (action interference), P2 (AX rate-limit cmux #2985), P3 (full recursive AX), P5 (AS stale-state), P8 (Electron CDP launch-only), P12 (Tahoe SCScreenshotManager regression #870), P14 (AX notifs fail web/Electron), P16 (Bear/Things SQLite drift)
- `.planning/research/STACK.md` — Locked dependencies (cdp-use, py-applescript, pyobjc, anyio, structlog, ImageHash, ocrmac)
- `.planning/research/FEATURES.md` — Translator + channel feature inventory

### Phase 1 deliverables (must read for Phase 2 hooks)
- `basicctrl/state/graph.py` — UIElement, Source, Capability, Bbox, EdgeKind
- `basicctrl/state/causal_dag.py` — ActionCanonical, HoarePre, HoarePost (idempotency token field)
- `basicctrl/profile/classifier.py` — AppProfile + classify() + translator_priority derivation
- `basicctrl/ax/observer.py` — AXEventBridge (CFRunLoop thread + asyncio Queue)
- `basicctrl/ax/rate_limit.py` — TokenBucket (20 calls/sec/pid)
- `basicctrl/ax/walker.py` — depth-limited subtree (3 levels)
- `basicctrl/verifier/axobserver.py` — AXObserverManager.expect (subscribe-before-fire)
- `basicctrl/verifier/aggregator.py` — WeightedVote + ensemble L0+L1
- `basicctrl/persist/session_writer.py` — NDJSON trace (idempotency token sink for D-16)
- `basicctrl/mcp_server/healing_tools.py` — Phase 1's `click_with_healing` (D-29 extends this)
- `basicctrl/mcp_server/main.py` + `proxy.py` — Existing MCP server shape

### External research artifacts (verified 2026-04-30)
- https://pypi.org/project/cdp-use/ — version 1.4.5, MIT (D-02)
- https://github.com/browser-use/cdp-use — typed CDP client, browser-use org
- https://www.electronjs.org/docs/latest/api/debugger — Electron CDP transport
- https://pypi.org/project/uitag/ — version 0.6.0, 2026-04-09 (D-05)
- https://github.com/laywens/uitag — Apple Vision + YOLO11 MLX, 90.8% ScreenSpot-Pro
- https://pypi.org/project/ocrmac/ — version 1.0.1, 2026-01-08 (D-05)
- https://pypi.org/project/py-applescript/ — version 1.0.3 (D-04)
- https://www.anthropic.com/engineering/writing-tools-for-agents — D-28 rationale
- https://arxiv.org/abs/2505.03275 — RAG-MCP tool-count accuracy paper

### Local reference clones (HIGH confidence — verified by direct read 2026-04-30)
- `~/thinker/research-clones/skyvern/skyvern/webeye/actions/action_types.py:4-31` — D-09 action taxonomy comparison
- `~/thinker/research-clones/stagehand/packages/core/lib/v3/types/private/handlers.ts:33-45` — D-09 action enum
- `~/thinker/research-clones/stagehand/packages/core/lib/v3/cache/AgentCache.ts:158` — D-16 cassette pattern
- `~/thinker/research-clones/macOS26-Agent/Agent/AgentViewModel/NativeToolHandlers/Conversation.swift:245-248` — AppleEvent hang on detached threads (D-04, D-15)
- `~/thinker/research-clones/trycua-cua/libs/cua-driver/Sources/CuaDriverServer/ToolRegistry.swift:34-45` — set_value as separate first-class action (D-11 verification)
- `~/browser-harness/pyproject.toml` + `~/browser-harness/daemon.py:6` — confirms cdp-use 1.4.5 dep (D-02 verification)

### Reference MCP server shapes (D-28)
- https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/index.ts — 14 separate tools
- https://github.com/CursorTouch/Windows-MCP/blob/main/src/windows_mcp/tools/input.py — Click/Type/Scroll/Move/Shortcut/Wait pattern
- https://github.com/anthropics/anthropic-quickstarts/blob/main/computer-use-demo/computer_use_demo/tools/computer.py:23-44 — Anthropic's polymorphic computer tool (special case, schema trained-in)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (built in Phase 1)
- **`basicctrl/state/graph.py`** — UIElement schema, Source enum (AX, CDP, AS, OCR, PIXEL — already covers all 5 translators), Capability enum (PRESS, INCREMENT, SHOWMENU, PICK, SET_VALUE, FOCUS), Bbox.centroid (4px-quantised stable identity).
- **`basicctrl/state/causal_dag.py`** — ActionCanonical with `id` field that doubles as ACT-03 idempotency token. `kind: Literal["READ","MUTATE"]` enforces speculation safety. `tier: Optional[Literal["T1"-"T5"]]` and `channel: Optional[Literal["C1"-"C5"]]` already declared (Phase 1 left them Optional; Phase 2 fills them).
- **`basicctrl/profile/classifier.py`** — AppProfile with full capability probe (AX-rich, AX observer works, .sdef present, CDP port reachable, Electron, Tauri/Wails). `translator_priority` derivation already implements rule-based ordering (T2 first when Electron+CDP; T1 for ax_rich; T3 for sdef; T4/T5 always tail). Phase 2 adds the bundled top-12 short-circuit (D-20).
- **`basicctrl/ax/*`** — Full AX safety stack: TokenBucket rate limiter (20/sec/pid), depth-limited walker (3 levels), AXEventBridge (CFRunLoop thread + asyncio Queue), AXObserver bridge with action_id refcon for stale-event filtering. T1 reuses ALL of this.
- **`basicctrl/verifier/*`** — AXObserverManager.expect() is the subscribe-before-fire entry point. Race orchestrator passes the expected subscription future to `asyncio.wait` alongside the channel coroutines.
- **`basicctrl/persist/session_writer.py`** — NDJSON sink for D-16 (idempotency trace).
- **`basicctrl/mcp_server/`** — Existing MCP proxy + `click_with_healing` shape that D-29 extends.

### Established Patterns (follow these in Phase 2)
- **Pydantic v2 with `ConfigDict(frozen=True)`** for all action/state contracts (graph.py, causal_dag.py)
- **anyio task groups** for parallel work (capability_probe.py uses this exact pattern — Phase 2 race orchestrator does the same)
- **structlog with `bind(...)` context** for per-action logging
- **Per-feature sub-package** with `__init__.py` re-exports — follow `ax/`, `state/`, `profile/`, `verifier/` shape for `translators/`, `actions/`
- **Test markers**: `@pytest.mark.integration` for tests requiring real macOS apps (Calculator was Phase 1; Slack/Pages/Chess.app come in Phase 2). `@pytest.mark.manual` for tests requiring human interaction (Slack CDP relaunch is manual).
- **Type-system enforcement over runtime check** — `Literal["READ","MUTATE"]` for speculation; `RacePolicy` enum for D-09 race policy.

### Integration Points
- T1-T5 translators register into a shared registry at `basicctrl/translators/registry.py` (new). Registry is a `dict[str, Translator]` keyed by tier name; AppProfile.translator_priority drives selection.
- C1-C5 channels register into `basicctrl/actions/channel_registry.py` (new). Channels are awaitables that take an ActionCanonical, return a ChannelOutcome.
- Race orchestrator at `basicctrl/actions/race_orchestrator.py` (new) wires translator (target resolution) + channels (delivery) + verifier (decision) + idempotency (atomicity).
- MCP server's `healing_tools.py` (extend) re-routes `click_with_healing` through the race orchestrator instead of the Phase 1 stub.
- Phase 1's `basicctrl/persist/session_writer.py` gains a new event type `idempotency_token` for D-16 trace.

</code_context>

<specifics>
## Specific Ideas

- **Pages test verb syntax (D-26):** `make new paragraph style with properties {name:"BoldTest", font name:"Helvetica", font size:14, bold:true}` — verified stable since iWork '09 via iworkautomation.com + Apple Discussions thread 250493541. Idempotent on repeat (creates a new style each call, ok for test).
- **Chess.app test sequence (D-27):** click square e2 → screenshot dHash → click square e4 → screenshot dHash. Coordinate resolution: uitag SoM grounder receives "white pawn at e2" + screenshot, returns bbox; T5 CGEvent.postToPid fires at bbox center. Verifier: Phase 1's L1 pixel ROI dHash on a 200×200 box around the e2/e4 squares — pawn moves are detectable.
- **Slack CDP relaunch (D-25):** `pkill -9 Slack; sleep 1; open -a "Slack" --args --remote-debugging-port=9222`. After 5s, `curl -s http://localhost:9222/json/version` returns ws URL. CDP target list filters: only pages whose URL contains a workspace subdomain (`*.slack.com`), skip GPU/utility helpers.
- **Slack helper-process gotcha (D-24):** Slack renderer architecture is multi-process per `slack.engineering` blog. Connect CDP to the main workspace renderer, not the GPU process. Filter `Target.getTargets` results by `type="page"` AND `url ~ /\.slack\.com/`.
- **Bear/Things SQLite (P16) policy** — already locked: URL scheme + AS primary, SQLite read-only fallback. Phase 2 enforces this in T3 (AS) implementation; Bear's `bear://x-callback-url/open-note?id=...` is the navigation path. SQLite is not a Phase 2 path at all.
- **Idempotency token format (D-17):** UUID4 + 64-bit monotonic claim_ns + claimed_by_channel: `f"{action.id}@{claim_ns}_{C1..C5}"`. Logged to NDJSON as `{"event": "claim", "action_id": "...", "claim_ns": ..., "channel": "C2"}` (the dict is in-memory authoritative; NDJSON is for replay forensics only).
- **AX validity pre-check (P28 mitigation, ACT-04)** — every translator that resolves a target must call `AXUIElementCopyAttributeValue(role)` immediately before fire to detect `kAXErrorInvalidUIElement`; on failure, falls back to the locator hierarchy in Phase 1's fingerprint module.
- **Race orchestrator first-verified-wins logic** — when verifier fires (Phase 1's `WeightedVote.aggregate` returns confidence ≥ 0.5), orchestrator cancels remaining channels via `cancel_event.set()`. Cancelled channels emit a `race_loser` event with the reason; the winning channel emits `race_winner`. This data feeds the Phase 4 RL training buffer.

</specifics>

<deferred>
## Deferred Ideas

- **MacPaw/Screen2AX synthetic AX tree** — research repo, conflicts with our pyobjc 12.1, not on PyPI. Phase 3 spike if uitag's flat detection list is empirically insufficient for non-AX apps. Otherwise skip.
- **DYLD inject CDP into already-running Electron renderers** — Phase 6 SPI-06 (SIP off, arm64e signing). Phase 2 takes the user-relaunch path (D-24).
- **Swift SkyLight bridge for true `SLEventPostToPid`** — Phase 6 SPI-01. Phase 2 uses public CGEvent.postToPid as C1 implementation; SkyLight is a no-op upgrade later. C1 channel signature stays stable across the swap.
- **Drag stream first-class API** — Phase 2 implements drag_and_drop as single-channel (D-11). A future drag-stream interface (mouse_down → mouse_move steps → mouse_up) for higher-fidelity drag could be added in Phase 4 alongside speculative pre-execution. Note for backlog.
- **Per-app DYLD-equivalent for Tauri/Wails** — Phase 1 classifier detects Tauri/Wails (`tauri_or_wails` flag) but Phase 2 has no T2 path for them. Defer until Phase 6 SPI work.
- **Multi-renderer Slack CDP attach** — Phase 2 tests one workspace renderer. Multi-workspace simultaneous CDP attach is a Phase 4 cassette-replay concern.
- **Linear / Discord / Notion bundleID verification** — first probe on Akeil's machine writes the cache; not a Phase 2 blocker. The bundled top-12 covers verified apps; unverified apps go through capability probe.
- **`transformers 4.x` side-by-side install for mlx-vlm 0.4.4** — if Phase 4's mlx-vlm path needs transformers 4.x and uitag 0.6.0 needs transformers 5.x, install via uv extras with isolated environments. Defer until Phase 4.

### Reviewed Todos (not folded)
None — todo match-phase returned empty.

</deferred>

---

*Phase: 02-translators-racing*
*Context gathered: 2026-04-30 via /research-driven 4-sub-agent fan-out*
