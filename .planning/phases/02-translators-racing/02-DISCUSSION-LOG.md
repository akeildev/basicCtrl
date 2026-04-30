# Phase 2: Translators + Racing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `02-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-04-30
**Phase:** 02-translators-racing
**Mode:** /research-driven (user said "/research to answer your questions")
**Areas discussed:** Translator depth + CDP reuse, Race policy + idempotency, Top-12 apps + test surface, MCP surface evolution
**Sub-agents:** 4 parallel `general-purpose` agents, all returned HIGH or MEDIUM confidence

---

## Area 1: Translator depth + CDP reuse

### Part A — T2 CDP integration strategy

| Option | Description | Selected |
|--------|-------------|----------|
| (a) `cdp-use` direct dep | Take cdp-use==1.4.5 as a project dependency | ✓ |
| (b) Vendor browser-harness CDP code | Copy browser-harness CDP path into cua_overlay/translators/t2_cdp/ | |
| (c) Runtime-import browser-harness | `import harness` as a sibling package | |

**Decision:** (a) — D-02
**Rationale:** Verified browser-harness uses cdp-use==1.4.5 already (`/Users/akeilsmith/browser-harness/pyproject.toml`); browser-harness is flat-script, not library-shaped (`py-modules = ["run", "helpers", "daemon", "admin"]`); vendoring would copy a personal tool. Electron uses identical CDP wire format (Electron docs).
**Confidence:** HIGH

### Part B — T4 Vision/Screen2AX integration depth

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Full uitag + Screen2AX + ocrmac | Ship all three in Phase 2 | |
| (b) uitag + ocrmac, defer Screen2AX | Active maintained components only | ✓ |
| (c) ocrmac only, defer everything else | Minimal Phase 2 footprint | |
| (d) Build custom YOLO + OCR pipeline | Ignore uitag, roll our own | |

**Decision:** (b) — D-05, D-06
**Rationale:** uitag 0.6.0 (PyPI 2026-04-09) is actively maintained, library-shaped (`run_pipeline` exported), 90.8% ScreenSpot-Pro coverage. Screen2AX is research repo, last commit 2025-07-23, NOT on PyPI, requires pyobjc 10.3.1 (conflicts with our 12.1). ocrmac 1.0.1 already in Phase 1 deps.
**Confidence:** HIGH (uitag), MEDIUM (Screen2AX deferral — could miss synthetic-tree value)
**Risk noted:** uitag requires `transformers>=5.0.0`; CLAUDE.md stack notes Phase 4 may want 4.50+. Pin transformers 5.0+ for Phase 2 (D-08).

---

## Area 2: Race policy + idempotency

### Part A — Action-class race vs single-channel allowlist

| Action class | Options considered | Decision |
|--------------|-------------------|----------|
| click_button / focus / scroll (absolute) / hover | RACE / SINGLE | RACE — D-10 |
| type_into_focused | RACE / SINGLE | SINGLE — D-11 |
| set_value | RACE / SINGLE | SINGLE — D-11 |
| drag_and_drop | RACE / SINGLE / split into mouse_down+up steps | SINGLE (drag as one op) — D-11 |
| key_combo cmd+s/cmd+enter/cmd+w/cmd+z | RACE / SINGLE | SINGLE — D-11 |
| key_combo cmd+c/cmd+v | RACE / SINGLE | RACE — D-12 |
| scroll_by_delta | RACE / SINGLE | SINGLE — D-11 |
| submit/send/delete (locked from P1) | — | SINGLE — D-11 |

**Rationale:** Surveyed Skyvern (`action_types.py:4-31`), Stagehand (`handlers.ts:33-45`), magentic-ui (`_tool_definitions.py`), Anthropic computer-use (`anthropic.py:280-1631`), trycua (`ToolRegistry.swift:34-45`). None race actions — all sequential. Phase 2 racing is novel territory, so first-principles: RACE = idempotent reads/viewport ops. SINGLE = state mutation, focus-altering, stateful sequences.
**Confidence:** HIGH

### Part B — Idempotency token persistence

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Process-local asyncio dict only | Live race only, no replay | |
| (b) SessionWriter NDJSON trace only | Replay possible, no live atomicity | |
| (c) SQLite WAL | Cross-process safe, durable | |
| (d) Memory authoritative + NDJSON trace | Live atomicity + replay | ✓ |

**Decision:** (d) — D-16
**Rationale:** Single-process Python overlay = no IPC concurrency. SQLite WAL is overkill. Stagehand AgentCache pattern matches: per-run JSONL, no token DB (`AgentCache.ts:158`). LangGraph Postgres handles graph-level durability separately.
**Confidence:** HIGH

### Part C — AppleScript stagger window

| Option | Description | Selected |
|--------|-------------|----------|
| 250ms | Tighter — matches AS p50 baseline | |
| 500ms | Default — covers 99th percentile | ✓ |
| 750ms | Conservative — covers AppleEvent inter-app hangs | |
| Per-template tunable | Recipe carries `as_class: fast\|slow` | ✓ (combined with 500ms default) |

**Decision:** 500ms default + per-recipe tunable — D-15
**Rationale:** Pitfall P5 (50-200ms baseline) + macOS26-Agent doc on AppleEvent reply hang (`Conversation.swift:245-248`) + 1 std-dev safety. No surveyed system staggers AS — they don't use AS at all. Per-template lets fast `tell to activate` skip the wait.
**Confidence:** MEDIUM (no empirical data on racing AS — could need adjustment after Phase 2 integration tests)

---

## Area 3: Top-12 apps + test surface

### Part A — Top-12 association map

