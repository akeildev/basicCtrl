# basicCtrl — Research Summary

**Project:** basicCtrl
**Domain:** Self-healing autonomous Mac CU framework (Python overlay above trycua/cua Swift driver)
**Researched:** 2026-04-29
**Confidence:** HIGH
**Granularity:** standard (5–8 phases)

---

## Executive Summary

```
Build a Python overlay on a forked trycua Swift driver.
Race 5 protocol translators per action.
Verify with push events first, LLM last.
5-branch parallel recovery when verify fails.
6 phases. Visualizer + private SPIs late. Cognition last.
```

**What this is.** A maximalist Mac CU framework. Self-heals on translator drift. Never silently fails.

**How experts build it.** Bottom-up: foundation → verifier → driver → recovery → learning → cognition. Push events (AXObserver) are the secret weapon — sub-1ms verification via Mach port. Deterministic ensemble before any LLM call.

**Key risks.** Racing translators can double-click destructive actions (Pitfall 1). AX polling >30/sec freezes target apps (Pitfall 2). Push verifier silently dies on web content (Pitfall 14). All three need design-time mitigations baked into Phase 1–2, not bolted on.

---

## Key Findings

### Recommended Stack — top picks

```
Python 3.12 + uv          ← overlay primary
Swift 6 (~300 LOC)        ← visualizer + CGEvent tap + SPI bridges
PyObjC 12.1               ← all macOS framework access
mlx-vlm 0.4.4             ← UI-TARS-1.5-7B + ShowUI-2B grounders
faiss-cpu 1.13.2          ← episodic memory (embedded, no server)
LangGraph PostgresSaver   ← durable execution (local Postgres)
structlog 25.5.0          ← async-safe NDJSON action log
ocrmac + ImageHash        ← Vision OCR + dHash for cheap diff
py-applescript 1.0.3      ← in-process NSAppleScript (no subprocess)
apple-fm-sdk 0.1.1        ← tier-0 binary classifier ONLY
```

**Total Python deps: ~18.** Total Swift: ~300 LOC.

### Stack — dropped options

| Dropped | Why |
|---|---|
| pyatomac / atomac | Abandoned 2013/2018 |
| atomacos as dep | Stale 2021; **fork helpers, don't depend** |
| subprocess osascript | 50-200ms fork+exec per call |
| PyObjC CGEvent tap | CFRunLoop fights asyncio — Swift sidecar instead |
| vcrpy / pytest-recording | HTTP-only — useless for AX/CDP cassettes |
| ChromaDB | Server-mode even when "embedded" |
| loguru | Buggy contextvar across asyncio task groups |
| Inngest / Restate / Temporal | Server runtime; wrong fit for desktop |
| GGUF UI-TARS | ByteDance pulled — vision encoder won't serialize |

### Feature Taxonomy

```
TABLE STAKES   = 25 features  → 5 translators + push verifier + race + recover + persist + MCP
DIFFERENTIATORS = 47 features  → transparency + learning + private SPI + ensemble cognition
ANTI-FEATURES   = 20 patterns  → production safety, sandboxing, cross-platform, intrinsic LLM correction
```

**All 79 Active reqs from PROJECT.md covered.** Every Out-of-Scope item maps to a documented anti-feature.

**Complexity:** 23 LOW, 36 MEDIUM, 13 HIGH, 3 SPIKE.

### Architecture Overview

```
┌──────────────────────────────────────────────┐
│  MCP server (preserves trycua surface)       │
└────────────────┬─────────────────────────────┘
                 │
┌────────────────▼─────────────────────────────┐
│  overlay/ (Python — the State Bridge)        │
│                                              │
│  cognition  →  state/graph (CORE)            │
│       │                                      │
│       ├─→ profile  ─→ translators (T1-T5)   │
│       ├─→ verifier (L0 push → L1 → L2 → L3) │
│       ├─→ actions/race_orchestrator         │
│       ├─→ recovery (5 branches)             │
│       ├─→ cache/writeback                   │
│       ├─→ learning (CGEvent tap)            │
│       └─→ persist (LangGraph PG)            │
│                                              │
│  ipc/swift_bridge ←→ JSONL stdio            │
└────────────────┬─────────────────────────────┘
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
   cua-driver  visualizer  spi-bridge
   (untouched) (Swift,300) (Swift glue)
```

**IPC seam.** JSONL line-delimited over stdio. Two channels: driver + visualizer.

