# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-29)

**Core value:** Autonomous control of any Mac surface, with deterministic self-healing and full transparency — never silently fails, never gives up, never makes the user babysit.
**Current focus:** Phase 1 — Foundation + State + Verifier

## Current Position

Phase: 1 of 6 (Foundation + State + Verifier)
Plan: 0 of TBD in current phase
Status: Ready to plan
Last activity: 2026-04-29 — Roadmap created from 79 v1 requirements; 6 phases derived per research SUMMARY.md

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**
- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

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

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 4 research flag: UI-TARS-1.5 + ShowUI-2B MLX availability — verify model card before Phase 4 start; PyTorch+MPS fallback if needed
- Phase 6 research flag: arm64e DYLD signing spike required before commit; AppleSPUHIDDevice IMU may not exist on M-series (SPIKE outcome documented)
- Phase 2 research flag: T4 Vision/Screen2AX integration (MacPaw Screen2AX + uitag SoM are 2025/2026, sparse docs)

## Session Continuity

Last session: 2026-04-29
Stopped at: Roadmap creation complete; 79/79 requirements mapped across 6 phases
Resume file: None
