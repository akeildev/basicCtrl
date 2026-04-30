# Phase 4: Cognition + Learning + Episodic - Context

**Gathered:** 2026-04-30
**Status:** Ready for planning
**Mode:** Auto-generated (workflow.skip_discuss=true) — ROADMAP phase goal is the spec

<domain>
## Phase Boundary

Plan with multiple agents in parallel, predict ahead READ-ONLY, learn from observed user actions via CGEvent tap, and retrieve "last time we did this" from episodic memory before any LLM call.

**In scope (Phase 4):**
- Multi-agent ensemble: Opus + GPT-5 + Apple FM tier-0 (with Apple FM hard-gated to small-enum classification only — P6 + P7)
- UI-TARS-1.5-7B grounder (mlx-vlm 4-bit) with sanity gate (P4 mitigation: reject ±10px screen-center; uitag is primary, UI-TARS is secondary)
- V-Droid prefill-only verifier-LLM (prefix-cached, ~0.7s/step batch)
- World-model predictor (CUWM-style) — predicts post-state before action
- Critic / recovery arbiter — ranks oracle outputs, NEVER self-critiques (P21 mitigation)
- Speculative pre-execution — predicts steps N+1, N+2 in parallel with N's verifier; READ-ONLY type-system enforced (P22)
- 3-model ensemble vote on action selection (Opus + GPT-5 + Apple FM, majority + tiebreaker)
- CGEvent tap (.listenOnly) on background Swift thread (ghost-os pattern)
- Keystroke coalescing via CFRunLoopTimer (0.5s) → 1 typeText per word
- Auto re-enable on tapDisabledByTimeout
- Recording → ObservedAction → Recipe JSON synthesis (params + preconditions + steps + per-step on_failure)
- Episodic memory: FAISS local vector store keyed by (app, task_class, state_fingerprint); surfaces matching recipe BEFORE LLM call
- Phase 3 stub branches B3/B4 now wire into real cognition: B3 → world-model replan, B4 → planner replan via Critic
- AppProfile gains a `cognition_capable` field (capability probe at session start; degrades gracefully if local models unavailable)

**Out of scope:**
- Visualizer / HUD — Phase 5
- Private SPI Swift bridges (SkyLight, AX remote, ES, DTrace, DYLD) — Phase 6
- Durability hardening (LangGraph PostgresSaver) — Phase 6

</domain>

<decisions>
## Implementation Decisions

