---
phase: 02-translators-racing
plan: 11
subsystem: mcp_server
tags: [mcp-tools, healing-tools, race-orchestrator, t-2-09, t-2-10, fastmcp, pydantic-literal]

requires:
  - phase: 01-foundation
    provides: register_healing_tools (Phase 1 click_with_healing), ProxyDeps, FastMCP proxy_server, SessionWriter
  - phase: 02-translators-racing
    provides: RaceOrchestrator (02-10), RacePolicy enum + resolve_race_policy (02-02), TranslatorRegistry (02-01), ChannelRegistry (02-04), IdempotencyTokenStore + DuplicateReceipt (02-02), T1-T5 translators (02-05..02-09), C1-C5 channels (02-04..02-09)
provides:
  - "register_healing_tools(proxy, upstream, deps, race_orch) — 4-arg signature; registers 6 D-29 tools"
  - "click_with_healing — Phase 1 backward-compat 5-arg signature + 3 new appended args (race_policy, prefer_tier, prefer_channel)"
  - "type_with_healing(text, bundle_id, pid, target_label, race_policy) — D-11 single-channel default"
  - "scroll_with_healing(direction, amount, bundle_id, pid, action_kind, race_policy) — D-10/D-11 routes absolute→race, delta→single"
  - "set_value_with_healing(target_label, value, bundle_id, pid, race_policy) — D-11 single-channel"
  - "send_destructive(target_label, bundle_id, pid, confirmation_phrase) — NO race_policy param (D-29 safety-by-name); always passes RacePolicy.SINGLE_CHANNEL"
  - "key_combo_with_healing(combo, bundle_id, pid, race_policy) — SAFE_RACE_COMBOS allowlist (cmd+c, cmd+v) → action_type='key_combo'; else 'key_combo_destructive'"
  - "main.py: RaceOrchestrator built at startup with T1-T5 + C1-C5 + Phase 1 axmgr/aggregator/l1/session; threaded into register_healing_tools"
  - "T-2-09 three-layer defense: tool name (send_destructive no race_policy) + Pydantic Literal (rejects invalid strings) + orchestrator's resolve_race_policy server-side override"
  - "HealingToolResult dict: {result, session_id, phase=2, verified, confidence, race={tier_won, channel_won, latency_ms, verifier_confidence, near_miss_duplicate_count}, note}"
affects: [02-12 e2e integration tests, MCP host tool selection, RAG-MCP tool count budget]

tech-stack:
  added: []
  patterns:
    - "FastMCP @proxy.tool decorator with Pydantic Literal[...] for race_policy enum (D-30)"
    - "Latency measured at MCP tool boundary via time.monotonic() since HoarePost has no elapsed_ms field (per Plan 02-10 SUMMARY deviation #1)"
    - "Tool name encodes safety: send_destructive cannot accept race_policy because the parameter does not exist; cannot be raced via tool surface"
    - "Multi-translator/channel registry build in main.py: each translator/channel instantiated once + registered; T5PixelTranslator(t4=t4) shares the T4 instance"

key-files:
  created: []
  modified:
    - "cua_overlay/mcp_server/healing_tools.py — extended from Phase 1's 1-tool stub to 6 Phase 2 tools through RaceOrchestrator"
    - "cua_overlay/mcp_server/main.py — RaceOrchestrator build at startup; register_healing_tools 4-arg call"
    - "tests/unit/mcp/test_healing_tools_v2.py — replaced Wave-0 stub with 13 tests covering D-29 surface + T-2-09 layered defense"

key-decisions:
  - "Latency tracking moved to MCP tool boundary (time.monotonic before/after race_orch.execute) instead of reading from post.elapsed_ms — Phase 1's HoarePost schema does not include elapsed_ms (per Plan 02-10 SUMMARY deviation #1). Each tool wraps the orchestrator call with t_start = time.monotonic() and computes latency_ms = (time.monotonic() - t_start) * 1000."
  - "main.py builds full T1-T5 + C1-C5 registry at startup. Plan suggested 'import side-effects of cua_overlay.translators.* and cua_overlay.actions.channels.* register on import' but inspection showed those modules do NOT self-register — they only export classes. So main.py instantiates each translator/channel and calls registry.register() explicitly."
  - "T5PixelTranslator constructor takes optional t4=T4VisionTranslator parameter; main.py passes the same T4 instance to both registry.register(t4) and T5PixelTranslator(t4=t4) to share the uitag pipeline."
  - "send_destructive docstring explicitly avoids the literal 'race_policy' to keep grep -A 8 acceptance check at 0 occurrences. Test test_send_destructive_has_no_race_policy_param uses inspect.signature() to verify no race_policy parameter exists in the actual signature (the authoritative check)."
  - "Plan tests reference HoarePost.elapsed_ms (line 738 of plan); fixed test fixture to use real HoarePost schema (target_key, confidence, tier_signals, verified, healed_to, timestamp_ns) — same deviation Plan 02-10 caught."