| Approach | Description | Selected |
|----------|-------------|----------|
| Hard-code static map in `known_apps.py` | Fast cache hit, manual maintenance | ✓ |
| All apps via live capability probe | No hard-coded knowledge | |
| Hybrid: hard-code top-12 + probe everything else | Best of both | ✓ (combined) |

**Decision:** Hybrid — D-20, D-21
**Apps verified locally (HIGH confidence):**
- com.apple.calculator, com.apple.iWork.Pages, com.apple.iWork.Numbers, com.apple.iWork.Keynote, com.apple.mail, com.apple.iCal, com.apple.Notes, com.apple.reminders, com.apple.Safari, com.tinyspeck.slackmacgap, com.todesktop.230313mzl4w4u92 (Cursor), md.obsidian
- All sdef availability confirmed via `ls /Applications/.../Resources/*.sdef`
- All bundleIDs confirmed via `defaults read .../Info.plist CFBundleIdentifier`

**Apps deferred (MEDIUM confidence — first probe on Akeil's machine writes cache):**
- com.hnc.Discord (Discord — not installed locally)
- notion.id (Notion — not installed locally)
- com.linear.LinearMac (Linear — bundleID UNVERIFIED, docs reference `com.linear` preferences domain only)

### Part B — 3 test apps for race winners

| Success criterion | Candidate | Selected | Rationale |
|------|-----------|----------|-----------|
| T2 CDP wins | Slack with manual relaunch | ✓ | DM-to-self channel, `[data-qa="message_container"]` selector, port 9222 |
| T2 CDP wins | VS Code | | Cursor and VS Code both work but Slack is more representative of Akeil's use |
| T3 AS wins | Pages `make new paragraph style {bold:true}` | ✓ | Stable AS verb since iWork '09, idempotent for tests |
| T3 AS wins | Pages toolbar Bold button | | Toolbar buttons not cleanly addressable in Pages sdef (P12-style limit) |
| T4+T5 fires | Apple Chess.app | ✓ | Pre-installed, no .sdef, Metal board, deterministic e2→e4 test |
| T4+T5 fires | Stardew Valley | | Steam dep, $15, login, large download |
| T4+T5 fires | Slay the Spire / Hades / Disco Elysium | | Steam + paid + install cost |
| T4+T5 fires | Minecraft Java | | Launcher login + Java runtime |
| T4+T5 fires | OpenEmu retro emulator | | Requires ROMs (legal/distribution mess for CI) |
| T4+T5 fires | SwiftUI Canvas demo | | Too synthetic, doesn't represent real games |

**Decision:** Slack / Pages / Chess.app — D-25, D-26, D-27
**Confidence:** HIGH (all three verified; Chess.app is pre-installed on every macOS, perfect CI target)

---

## Area 4: MCP surface evolution

| Option | Description | Selected |
|--------|-------------|----------|
| (a) Extend `click_with_healing` + add domain-named siblings | type/scroll/set_value/destructive as separate tools | ✓ |
| (b) Many domain+policy tools | race_click, race_set_value, race_type, single_channel_send (4 per verb) | |
| (c) Single polymorphic `act(ActionCanonical)` | One tool, server picks tier/channel | |

**Decision:** (a) — D-28, D-29
**Rationale:**
- Anthropic guidance: "too many tools or overlapping tools can also distract agents" (https://www.anthropic.com/engineering/writing-tools-for-agents)
- RAG-MCP paper (arxiv:2505.03275): 13.62% accuracy at N=1100, drops markedly at N>100
- Filesystem MCP uses 14 separate tools (modelcontextprotocol/servers/src/filesystem/index.ts)
- Windows-MCP uses Click/Type/Scroll/Move/Shortcut/Wait — exact match for our shape
- Phase 1's `click_with_healing` already commits to (a) — no public-API break
- Reject (b): doubling tools where param does the same job
- Reject (c): polymorphic loses tool-name signal, drops LLM selection accuracy

**Phase 2 tool list:**
1. `click_with_healing` (extended with race_policy, prefer_tier, prefer_channel)
2. `type_with_healing`
3. `scroll_with_healing`
4. `set_value_with_healing`
5. `send_destructive` (single-channel by name, encodes safety)
6. `key_combo_with_healing`

Total ~10 MCP tools after Phase 2 (5 new healing + 1 destructive + 4 inherited from trycua proxy). Well under RAG-MCP ~30 sweet-spot.

**Confidence:** HIGH

---

## Claude's Discretion (areas captured but no user opinion gathered)

- Internal module structure under `cua_overlay/translators/` and `cua_overlay/actions/` (follow Phase 1 pattern)
- Race orchestrator's exact cancellation propagation order (anyio details)
- pytest fixture composition for Slack/Pages/Chess test apps
- Telemetry counter names for race wins
- Logging schema for `near_miss_duplicate` and `cdp_relaunch_offered` events

---

## Deferred Ideas (mentioned during research, captured for future phases)

- MacPaw/Screen2AX — Phase 3 spike if uitag insufficient
- DYLD inject CDP into running Electron — Phase 6 SPI-06
- Swift SkyLight bridge for true SLEventPostToPid — Phase 6 SPI-01
- Drag stream first-class API (mouse_down/move/up) — Phase 4 alongside speculative
- Tauri/Wails T2 path — Phase 6 SPI work
- Multi-renderer Slack CDP attach — Phase 4 cassette replay
- Linear / Discord / Notion bundleID verification — first probe on Akeil's machine
- transformers 4.x + 5.x side-by-side via uv extras — Phase 4 if mlx-vlm needs 4.x

---

*Generated 2026-04-30 from 4 parallel /research sub-agent reports (HIGH confidence on Areas 1, 3, 4; MEDIUM on Area 2 part C).*