### Cognition Layer (multi-agent in parallel)
- **D-01:** Module path `cua_overlay/cognition/` mirrors Phase 1-3 per-feature sub-package pattern.
- **D-02:** **Apple FM (`apple-fm-sdk 0.1.1`)** is tier-0 classifier ONLY. Output is Pydantic `Literal["T1","T2","T3","T4","T5"]` or `Literal["retry","escalate","abort"]`. NEVER JSON, NEVER multi-field params (P6). Hard-validate output against allowed enum; on mismatch, fall through to next tier. Text-only API gate (P7) — Apple FM never sees pixels; if visual context needed, OCR + uitag SoM produce a textual scene description first.
- **D-03:** **Planner (Opus 4.x)** via `anthropic` SDK with prompt caching enabled. Bounded plan generation (`max_steps=20` default). Returns Pydantic `PlanCandidate{steps, preconds, success_criteria}`.
- **D-04:** **Grounder (UI-TARS-1.5-7B 4-bit MLX via mlx-vlm 0.4.4)** runs in PARALLEL with planner. Output: bbox candidates. **Sanity gate** rejects any output where `|x - W/2| < 10 AND |y - H/2| < 10` UNLESS pixel-hash of expected element confirms it (P4). Force re-ground via uitag if sanity gate fails.
- **D-05:** **uitag SoM (Apple Vision + YOLO11 MLX, already a Phase 2 dep)** is the **PRIMARY** grounder. UI-TARS is **SECONDARY** with differential grounding (IoU >0.5 required between UI-TARS and uitag bboxes; on disagreement, fall to T4 OCR-grounded action).
- **D-06:** **Verifier-LLM (V-Droid pattern)** prefill-only, prefix-cached. ~0.7s/step batched. Used at L3 only (after L0/L1/L2 ensemble already returned `confidence < 0.30`).
- **D-07:** **World-model predictor (CUWM-style)** — predicts post-state before action fires. Output: `PredictedState{ax_delta, screenshot_phash_delta, expected_notifs}`. Phase 3 B3 branch (world-replan) now consumes this.
- **D-08:** **Critic / recovery arbiter** ranks oracle outputs (planner + grounder + verifier-LLM). NEVER self-critiques — only ranks external oracles. Uses pairwise comparison via small fast model (Apple FM or Haiku 3.5). P21 mitigation.
- **D-09:** **Ensemble vote on action selection** — Opus + GPT-5 + Apple FM. Majority wins; tiebreaker = highest-confidence vote. Apple FM hard-gated to small-enum (D-02). When 2 of 3 agree on tier+target, action proceeds. When all 3 disagree, escalate to user (Critic ranks the 3 candidates; Critic's pick used for telemetry but action escalates).
- **D-10:** **Speculative pre-execution** — Apple FM predicts N+1, N+2 in parallel with N's verifier. Pydantic `ActionCanonical.kind: Literal["READ","MUTATE"]` already enforces speculation safety from Phase 1. Speculator MUST emit only `kind="READ"` for N+1, N+2 candidates. Mutation gate at orchestrator blocks any speculative MUTATE action until N is VERIFIED. Hit rate target: ≥20% (per ROADMAP success criterion). Pattern: Skyvern agent.py:4337.

### Continuous Learning (CGEvent tap recorder)
- **D-11:** **CGEvent tap (.listenOnly)** lives in Swift sidecar at `libs/cua-driver/App/LearningRecorder.swift` (NEW Swift file — but only adding to App/, NOT editing existing CuaDriverServer Swift code per CLAUDE.md hard rule). Pattern from `~/thinker/research-clones/ghost-os/Sources/GhostOS/LearningRecorder.swift:62-88`.
- **D-12:** Background DispatchQueue, never main thread. CFRunLoop source registered on the Swift thread; events stream over JSONL stdio to Python overlay (same IPC pattern as Phase 1-2).
- **D-13:** Auto re-enable on `tapDisabledByTimeout` — Swift side detects, re-creates the tap, emits `tap_re_enabled` event.
- **D-14:** **Keystroke coalescing** via `CFRunLoopTimer(0.5s)` — 1 `typeText` action per word (whitespace-separated boundary) instead of N keystroke events.
- **D-15:** Python side at `cua_overlay/learning/recorder.py` consumes JSONL events; converts to `ObservedAction` Pydantic model.

### Recipe Synthesis
- **D-16:** `cua_overlay/learning/recipe_synth.py` — converts a sequence of `ObservedAction` events into a Recipe JSON. Schema:
  ```
  Recipe {
    name, app_bundle_id, params: dict,
    preconditions: [HoarePre],
    steps: [ActionCanonical with target_locator hierarchy],
    on_failure: [per-step recovery hint]
  }
  ```
  Reference: ghost-os recipe JSON pattern (no direct port; project-specific schema).
- **D-17:** Recipe ingestion: 5 minutes of recording → 1 valid Recipe JSON written to `~/.cua/sessions/<id>/recipes/<recipe_hash>.json`.

### Episodic Memory (FAISS)
- **D-18:** `cua_overlay/state/episodic.py` (extends Phase 1 STATE-04 stub) — `EpisodicMemory` wraps `faiss-cpu==1.13.2` with IndexFlatL2 (Phase 4 scale; IVFPQ when 1M+).
- **D-19:** Keys are `(app_bundle_id, task_class, state_fingerprint)` SHA-256 hashes. Embedding model: a small local sentence-transformer (or Apple FM text embedding) — exact model TBD by planner from current options at execute time. Episodic store also keeps the embedding's `source_text` so re-embedding on model swap is possible.
- **D-20:** **Episodic-first retrieval**: BEFORE the planner makes any LLM call, `episodic.lookup(query_state)` returns top-K matching recipes with similarity > 0.85. Cognition layer presents these to the user/agent as "I've done this before" suggestions.
- **D-21:** Episodic memory is local-only (FAISS file at `~/.cua/episodic.faiss` + metadata sidecar JSON).

### Wiring B3 + B4 (Phase 3 stubs become real)
- **D-22:** Phase 3 B3 stub (`world_replan_stub.py`) is replaced by `cua_overlay/recovery/branches/b3_world_replan.py` — calls `cognition/world_model.py:WorldModelPredictor.predict()` and `cognition/planner.py:Planner.replan()` to produce a new candidate action.
- **D-23:** Phase 3 B4 stub (`planner_reqry_stub.py`) is replaced by `cua_overlay/recovery/branches/b4_planner_replan.py` — calls `cognition/critic.py:Critic.rank_candidates()` to pick best replan from N candidates.
- **D-24:** Both real branches still respect Phase 3 contracts: try_claim BEFORE fire, cancel_event check, RecoveryOrchestrator's max_cycles=2 gate.

### Threats & Mitigations (Phase 4)
- **T-4-01:** UI-TARS coord quantization → screen center (P4). Mitigation: D-04 sanity gate + D-05 uitag-primary + differential grounding.
- **T-4-02:** Apple FM hallucinates params on complex schemas (P6). Mitigation: D-02 hard-validated enum-only output.
- **T-4-03:** Apple FM fed pixels (P7). Mitigation: D-02 text-only API gate; visual context goes through OCR + uitag first.
- **T-4-04:** Intrinsic LLM self-correction is broken (P21). Mitigation: D-08 Critic ranks external oracles only.
- **T-4-05:** Speculative pre-execution mutates state (P22). Mitigation: D-10 type-system gate (`Literal["READ","MUTATE"]` already in Phase 1) + orchestrator mutation gate blocks N+1 MUTATE until N VERIFIED.
- **T-4-06:** CGEvent tap fights asyncio CFRunLoop (Phase 1 hard rule). Mitigation: D-11..D-13 — Swift sidecar on background DispatchQueue, IPC to Python.
- **T-4-07:** mlx-vlm #330 coord-quantization regression. Mitigation: D-04 sanity gate + ShowUI-2B fallback if UI-TARS fails sanity check.
- **T-4-08:** Episodic memory poisoning (bad recipe pollutes future runs). Mitigation: D-19 store embedding source_text + per-recipe `success_count/failure_count`; on >2 failures, recipe is quarantined and surfaces as "low-confidence" only.

### Test Surface (SC #1-#6)
- **D-25:** SC #1 ensemble agreement: synthetic test — 100 routine clicks across 5 apps; assert ≥80% 3-model agreement. Mocked LLM responses for unit speed; integration test uses real Opus + GPT-5 + Apple FM (skip if API keys absent).
- **D-26:** SC #2 speculative N+1 hit rate: replay a recorded trace, count cases where speculator's N+1 prediction matched actual N+1 action; assert ≥20% hit rate.
- **D-27:** SC #3 CGEvent tap recording: integration test launches Swift recorder + Python consumer, simulates 5 keystrokes, asserts 1 `typeText("hello")` event.
- **D-28:** SC #4 Recipe JSON: integration test records 5min of work (or replays recorded fixture), assert recipe has ≥1 step + valid preconditions.
- **D-29:** SC #5 episodic surfaces match BEFORE LLM call: hermetic test seeds 1 recipe, calls cognition with same state fingerprint, assert lookup hits BEFORE any LLM mock invocation.
- **D-30:** SC #6 UI-TARS sanity gate: feed UI-TARS a known-quantization-bug image, assert sanity gate rejects + uitag fallback fires.

### MCP Surface (Phase 4 additions)
- **D-31:** Existing 6 healing tools from Phase 2 + 3 from Phase 3 = 9 unchanged. Phase 4 adds:
  - `record_user_actions(start, stop)` — toggle CGEvent tap recording
  - `synthesize_recipe(session_id, task_label)` — bake recorded session into Recipe JSON
  - `replay_recipe(recipe_id, params)` — execute a saved recipe with bound params
  - `query_episodic(state_fingerprint, top_k=3)` — surface "I've done this before" matches
- **D-32:** Total MCP tool count after Phase 4: ~17 (still under RAG-MCP ~30 sweet spot).

### Claude's Discretion
- Internal module structure under `cua_overlay/cognition/` and `cua_overlay/learning/`
- Exact embedding model for episodic memory (sentence-transformers small vs Apple FM text vs OpenAI ada-002 — pick one at planner time, document in summary)
- Critic's pairwise comparison model (Apple FM vs Haiku 3.5 vs Opus mini)
- Recipe schema field-naming details
- Telemetry counter names

</decisions>

<canonical_refs>
## Canonical References

### Phase 1-3 deliverables (must read — Phase 4 builds atop)
- `cua_overlay/state/causal_dag.py` — ActionCanonical.kind Literal["READ","MUTATE"] (speculation gate)
- `cua_overlay/recovery/orchestrator.py` (Phase 4 wires B3/B4 into this)
- `cua_overlay/recovery/branches/b3_world_replan_stub.py` + `b4_planner_reqry_stub.py` (replaced)
- `cua_overlay/cache/agent_cache.py` (episodic memory consumes from this)

### Stack refs
- `apple-fm-sdk 0.1.1` (PyPI) — text-only, requires macOS 26 + Apple Intelligence ON
- `mlx-vlm 0.4.4` (PyPI) — UI-TARS-1.5-7B 4-bit + ShowUI-2B fallback
- `mlx-community/UI-TARS-1.5-7B-4bit` HF model
- `mlx-community/ShowUI-2B-4bit` HF model (fallback if UI-TARS sanity gate fails)
- `faiss-cpu 1.13.2` — episodic memory
- `anthropic` SDK — Opus planner with prompt caching
- `openai` SDK — GPT-5 ensemble
- `~/thinker/research-clones/ghost-os/Sources/GhostOS/LearningRecorder.swift:62-88` — CGEvent tap pattern reference
- `~/thinker/research-clones/skyvern/skyvern/forge/sdk/agent.py:4337` — speculative read-only pattern reference

### Pitfalls
- P4 (UI-TARS coord quantization)
- P6 (Apple FM 50% param hallucination)
- P7 (Apple FM text-only API)
- P21 (intrinsic LLM self-correction broken)
- P22 (speculation mutating state)

### Project planning
- `.planning/REQUIREMENTS.md` — STATE-04, COG-01..08, LEARN-01..05 (14 reqs)
- `.planning/ROADMAP.md` §"Phase 4"

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets (Phase 1-3)
- `ActionCanonical.kind` Literal["READ","MUTATE"] — speculation safety gate already enforced at type level
- `RaceOrchestrator.race_first_complete` — ensemble parallel pattern (Phase 4 ensemble vote reuses this)
- `RecoveryOrchestrator` — Phase 4 cognition layer feeds branches via this
- `SessionWriter` NDJSON sink — speculative_hit, ensemble_disagree, recipe_synthesized events all stream here
- `KNOWN_APPS` (Phase 2) — gains `cognition_capable` field at probe time

### Established Patterns
- Pydantic v2 frozen models for all event types
- anyio task groups for parallel work with cancel scopes
- Per-feature sub-packages with `__init__.py` re-exports
- structlog `bind(action_id, model, agent)` context for all events
- `@pytest.mark.integration` for tests requiring real APIs/models; `@pytest.mark.manual` for human gestures
- Swift sidecar JSONL stdio IPC pattern (Phase 1 ToolRegistry hook)

</code_context>

<specifics>
## Specific Ideas

- ghost-os LearningRecorder.swift:62-88 is the canonical CGEvent tap pattern — port shape, not direct copy (recipe schema is project-specific)
- UI-TARS-1.5-7B 4-bit MLX bundled model size ~4.5 GB; first run triggers HF download — document in PHASE-4-DEMO.md
- ShowUI-2B fallback model size ~1.2 GB; downloads on first sanity-gate failure
- Episodic similarity threshold 0.85 derived from Stagehand AgentCache hit-rate observations — tune empirically
- 5-minute recipe synthesis target = 5min × 60s × ~3 keystrokes/sec coalesced into ~150 typeText events + ~50 click events

</specifics>

<deferred>
## Deferred Ideas

- Visualizer integration of speculative pre-execution timeline — Phase 5
- LangGraph Postgres durable storage of episodic memory — Phase 6 (FAISS file is enough for Phase 4 single-user)
- Recipe sharing across machines (replication store, conflict resolution) — beyond v1.0
- Multi-modal Apple FM (when Apple ships image input post-26.4) — backlog
- ShowUI-2B → UI-TARS-1.5 swap on `mlx-vlm #330` upstream fix — track + remove the fallback path

</deferred>

---

*Phase: 04-cognition-learning-episodic*
*Context auto-generated 2026-04-30 via workflow.skip_discuss path*