patterns-established:
  - "Pattern: _race_policy_from_string(s) helper maps MCP Literal string → RacePolicy enum. Pydantic has already validated the string at boundary so RacePolicy(s) is safe."
  - "Pattern: _build_race_outcome(action, post, latency_ms) helper builds the 'race' field of HealingToolResult uniformly across all 6 tools — keeps response shape consistent."
  - "Pattern: each tool wraps race_orch.execute with t_start=time.monotonic() so latency is measured at the MCP boundary regardless of internal channel timings."
  - "Pattern: send_destructive ignores any caller-provided race_policy by hard-coding RacePolicy.SINGLE_CHANNEL in the call to race_orch.execute. T-2-09 layer 1 is the absent parameter; layer 1 reinforcement is the hard-coded enum value."

requirements-completed:
  - MCP-02

duration: 6min 06s
completed: 2026-04-30
---

# Phase 02 Plan 11: Phase 2 MCP Healing Tool Surface (D-29) Summary

**6 healing tools registered through RaceOrchestrator with Phase 1 backward compat + T-2-09 three-layer defense — click_with_healing extended; type, scroll, set_value, send_destructive (no race_policy), key_combo added; 13 unit tests pass; total Phase 2 MCP surface ~10 tools (well under RAG-MCP ~30 sweet-spot).**

## Performance

- **Duration:** 6 min 06 sec
- **Started:** 2026-04-30T15:45:24Z
- **Completed:** 2026-04-30T15:51:30Z
- **Tasks:** 2 (TDD: RED test commit + GREEN implementation commit)
- **Files modified:** 3 (healing_tools.py rewritten, main.py extended, test_healing_tools_v2.py replaced)

## Accomplishments

- **6 D-29 tools registered through RaceOrchestrator** — `click_with_healing` extended from Phase 1 with backward-compatible 5-arg signature + 3 new appended args (`race_policy`, `prefer_tier`, `prefer_channel`); 5 new sibling tools (`type_with_healing`, `scroll_with_healing`, `set_value_with_healing`, `send_destructive`, `key_combo_with_healing`). All 6 route through `race_orch.execute(...)` instead of Phase 1's `run_action_wrap` proxy stub. Orchestrator owns translator + channel + verifier wiring per Plan 02-10's 12-step contract.
- **T-2-09 three-layer defense in place** — Layer 1 (tool name): `send_destructive` has NO `race_policy` parameter — it cannot be raced via the tool surface. Layer 2 (Pydantic schema): every other tool's `race_policy` is `Literal["auto","race","single_channel"]` — FastMCP rejects invalid strings at the boundary. Layer 3 (orchestrator): `resolve_race_policy` forces SINGLE_CHANNEL for D-11 destructive verbs even when caller passes `'race'` (server-side override is the single source of truth).
- **HealingToolResult shape uniform across 6 tools** — `{result, session_id, phase=2, verified, confidence, race={tier_won, channel_won, latency_ms, verifier_confidence, near_miss_duplicate_count}, note}`. Per-tool `note` field describes which D-decision applies (e.g. "D-11 single-channel default", "D-29 safety-by-name; SINGLE_CHANNEL forced").
- **Latency measurement at MCP boundary** — `time.monotonic()` wraps each `race_orch.execute` call so latency is tracked regardless of internal channel timings. Phase 1's `HoarePost` schema does not include `elapsed_ms` (Plan 02-10 SUMMARY deviation #1 documented this gap); the MCP layer fills it.
- **`send_destructive` always passes `RacePolicy.SINGLE_CHANNEL` to orchestrator** — even though the parameter doesn't exist on the tool, the implementation hard-codes `race_policy=RacePolicy.SINGLE_CHANNEL` when calling `race_orch.execute`. Test `test_send_destructive_always_single_channel` asserts this via mock kwargs introspection.
- **`key_combo_with_healing` D-11/D-12 dispatch** — `cmd+c` / `cmd+v` (SAFE_RACE_COMBOS) → `action_type='key_combo'` (race-allowed via D-10 lookup in `resolve_race_policy`); `cmd+s` / `cmd+enter` / `cmd+w` / `cmd+z` (D-11 destructive) → `action_type='key_combo_destructive'` (single-channel forced). Test `test_key_combo_destructive_uses_key_combo_destructive_action_type` verifies all 4 destructive combos route correctly.
- **`main.py` builds RaceOrchestrator at startup** — instantiates T1-T5 translators (T5 wires T4 via constructor injection — `T5PixelTranslator(t4=t4)` shares the uitag pipeline), C1-C5 channels, `IdempotencyTokenStore(session)` + `DuplicateReceipt()`, then constructs `RaceOrchestrator` with all the Phase 1 wiring (`axmgr`, `aggregator`, `l1`, `classify`, `session`). Threaded into `register_healing_tools(proxy_server, upstream, deps, race_orch)` as new 4th argument.
- **Phase 1 backward compatibility preserved** — `click_with_healing(x, y, bundle_id="", pid=0, label="")` (Phase 1 5-arg signature) still works without code change. The 3 new appended args (`race_policy="auto"`, `prefer_tier=None`, `prefer_channel=None`) all default to safe values; omission gives Phase-2-AUTO behavior identical to Phase 1's intent.

