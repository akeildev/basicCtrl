---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: "Completed 06-09: Durability hardening — LangGraph PostgresSaver test suite"
last_updated: "2026-05-01T22:17:51.628Z"
last_activity: 2026-05-01
progress:
  total_phases: 6
  completed_phases: 5
  total_plans: 61
  completed_plans: 58
  percent: 95
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-29)

**Core value:** Autonomous control of any Mac surface, with deterministic self-healing and full transparency — never silently fails, never gives up, never makes the user babysit.
**Current focus:** Phase 6 — private-spis-durability-hardening

## Current Position

Phase: 6 (private-spis-durability-hardening) — EXECUTING
Plan: 9 of 12
Status: Ready to execute
Last activity: 2026-05-01

Progress: [███████░░░] 49/49 plans completed (100%)

## Performance Metrics

**Velocity:**

- Total plans completed: 49
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 9 | - | - |
| 2 | 12 | - | - |
| 3 | 9 | - | - |
| 4 | 9 | - | - |
| 5 | 10 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 02-translators-racing P01 | 4min | 2 tasks | 23 files |
| Phase 02 P02 | 4min | 3 tasks | 7 files |
| Phase 02 P03 | 4min | 2 tasks | 3 files |
| Phase 02 P04 | 4min | 2 tasks | 8 files |
| Phase 02 P05 | 16m | 2 tasks | 7 files |
| Phase 02 P06 | 6min | 2 tasks | 6 files |
| Phase 02 P07 | 4min | 2 tasks | 6 files |
| Phase 02 P08 | 3min | 1 tasks | 3 files |
| Phase 02 P02-09 | 5min | 2 tasks | 5 files |
| Phase 02-translators-racing P10 | 4min 33s | 2 tasks | 3 files |
| Phase 02 P11 | 6m 06s | 2 tasks | 3 files |
| Phase 02-translators-racing P12 | 25min | 6 tasks | 6 files |
| Phase 04 P01 | 5m 42s | 3 tasks | 11 files |
| Phase 04 P04-03 | 3m 30s | 2 tasks | 5 files |
| Phase 04 P04 | 18m | 3 tasks | 6 files |
| Phase 04 P05 | 8s | 2 tasks | 6 files |
| Phase 04 P06 | 22 min | 2 tasks | 4 files |
| Phase 04 P07 | 18m | 2 tasks | 6 files |
| Phase 04 P08 | 25m | 2 tasks | 6 files |
| Phase 05-visualizer-full-transparency P02 | 2 | 3 tasks | 3 files |
| Phase 05 P03 | 2 | 2 tasks | 3 files |
| Phase 05 P04 | 8 | 2 tasks | 3 files |
| Phase 05 P06 | 5 | 2 tasks | 3 files |
| Phase 05-visualizer-full-transparency P07 | 8 | 2 tasks | 2 files |
| Phase 06 P01 | 15 | 3 tasks | 6 files |
| Phase 06 P02 | 20 | 3 tasks | 4 files |
| Phase 06 P03 | 8 | 2 tasks | 2 files |
| Phase 06 P05 | 5 | 2 tasks | 2 files |
| Phase 06-private-spis-durability-hardening P06 | 8 | 2 tasks | 5 files |
| Phase 06-private-spis-durability-hardening P09 | 8min | 1 tasks | 1 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Phase 1: Push-event subscription (AXObserver) is primary verifier — sub-1ms via Mach port, deterministic, must be subscribed BEFORE action fires
- Phase 1: Deterministic ensemble (L0 push → L1 cheap → L2 medium → L3 LLM) — never start at L3; intrinsic LLM self-correction is 16-27% accurate (papers 2601.00828, 2412.14959)
- Phase 2: Race translators in parallel with atomic idempotency tokens; destructive actions (submit/send/delete) use single-channel delivery only
- Phase 4: Apple FM is tier-0 binary classifier ONLY; never JSON, never multi-field params (50% hallucination on complex schemas; text-only public API)
- Phase 5: Visualizer in Phase 5 not Phase 1 — failure logs come first; need real recordings before knowing what's worth visualizing
- Phase 6: Every private SPI needs public-API fallback in registry; capability probe at session start; macOS-version risk = degrade gracefully
- [Phase 02-translators-racing]: Wave-0 stubs use pytest.importorskip at module load — files collect/skip cleanly until target module ships, then pass automatically (Nyquist gate)
- [Phase 02-translators-racing]: Skip-if-missing fixture pattern adopted for slack_cdp_ws/pages_running/chess_launcher — probe + pytest.skip(actionable msg) over hard fail
- [Phase 02]: Single global asyncio.Lock for IdempotencyTokenStore (D-16) — per-target locks rejected; first-claimer-wins is correct by design (Pitfall F)
- [Phase 02]: RacePolicy unknown action_types default to SINGLE_CHANNEL — conservative; explicit RACE caller request still downgrades when intrinsic = SINGLE_CHANNEL (T-2-09)
- [Phase 02]: NDJSON idempotency_claim event written INSIDE the asyncio.Lock — guarantees deterministic ordering for Phase 4 cassette replay (D-16 trace contract)
- [Phase 02]: D-20: classify() consults KNOWN_APPS short-circuit BEFORE live probes; 17-entry bundled map (12 D-21 + 5 D-22) covers Akeil's daily app surface; Slack/Cursor/Obsidian flagged cdp_after_relaunch=True for Plan 02-11 MCP relaunch prompt; min_known_version drift detection emits warning + falls through to live probe
- [Phase 02]: Plan 02-04: Translator + Channel Protocol contracts shipped as interface-first Wave 1; D-14 default tier→channel binding (T1→C2, T2→C5, T3→C4, T4→C1, T5→C3) codified as TIER_TO_CHANNEL_DEFAULT module constant; CHANNEL_TO_TIER_DEFAULT auto-inverted; ChannelRegistry.tier_for_channel reverse lookup unblocks Plan 02-10 race orchestrator's tier-from-winner inference
- [Phase 02]: Plan 02-04: TranslatorTarget mutable (extras dict written by translator pre-fire); ChannelOutcome frozen (T-2-06/T-2-08 race-cancel correctness — channels return new instances rather than mutating; race orchestrator can safely cache outcome references across cancel scopes)
- [Phase 02]: T1 ships its own walker (_walk_with_refs) preserving raw AXUIElementRef opaque handles; Phase 1's walk_subtree returns only UIElements
- [Phase 02]: Two-bucket TokenBucket pattern in T1: 200/sec resolution bucket + 20/sec action-time validate bucket
- [Phase 02]: T1 _MAX_DEPTH=6 with load-bearing _MAX_NODES_T1=200 cap; CLAUDE.md max-3 rule applies to walk_subtree, not translator-layer walkers (per Phase 1 demo precedent)
- [Phase 02]: Module-scoped calculator_session_pid fixture for tests that need warm Calculator across multiple sequential test functions
- [Phase 02]: T2 ws_url stashed in TranslatorTarget.extras for C5 cross-fire re-attach (Phase 2 trades 10ms socket re-open for clean per-fire CDPClient lifecycle)
- [Phase 02]: T2/C5 validate() does cheap struct check (no live DOM round-trip) — channel fails fast on stale session at dispatch time
- [Phase 02]: D-03 hard rule grep-enforced: zero occurrences of literal 'browser_harness' substring in t2_cdp.py source
- [Phase 02]: T3+C4 ship as third D-14 default tier-channel pair: dedicated cua-as ThreadPool (T-2-03), module-level compiled-script cache (Pitfall E), C4 reuses T3 pool (does not spin own)
- [Phase 02]: Plan 02-08: T4 Vision uses lazy uitag/ocrmac imports inside asyncio.to_thread closures (Pitfall C isolation + test-friendly patch.dict); D-06 grep-enforced to 0 occurrences of Screen2AX/MacPaw literals; image_width/image_height logged at INFO on every resolve for A1 Retina ratio surfacing in Plan 02-12 Chess integration
- [Phase 02]: Plan 02-09: T5 Pixel + C1 + C3 ship together; T5 delegates coordinate resolution to T4 (D-07); C1 = background no-cursor-warp tier (Phase 6 SkyLight upgrade), C3 = foreground with cursor (stays public CGEventPostToPid). Both wrap CGEventPostToPid only (T-2-05 grep-enforced). C3 imports _post_left_click from c1_skylight (DRY).
- [Phase 02-translators-racing]: race_first_complete uses tg.cancel_scope.cancel() (anyio FIRST_COMPLETED workaround per D-13)
- [Phase 02-translators-racing]: Server-side T-2-09 enforcement: resolve_race_policy gates BEFORE channel construction; D-11 destructive verbs forced to SINGLE_CHANNEL even when caller passes RACE
- [Phase 02-translators-racing]: ActionCanonical.tier and .channel filled from winner's ChannelOutcome via model_copy after race resolves (D-14 inverse map for tier_for_channel)
- [Phase 02]: Latency tracked at MCP boundary via time.monotonic — Phase 1 HoarePost has no elapsed_ms field
- [Phase 02]: main.py builds RaceOrchestrator at startup with explicit T1-T5 + C1-C5 register calls (translators/channels do NOT self-register on import)
- [Phase 02]: send_destructive encodes safety in tool name (no race_policy parameter) — T-2-09 layer 1 of three-layer defense
- [Phase 02-translators-racing]: Phase 2 ship gate complete: 5 SC integration tests written, PHASE-2-DEMO.md operator runbook in PHASE-1-DEMO.md format; case-sensitive bundle_ids per D-21; SC #2 uses action_type='click' (D-10 RACE) per WARN-4 for AS stagger observability; SC #4 stress on Calculator + WARN-6 C1/C3 dedup; ready for gsd-verifier
- [Phase 06]: IOKit IMU enumeration via ioreg(1); graceful skip on Intel
- [Phase ?]: All Tier-B/C SPIs gracefully skip on default Mac (SIP fully on); is_sip_partial_off() helper centralized in probe.py
- [Phase 06-private-spis-durability-hardening]: Consolidated durability tests into single tests/test_durability.py module for clarity (not split across integration/)

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 4 research flag: UI-TARS-1.5 + ShowUI-2B MLX availability — verify model card before Phase 4 start; PyTorch+MPS fallback if needed
- Phase 6 research flag: arm64e DYLD signing spike required before commit; AppleSPUHIDDevice IMU may not exist on M-series (SPIKE outcome documented)
- Phase 2 research flag: T4 Vision/Screen2AX integration (MacPaw Screen2AX + uitag SoM are 2025/2026, sparse docs)

## Session Continuity

Last session: 2026-05-01T22:17:51.625Z
Stopped at: Completed 06-09: Durability hardening — LangGraph PostgresSaver test suite
Resume file: None

**Phase 5 Summary:**

- All 12 ROADMAP requirements tested (VIS-01..OBS-06)
- All 4 pitfall mitigations verified (P9/P10/P11/P12)
- 33 tests passing (12 requirement + 17 session diff + 4 validation)
- Phase 5 gate: **PASSED** ✅
- Ready for Phase 6 planning
