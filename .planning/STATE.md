---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 02-02-PLAN.md
last_updated: "2026-04-30T06:41:24.651Z"
last_activity: 2026-04-30
progress:
  total_phases: 6
  completed_phases: 1
  total_plans: 21
  completed_plans: 11
  percent: 52
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-29)

**Core value:** Autonomous control of any Mac surface, with deterministic self-healing and full transparency — never silently fails, never gives up, never makes the user babysit.
**Current focus:** Phase 02 — Translators + Racing

## Current Position

Phase: 02 (Translators + Racing) — EXECUTING
Plan: 3 of 12
Status: Ready to execute
Last activity: 2026-04-30

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 9
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 9 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 02-translators-racing P01 | 4min | 2 tasks | 23 files |
| Phase 02 P02 | 4min | 3 tasks | 7 files |

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

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 4 research flag: UI-TARS-1.5 + ShowUI-2B MLX availability — verify model card before Phase 4 start; PyTorch+MPS fallback if needed
- Phase 6 research flag: arm64e DYLD signing spike required before commit; AppleSPUHIDDevice IMU may not exist on M-series (SPIKE outcome documented)
- Phase 2 research flag: T4 Vision/Screen2AX integration (MacPaw Screen2AX + uitag SoM are 2025/2026, sparse docs)

## Session Continuity

Last session: 2026-04-30T06:41:15.806Z
Stopped at: Completed 02-02-PLAN.md
Resume file: None