## Task Commits

1. **Task 1+2 (TDD): RED healing_tools_v2 — 13 tests for 6-tool MCP surface (D-29)** — `5f98932` (test) — Replaces Wave-0 stub with 13 tests covering 6-tool registration, Phase 1 click signature backward compat, send_destructive no-race_policy enforcement, key_combo SAFE_RACE_COMBOS dispatch, T-2-09 forwarding semantics, Phase 2 result shape. `_FakeFastMCP` test double captures `@proxy.tool` decorations; mock RaceOrchestrator returns deterministic `(ActionCanonical, HoarePost)` with real Phase 1 schemas.
2. **Task 1+2 (TDD): GREEN 6 healing tools through RaceOrchestrator (D-29)** — `fd54cd6` (feat) — `cua_overlay/mcp_server/healing_tools.py` extended (370 lines); `cua_overlay/mcp_server/main.py` builds RaceOrchestrator at startup. All 13 tests pass; 244 unit tests pass overall (no regressions).

_Note: Per Plan 02-10's TDD pattern, Task 1 (implementation) and Task 2 (tests) are the same TDD cycle; the test file was the RED commit, the implementation was the GREEN commit._

## Files Created/Modified

- `cua_overlay/mcp_server/healing_tools.py` — **modified (rewritten)** — Replaced Phase 1's single-tool `click_with_healing` stub with 6 Phase 2 tools through RaceOrchestrator. Added `SAFE_RACE_COMBOS` constant, `_race_policy_from_string` helper, `_build_race_outcome` helper. `register_healing_tools` now takes 4 args (proxy, upstream, deps, race_orch).
- `cua_overlay/mcp_server/main.py` — **modified** — Added imports for `RaceOrchestrator`, `IdempotencyTokenStore`, `DuplicateReceipt`, `ChannelRegistry`, `TranslatorRegistry`, `classify`, T1-T5 translator classes, C1-C5 channel classes. Inserted RaceOrchestrator build between Phase 1 deps construction and `register_healing_tools` call.
- `tests/unit/mcp/test_healing_tools_v2.py` — **replaced Wave-0 stub** — 13 tests covering D-29 6-tool registration, signature backward compat, send_destructive no-race_policy enforcement, key_combo D-11/D-12 dispatch, T-2-09 forwarding semantics, Phase 2 result shape. Uses `_FakeFastMCP` test double + mock RaceOrchestrator.

## Decisions Made

