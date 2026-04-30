# Phase 3: Recovery + Cache Write-Back - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Mode:** Auto-generated (workflow.skip_discuss=true) — ROADMAP phase goal is the spec

<domain>
## Phase Boundary

When verification fails, the system never silently drops. It classifies the failure (6-class enum), fans out 5 recovery branches in parallel, takes the first-verified result, and writes healed selectors back to the cassette — with every heal logged as an event.

**In scope (Phase 3):**
- 6-class failure classifier: PERCEPTUAL / COGNITIVE / ACTUATION / ENVIRONMENTAL / RESOURCE / LOOP
- 5 recovery branches in parallel (B1 rescroll+AX, B2 OCR regrounding+CGEvent, B3 world-model replan stub, B4 planner replan stub, B5 AppleScript fallback)
- First-verified-branch wins; losers cancelled cleanly; failed branches log to RL training buffer
- Bounded recovery: max 2 cycles → escalate to user with actionable message
- Circuit breaker: 3 consecutive same-target failures → trip, switch primary translator for 60s
- Heal-event emission: every heal writes `HealEvent{old_locator, new_locator, reason, trace_id, ts}` to `~/.cua/sessions/<id>/heals.ndjson`
- Heal-rate budget: pauses auto-heal at >5%/session (P20 mitigation — silent regression masking)
- AgentCache port (Stagehand-style): SHA-256 keyed by (bundleID, role_path, instruction)
- Cassette replay: replay until broken step → live re-execute → semantic-diff write-back of healed selectors
- Stable-locator gate: only AXIdentifier/AXLabel/AXTitle write back to canonical cassette; coord/vision-based heals are session-only (P23 mitigation)
- Stream wrapping for transparent caching of streaming results

**Out of scope:**
- Cognition layer (Opus planner, UI-TARS grounder, ensemble vote) — Phase 4. B3/B4 branches are stubs in Phase 3 that emit "cognition not yet ready" events; full implementation in Phase 4.
- Continuous learning (CGEvent tap recorder, Recipe synthesis) — Phase 4
- Visualizer / HUD — Phase 5
- Private SPI Swift bridges — Phase 6

</domain>

<decisions>
## Implementation Decisions

### Failure Classifier
- **D-01:** 6-class typed Pydantic enum `FailureClass` at `cua_overlay/recovery/classifier.py`: `PERCEPTUAL`, `COGNITIVE`, `ACTUATION`, `ENVIRONMENTAL`, `RESOURCE`, `LOOP`. Module-level dispatch table maps each class to its candidate recovery branches (B1-B5).
- **D-02:** Classifier reads HoarePost from RaceOrchestrator (Phase 2 contract) + last verifier signal + last AX/CDP error code. Confidence < 0.50 + specific error patterns route to specific classes (e.g. `kAXErrorCannotComplete` → ACTUATION; `cdp ws closed` → ENVIRONMENTAL; same-target third-failure → LOOP).

### 5 Recovery Branches
- **D-03:** Branches at `cua_overlay/recovery/branches/b{1..5}.py`. Each implements a `RecoveryBranch` Protocol: `async def attempt(failure: FailureCtx) -> Optional[ChannelOutcome]`.
- **D-04:** B1 (rescroll+AX) — scrolls target into view via Phase 1 walker + retries via T1/C2.
- **D-05:** B2 (OCR regrounding+CGEvent) — re-runs T4 uitag/ocrmac to ground target, fires C3 CGEvent.
- **D-06:** B3 (world-model replan) — Phase 3 stub: emits `branch_skipped: cognition_not_ready` event; Phase 4 fills in CUWM-style predictor.
- **D-07:** B4 (planner replan) — Phase 3 stub: same pattern as B3; Phase 4 fills in Opus planner.
- **D-08:** B5 (AppleScript fallback) — re-fires action via T3/C4 with extra 500ms stagger.