**One rule.** Components never reach across boundaries. `cognition/` asks `actions/` for an outcome — never calls translators directly.

### Top 10 Pitfalls to Design Around Early

| # | Pitfall | Severity | Phase Owns It |
|---|---|---|---|
| 1 | Action interference (double-clicks on race) | BLOCKER | Driver — atomic idempotency token + per-action-class race policy |
| 2 | AX rate-limit (cmux #2985) | BLOCKER | Verifier — 20 calls/sec/pid token bucket, push-first |
| 3 | Full recursive AX = 15-20s on Safari | BLOCKER | Verifier — depth-limited 3 levels; CDP DOM observer for web |
| 14 | AX notifications fail on web/Electron | BLOCKER | Verifier — bundle-routed L0 source |
| 4 | UI-TARS coord quantization → screen-center | BLOCKER | Cognition — uitag primary, sanity gate |
| 8 | Electron `--remote-debugging-port` launch-only | BLOCKER | Foundation — never silent relaunch |
| 21 | Intrinsic LLM self-correction = 16-27% accuracy | BLOCKER | Recovery — Critic ranks oracles, never self-critiques |
| 22 | Speculation mutating state | BLOCKER | Cognition — speculation is READ-ONLY |
| 9, 10 | Visualizer leaks into verifier capture | BLOCKER | Visualizer — `SCContentFilter(excludingWindows:)` |
| 20 | Self-healing masks regressions (41% abandonment) | MAJOR | Recovery + Cache — heal events + rate budget |

**Severity totals:** 11 BLOCKER, 16 MAJOR, 2 MINOR.

---

## Implications for Roadmap

### Recommended Phase Count: **6 phases**

Researchers diverged: architecture said 5, features said 8, pitfalls mapped to 12 sprints. Standard granularity wants 5–8. **Pick 6.** Splits "transparency" cleanly from "SPIs+durability" without bloating to 8.

### Phase Structure

```
Phase 1: Foundation + State + Verifier  (~12 days)
Phase 2: Translators + Racing            (~12 days)
Phase 3: Recovery + Cache write-back     (~10 days)
Phase 4: Learning + Episodic + Cognition (~12 days)
Phase 5: Visualizer + Transparency       (~8 days)
Phase 6: Private SPIs + Durability       (~7 days)
```

### Phase 1 — Foundation + State + Verifier

**Rationale:** Push subscriptions must exist before actions fire. State graph is the substrate everything writes to.
**Delivers:** Click in any app → AXValueChanged fires → recorded as verified in <50ms.
**Addresses:** CORE-01..03, STATE-01..03, VERIFY-01..07, PERSIST-01..03, MCP-01..02
**Avoids:** Pitfalls 2, 3, 14, 24

### Phase 2 — Translators + Racing

**Rationale:** Verifier from Phase 1 → racing has a winner-decider. All translators write same UIElement shape.
**Delivers:** Slack click via T2 CDP wins. No double-clicks across 100 fires.
**Addresses:** TRANS-01..05, ACT-01..04
**Avoids:** Pitfalls 1, 5, 8, 16

### Phase 3 — Recovery + Cache write-back

**Rationale:** Racing without recovery is fragile. Cache write-back needs healed selectors from recovery branches.
**Delivers:** Stale selector → cassette replay → broken-step → live re-execute → write-back.
**Addresses:** HEAL-01..05, CACHE-01..03
**Avoids:** Pitfalls 13, 20, 23, 26

### Phase 4 — Learning + Episodic + Cognition

**Rationale:** Cognition + learning both produce/consume episodic memory. Together they unlock parallel multi-agent.
**Delivers:** 5min recording → Recipe JSON. Episodic retrieval before LLM call. 3-model ensemble vote.
**Addresses:** LEARN-01..05, STATE-04, COG-01..08
**Avoids:** Pitfalls 4, 6, 21, 22

### Phase 5 — Visualizer + Transparency

**Rationale:** Only worth visualizing once we have real data. PROJECT.md says "Visualizer in v2."
**Delivers:** Ghost cursor + HUD + 60fps replay + 3D timeline + counterfactual replay.
**Addresses:** VIS-01..06, OBS-01..06
**Avoids:** Pitfalls 9, 10, 11

### Phase 6 — Private SPIs + Durability hardening

**Rationale:** SPIs unlock channels translators route to — every SPI needs public-API fallback.
**Delivers:** Slack background automation. DYLD into Electron renderers. Kill -9 → resume.
**Addresses:** SPI-01..08 + PERSIST hardening
**Avoids:** Pitfalls 17, 18, 19

### Phase Ordering Rationale

```
Foundation FIRST          → state graph + verifier are everything's substrate
Verifier BEFORE driver   → push subs MUST exist before actions fire
Racing AFTER verify      → racing without verifier = coin flip
Recovery AFTER racing    → branches use translators + channels
Learning + Cognition    → produce/consume episodic memory together
Transparency LATE       → no point visualizing nothing
SPIs LAST               → every SPI needs public fallback
```

### Research Flags

| Phase | Research Needed | Why |
|---|---|---|
| **Phase 2** | T4 Vision/Screen2AX integration | MacPaw Screen2AX + uitag SoM are 2025/2026, sparse docs |
| **Phase 4** | UI-TARS-1.5 + ShowUI-2B fallback | mlx-vlm #330 mitigation pattern needs validation |
| **Phase 4** | Recipe JSON schema | Borrow from ghost-os, project-specific |
| **Phase 6** | DYLD injection on arm64e | PAC + signing fragile, needs spike |
| **Phase 6** | AppleSPUHIDDevice IMU | SPIKE — undocumented, may not exist on M-series |

### Standard Patterns (skip research)

| Phase | Source |
|---|---|
| **Phase 1** Foundation | Established trycua + browser-harness patterns |
| **Phase 3** Cache write-back | Stagehand `AgentCache.ts:573-624` is reference |
| **Phase 5** Visualizer | NSPanel + SwiftUI well-documented |

---

## Confidence Assessment

| Area | Confidence | Notes |
|---|---|---|
| Stack | **HIGH** | All versions live-verified on PyPI 2026-04-29; ShowUI MLX availability is MEDIUM |
| Features | **HIGH** | Locked architecture + verified competitive landscape |
| Architecture | **HIGH** | 9-layer locked arch in vault; 4 reference clones |
| Pitfalls | **HIGH** | Every pitfall has production-code citation, issue, or paper |

**Overall: HIGH.**

### Gaps to Address During Planning

| Gap | Plan |
|---|---|
| ShowUI-2B MLX availability | Verify model card before Phase 4; PyTorch+MPS fallback |
| `traceops` library existence | May be pattern not package — write custom JSONL cassette |
| Apple FM image input | Text-only as of 26.4 — capability probe gate |
| macOS 27 SPI breakage | Capability probe at session start; log degradation |
| arm64e DYLD signing | Spike in Phase 6 before commit |

---

## Sources

### Primary (HIGH)
- `/Users/akeilsmith/dev/basicCtrl/.planning/PROJECT.md`
- `~/thinker/vault/research/basicCtrl-self-healing-framework-2026-04-29.md` — THE locked architecture
- `~/thinker/vault/research/computer-use-alternatives-2026-04-29.md`
- `~/thinker/research-clones/trycua-cua/`, `browser-harness/`, `ghost-os/`, `skyvern/`, `stagehand/`

### PyPI verified live (2026-04-29)
- pyobjc 12.1, mlx-vlm 0.4.4, faiss-cpu 1.13.2, structlog 25.5.0
- langgraph-checkpoint-postgres 3.0.5, ocrmac 1.0.1, apple-fm-sdk 0.1.1
- ImageHash 4.3.2, py-applescript 1.0.3

### Research papers (post-Oct 2024)
- Decomposing Self-Correction (2601.00828) — intrinsic broken
- Dark Side of Self-Correction (2412.14959) — wavering
- AX-tree Self-Healing (2603.20358) — 10-tier locator
- Speculative Actions (2510.04371) — read-only only
- Screen2AX (2507.16704) — 77% F1
- V-Droid (2503.15937) — 0.7s/step
- CUWM (2602.17365) — world model
- Reliability of CUAs (2604.17849) — non-determinism

### Production issues
- trycua/cua #870 — Tahoe SCScreenshotManager
- cmux #2985 — AX rate-limit
- mlx-vlm #330 — UI-TARS quantization
- Cowork #49498 — session loss

### Detail docs (this folder)
- /Users/akeilsmith/dev/basicCtrl/.planning/research/STACK.md
- /Users/akeilsmith/dev/basicCtrl/.planning/research/FEATURES.md
- /Users/akeilsmith/dev/basicCtrl/.planning/research/ARCHITECTURE.md
- /Users/akeilsmith/dev/basicCtrl/.planning/research/PITFALLS.md