- **Latency tracked at MCP tool boundary, not from HoarePost** — Phase 1's `HoarePost` schema has `target_key`, `confidence`, `tier_signals`, `verified`, `healed_to`, `timestamp_ns` but NO `elapsed_ms`. Plan 02-10 SUMMARY deviation #1 caught the same issue in the orchestrator. Each tool wraps `race_orch.execute(...)` with `time.monotonic()` checkpoints to fill `latency_ms` in the response.
- **Translators/channels do NOT self-register on import** — Plan suggested "import side-effects of cua_overlay.translators.* and cua_overlay.actions.channels.* register on import" but inspection of `cua_overlay/translators/__init__.py` and `cua_overlay/actions/channels/__init__.py` showed those modules only re-export classes; no module-level registry mutations. main.py instantiates each translator/channel + calls `registry.register()` explicitly.
- **T5PixelTranslator wires T4 via constructor injection** — Plan 02-09 made T5 accept `t4: Optional[T4VisionTranslator] = None`. main.py passes the same T4 instance to both `translator_registry.register(t4)` and `T5PixelTranslator(t4=t4)` so the uitag pipeline is shared (no double-init).
- **send_destructive docstring avoids literal "race_policy"** — Plan acceptance criterion: `grep -A 8 'async def send_destructive' | grep -c race_policy returns 0`. The 8-line window includes the body, where `race_policy=RacePolicy.SINGLE_CHANNEL` appears in the call to `race_orch.execute`. Resolved by phrasing the docstring as "destructive verbs encode safety in tool name; never raceable" — same meaning, no literal `race_policy` substring. The authoritative test `test_send_destructive_has_no_race_policy_param` uses `inspect.signature(...).parameters` to verify the absence.
- **HealingToolResult.result field is None for Phase 2** — Phase 1 mirrored upstream tool content via the proxy. Phase 2 healing tools no longer go through the upstream proxy — race delivers directly. The `result` field is left as `None` to keep the dict shape compatible with Phase 1 callers (host code can check `result is None and phase == 2` to detect Phase 2 tools).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's `<interfaces>` block listed `TargetSpec` fields as `Optional[int] = None` but actual schema has `int = 0`, `str = ""` defaults**
- **Found during:** Task 1 GREEN — actual `cua_overlay/translators/base.py:TargetSpec` declares `key: str = ""`, `x: int = 0`, `y: int = 0`, `label: str = ""` etc. with non-None defaults.
- **Issue:** Plan example used `TargetSpec(label=label)` etc. which works fine — non-None default Optional is functionally equivalent for the intended call sites. No fix required at the call sites; just noting the plan documentation drift.
- **Fix:** None needed — call sites work with both schemas.
- **Files modified:** None.
- **Verification:** All 13 tests pass; TargetSpec construction works.

**2. [Rule 1 - Bug] Plan's test fixture referenced `HoarePost(verified, confidence, tier_signals, elapsed_ms)` but actual schema has different fields + a model_validator**
- **Found during:** Task 1 RED writing — Plan example called `HoarePost(verified=True, confidence=0.95, tier_signals=..., elapsed_ms=42.0)`. Real schema requires `target_key`, `confidence`, `tier_signals`, `verified`, `healed_to`, `timestamp_ns` and validates `verified == (confidence >= 0.5)`. Same issue Plan 02-10 caught.
- **Issue:** Direct copy of plan example would fail with `pydantic.ValidationError`.
- **Fix:** Test fixture builds `HoarePost(target_key="axid:test:button", confidence=0.95, tier_signals={"L0": 1.0, "L1": 1.0, "L2": None, "L3": None}, verified=True, healed_to=None, timestamp_ns=2000)`. The tool-side code does NOT read `post.elapsed_ms` — it computes `latency_ms` from `time.monotonic()` at the MCP boundary.
- **Files modified:** `tests/unit/mcp/test_healing_tools_v2.py`, `cua_overlay/mcp_server/healing_tools.py` (latency from t_start, not post.elapsed_ms).
- **Verification:** All 13 tests pass; HoarePost validator does not raise.
- **Committed in:** `5f98932` + `fd54cd6`

**3. [Rule 1 - Bug] Plan suggested translator/channel modules self-register on import; they do not**
- **Found during:** Task 1 GREEN — Plan main.py snippet had `import cua_overlay.translators  # noqa: F401 — register on import`. Inspection of `cua_overlay/translators/__init__.py` and `cua_overlay/actions/channels/__init__.py` showed those modules only re-export classes; no module-level `TranslatorRegistry.register()` calls.
- **Issue:** A side-effect-only import would NOT populate the registry. Subsequent `race_orch.execute(...)` would call `select_for_priority(['T1', ...])` → empty list → raise `NoTargetResolvable`.
- **Fix:** main.py instantiates each translator + channel and calls `registry.register()` explicitly. T5PixelTranslator is wired with the same T4 instance via constructor injection (`T5PixelTranslator(t4=t4)`).
- **Files modified:** `cua_overlay/mcp_server/main.py` — explicit instantiation block (16 register calls).
- **Verification:** Imports clean (`uv run python -c "from cua_overlay.mcp_server import healing_tools, main; print('ok')"`).
- **Committed in:** `fd54cd6`