### Recovery Orchestrator
- **D-09:** `cua_overlay/recovery/orchestrator.py` — `RecoveryOrchestrator.attempt(failure_ctx)` runs B1..B5 in parallel via `anyio.create_task_group` + `race_first_complete` wrapper from Phase 2 (reuses Phase 2's anyio cancel-scope pattern).
- **D-10:** First-verified-branch wins; losers cancelled. Failed branches log structured event `{branch, reason, latency_ms, error}` to `~/.cua/sessions/<id>/recovery_log.ndjson` for RL training buffer.
- **D-11:** Bounded retries: `max_cycles=2`. After 2nd cycle fails → escalate via user-facing event `{action_id, target_key, last_error, branches_tried, suggested_action}` and abort the action.

### Circuit Breaker
- **D-12:** `cua_overlay/recovery/circuit_breaker.py` — per-(bundle_id, target_key) counter. 3 consecutive failures within 60s window → trip; emits `circuit_breaker_tripped` event; for the next 60s the AppProfile.translator_priority for that bundle is reordered (current primary moved to tail, next-priority promoted).
- **D-13:** Circuit breaker state stored in-memory dict (process-local, asyncio.Lock guarded — same pattern as Phase 2 IdempotencyTokenStore). Phase 6 may upgrade to LangGraph Postgres for crash-resume.

### Heal Events + Rate Budget
- **D-14:** `cua_overlay/recovery/heal_event.py` — Pydantic `HealEvent{old_locator, new_locator, reason, trace_id, ts, locator_tier, source_branch}`. Emitted by branches that produce a healed selector.
- **D-15:** Heals written via Phase 1's SessionWriter to `~/.cua/sessions/<id>/heals.ndjson` (not the action_log — separate stream so analysts can grep heals).
- **D-16:** Heal-rate budget: tracks `heals_per_action / total_actions` per session. When ratio > 0.05 (5%), auto-heal is paused; subsequent failures escalate immediately to user without invoking branches B1-B2 (P20 mitigation against 41% silent-regression abandonment).

### AgentCache + Cassette Write-Back
- **D-17:** `cua_overlay/cache/agent_cache.py` — `AgentCache` port (Stagehand-style, AgentCache.ts:573-624 pattern). Keys are SHA-256 of `(bundle_id, role_path, instruction)`.
- **D-18:** `cua_overlay/cache/cassette.py` — Cassette format = JSON Lines per phase 1 SessionWriter pattern. Each step: `{step_idx, hoare_pre, action_canonical, hoare_post, screenshot_phash, ax_subtree_hash, healed_selectors[]}`.
- **D-19:** `cua_overlay/cache/replay.py` — `CassetteReplayEngine` replays cassette until first non-matching step → falls through to live RaceOrchestrator → on success, calls `WriteBack.heal()`.
- **D-20:** `cua_overlay/cache/writeback.py` — `WriteBack` only updates the cassette when the healed selector is from a STABLE LOCATOR TIER (AXIdentifier, AXLabel, AXTitle, AXRoleDescription). Coord-based or vision-based heals are session-only (live cache only, never write back to canonical cassette per P23). Atomic replace on cassette file (write to `.tmp`, fsync, rename).
- **D-21:** Stream wrapping (CACHE-03) — `cua_overlay/cache/stream_wrap.py` wraps any async generator the agent consumes; transparently caches per-chunk and replays on cassette hit.

### Threats & Mitigations (Phase 3)
- **T-3-01:** Silent heal masking real regressions. Mitigation: D-14..D-16 — every heal logs an event; rate budget pauses auto-heal at >5%.
- **T-3-02:** Cassette write-back loop / non-deterministic re-record. Mitigation: D-20 stable-tier gate + atomic replace.
- **T-3-03:** 5-branch recovery cost explosion (Opus pricing × 5 in Phase 4). Mitigation: D-11 bounded cycles + D-12 circuit breaker.
- **T-3-04:** Race condition between branches and main verifier. Mitigation: D-09 reuses Phase 2's race_first_complete; cancel_event propagated.
- **T-3-05:** Recovery-induced double-action (B1 retries while B5 already fires AS). Mitigation: each branch reuses Phase 2's IdempotencyTokenStore.try_claim before any channel.fire.
- **T-3-06:** Cassette schema drift across versions. Mitigation: cassette files include `schema_version` field; replay validates and warns on mismatch.

### Test Surface
- **D-22:** Test apps reuse Phase 2's: Calculator (com.apple.calculator) for stress, Slack/Pages/Chess for SC integration. New: simulate stale selector by injecting an `old_locator` that doesn't resolve, expect heal cycle to update cassette.
- **D-23:** Unit tests cover: each FailureClass routes to correct branches; each branch resolves expected outcomes on mock; circuit breaker trip/reset; rate budget pause/resume; stable-tier gate accept/reject; atomic cassette replace.
- **D-24:** Integration test for SC #1: Inject stale selector, run cassette replay, observe live re-execute via fanout, confirm cassette atomically updated with healed AXIdentifier.

### MCP Surface (Phase 3 additions)
- **D-25:** Existing 6 healing tools from Phase 2 remain unchanged (extension only). Phase 3 adds:
  - `replay_cassette(session_id, cassette_id)` — replay a recorded cassette; emits per-step events
  - `cancel_recovery(action_id)` — abort an in-flight recovery cycle (user override)
  - `clear_circuit_breaker(bundle_id)` — manually reset a tripped breaker
- **D-26:** Total MCP tool count after Phase 3: ~13 (still under RAG-MCP ~30 sweet spot).

### Claude's Discretion
- Internal module structure under `cua_overlay/recovery/` and `cua_overlay/cache/` — follow Phase 1/2 per-feature sub-package pattern
- Exact `RecoveryBranch` Protocol field names (Pydantic model)
- Telemetry counter names for branch wins per (failure_class, branch)
- Logging schema for `circuit_breaker_tripped`, `heal_rate_paused`, `recovery_escalated` events
- Cassette replay step-matching tolerance (pHash threshold, AX subtree hash truncation depth)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 2 deliverables (must read — Phase 3 builds atop)
- `cua_overlay/actions/race_orchestrator.py` (race_first_complete pattern Phase 3 reuses)
- `cua_overlay/actions/idempotency.py` (try_claim — branches must use it)
- `cua_overlay/actions/race_policy.py` (resolve_race_policy — branches honor it)
- `cua_overlay/actions/duplicate_receipt.py` (2s ring buffer)
- `cua_overlay/translators/*.py` (T1-T5 — branches dispatch through these)
- `cua_overlay/actions/channels/*.py` (C1-C5)
- `cua_overlay/profile/classifier.py` (AppProfile.translator_priority — circuit breaker reorders this)
- `cua_overlay/persist/session_writer.py` (NDJSON sink — heal events go here)

### Architecture refs
- `~/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md` — recovery layer L6+L7
- `.planning/research/ARCHITECTURE.md` §"recovery/" §"cache/" §"Backward path — failure → recovery"
- `.planning/research/PITFALLS.md` — P20, P23, P26, P27 (Phase 3 BLOCKERs)

### External patterns
- `~/thinker/research-clones/stagehand/packages/core/lib/v3/cache/AgentCache.ts:158-187` — cache write-back pattern
- `~/thinker/research-clones/skyvern/skyvern/forge/sdk/` — failure taxonomy reference

### Project planning
- `.planning/REQUIREMENTS.md` — HEAL-01..05, CACHE-01..03 (Phase 3 reqs)
- `.planning/ROADMAP.md` §"Phase 3" — goal + success criteria
- `.planning/RALPH-HANDOFF.md` — autonomous run state

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (Phase 1+2)
- `RaceOrchestrator.race_first_complete` (Phase 2) → reused as `BranchOrchestrator.first_verified` in Phase 3
- `IdempotencyTokenStore.try_claim` (Phase 2) → branches use it to prevent recovery-induced double-fires
- `WeightedVote / Aggregator` (Phase 1) → branches feed L0+L1+L2 verifier the same way main path does
- `SessionWriter` (Phase 1) → heal events, recovery_log, circuit_breaker events all stream here as NDJSON
- `AppProfile + KNOWN_APPS` (Phase 2) → circuit breaker reorders priority list per-bundle for 60s

### Established Patterns
- Pydantic v2 frozen models for all event types
- anyio task groups for parallel work with cancel scopes
- Per-feature sub-packages with `__init__.py` re-exports
- structlog `bind(action_id, branch, target_key)` context for all events
- `@pytest.mark.integration` for tests requiring real apps; `@pytest.mark.manual` for human gestures

### Integration Points
- RaceOrchestrator emits failure events when verifier confidence < 0.50; RecoveryOrchestrator subscribes and triggers
- AppProfile classifier's `translator_priority` field is mutable (per-session) for circuit breaker reordering
- Cassette files written under `~/.cua/sessions/<id>/cassettes/<bundle_id>/<task_class>/<sha256>.jsonl`
- Heal-event NDJSON file written under `~/.cua/sessions/<id>/heals.ndjson`

</code_context>

<specifics>
## Specific Ideas

- AgentCache.ts:573-624 (Stagehand) is the canonical pattern for cache self-heal write-back — use as reference, not direct port
- Atomic file replace pattern: write to `<file>.tmp`, fsync, then `os.rename()` — POSIX atomic on same filesystem
- pHash threshold for cassette replay step-matching: 8 (out of 64 bits) — empirically derived; tune if Tahoe screenshot regression bumps noise
- Recovery escalation message format: `"Action {action_id} failed after 2 recovery cycles on target {target_key}. Last error: {err}. Tried branches: {b1, b2, ...}. Suggested: {next_step}"` — the `next_step` field uses heuristics (e.g. "open System Settings → Privacy → Accessibility" if `kAXErrorAPIDisabled`)

</specifics>

<deferred>
## Deferred Ideas

- Full cognition (Opus planner, ensemble vote, world model) — Phase 4
- Visualizer integration of heal events (HUD shows heal events in real time) — Phase 5
- LangGraph Postgres durable storage of circuit breaker state — Phase 6
- Cassette schema migration tool (when schema_version bumps) — backlog
- RL training buffer consumer (offline policy learning from failed branches) — backlog beyond Milestone v1.0

</deferred>

---

*Phase: 03-recovery-cache-write-back*
*Context auto-generated 2026-04-30 via workflow.skip_discuss path*