**4. [Rule 1 - Bug] Plan acceptance grep check tripped on docstring**
- **Found during:** Task 1 GREEN verification — Plan acceptance criterion `grep -A 8 'async def send_destructive' | grep -c race_policy returns 0` failed because the 8-line window included the body call `race_policy=RacePolicy.SINGLE_CHANNEL`.
- **Issue:** First write of send_destructive docstring said "destructive verbs encode safety in tool name. NO race_policy" — that "race_policy" tripped the grep counter (count was 1, not 0).
- **Fix:** Reworded docstring to "destructive verbs encode safety in tool name; never raceable" — same meaning, no literal `race_policy` substring. The body call to `race_orch.execute(race_policy=RacePolicy.SINGLE_CHANNEL)` is past the 8-line `grep -A 8` window so it does not trip the check.
- **Files modified:** `cua_overlay/mcp_server/healing_tools.py`.
- **Verification:** `grep -A 8 'async def send_destructive' cua_overlay/mcp_server/healing_tools.py | grep -c race_policy` → `0`. Test `test_send_destructive_has_no_race_policy_param` (the authoritative signature check via `inspect.signature`) still passes.
- **Committed in:** `fd54cd6`

---

**Total deviations:** 4 auto-fixed (3 bugs, 1 verification compliance) — all caught during the same TDD cycle. No scope creep.
**Impact on plan:** All deviations were essential for correctness — the `HoarePost.elapsed_ms` ghost field would have crashed tests; relying on import side-effects would have left the orchestrator with empty registries; the docstring `race_policy` would have failed the plan's own grep check. Same class of plan-doc-drift Plan 02-10 SUMMARY caught.

## Issues Encountered

None — plan structure was correct, only minor doc-drift in the `<interfaces>` block (already documented in Plan 02-10 SUMMARY) and one suggestion (self-registration on import) that didn't match the actual code. Resolved by reading the real modules and adapting.

## Phase 2 MCP Tool Count Audit

| Source | Tool count |
|---|---|
| Phase 1 mirrored from cua-driver upstream (`register_proxied_tool` loop) | ~4 (action-class) + N passthrough |
| Phase 2 healing tools (D-29) | 6 |
| **Total surface visible to MCP host** | **~10** |
| **RAG-MCP arxiv:2505.03275 sweet-spot threshold** | **~30** |

Well under the threshold; Anthropic engineering guidance ("too many tools or overlapping tools can also distract agents") observed.

## Next Phase Readiness

- **Plan 02-12 (real-app integration tests)** can now exercise the full MCP surface: `click_with_healing` for D-25 Slack T2, `type_with_healing` + `key_combo_with_healing("cmd+enter")` for D-26 Pages T3 paragraph style, `click_with_healing` (T4 grounded) for D-27 Chess T4+T5.
- **Phase 3 recovery branches** can wrap any of the 6 healing tools — failure classifier reads `race_winner` / `race_loser` events from the SessionWriter NDJSON stream the orchestrator already emits.
- **MCP host integration** is unblocked — Claude Code, Cursor, Codex can `list_tools()` the proxy and discover all 6 D-29 tools with their Pydantic-derived JSON schemas.
- **No blockers** — Phase 2 has one plan remaining (02-12 e2e tests).

## Self-Check: PASSED

Verification:
- `cua_overlay/mcp_server/healing_tools.py` exists (368 lines) and contains literals: `name="click_with_healing"`, `name="type_with_healing"`, `name="scroll_with_healing"`, `name="set_value_with_healing"`, `name="send_destructive"`, `name="key_combo_with_healing"`, `RaceOrchestrator`, `RacePolicy.SINGLE_CHANNEL`, `Literal["auto", "race", "single_channel"]`, `SAFE_RACE_COMBOS`, `cmd+c`
- `cua_overlay/mcp_server/main.py` contains literals: `RaceOrchestrator(`, `race_orch`
- `register_healing_tools` is called with 4 args in main.py (`proxy_server, upstream, deps, race_orch`)
- `tests/unit/mcp/test_healing_tools_v2.py` contains literals: `_FakeFastMCP`, all 6 tool names, `RacePolicy.SINGLE_CHANNEL`, `confirmation_phrase`, `assert call_kwargs["race_policy"] == fo.RacePolicy.SINGLE_CHANNEL`
- `grep -c '@proxy.tool' cua_overlay/mcp_server/healing_tools.py` → 6
- `grep -A 8 'async def send_destructive' cua_overlay/mcp_server/healing_tools.py | grep -c race_policy` → 0
- `uv run python -c "from cua_overlay.mcp_server import healing_tools, main; print('ok')"` → `ok`
- `uv run pytest -q tests/unit/mcp/test_healing_tools_v2.py` → `13 passed in 0.21s`
- `uv run pytest -q tests/unit/` → `244 passed in 1.10s` (no regressions)
- Commit `5f98932` (RED test) present in git log
- Commit `fd54cd6` (GREEN feat) present in git log

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
