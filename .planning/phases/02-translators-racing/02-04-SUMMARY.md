---
phase: 02-translators-racing
plan: 04
subsystem: translators-channels-base
tags: [protocol, registry, pydantic-frozen, D-14, T-2-06, ACT-01, TRANS-01, TRANS-02, TRANS-03, TRANS-04, TRANS-05, channel-binding, tier-for-channel]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: cua_overlay.state.graph.UIElement + Bbox, cua_overlay.state.causal_dag.ActionCanonical
  - phase: 02-translators-racing
    provides: cua_overlay.actions.idempotency.IdempotencyTokenStore (Plan 02-02), cua_overlay.actions.race_policy.RacePolicy (Plan 02-02), Wave-0 stub tests (Plan 02-01)
provides:
  - cua_overlay.translators package — interface contracts (Translator Protocol, TranslatorTarget, TargetSpec, TranslatorRegistry)
  - cua_overlay.actions.channels package — interface contracts (Channel Protocol, ChannelOutcome frozen Pydantic)
  - cua_overlay.actions.channel_registry module — ChannelRegistry with register/get/select/tier_for_channel
  - TIER_TO_CHANNEL_DEFAULT module constant — D-14 verbatim mapping (T1→C2, T2→C5, T3→C4, T4→C1, T5→C3)
  - CHANNEL_TO_TIER_DEFAULT module constant — inverted lookup, computed at module load
  - ChannelRegistry.tier_for_channel(name) — O(1) reverse lookup for race orchestrator (Plan 02-10) to fill ActionCanonical.tier from winning ChannelOutcome.channel
  - 16 unit tests (5 translator-registry + 11 channel-registry) gating Wave-2 plans
affects: [phase-02 plans 02-05 (T1+C2), 02-06 (T2+C5), 02-07 (T3+C4), 02-08 (T4 Vision), 02-09 (T5 Pixel + C1+C3), 02-10 (race orchestrator), 02-11 (MCP healing tools v2)]

# Tech tracking
tech-stack:
  added: []  # No new dependencies — reuses anyio (race-policy module dep), pydantic v2, structlog (already pinned)
  patterns:
    - "Interface-first wave plan — ZERO concrete translators or channels; only Protocol classes + Pydantic schemas + registries. Wave 2 (02-05..02-09) plans subclass without redefining."
    - "Frozen Pydantic ChannelOutcome (T-2-06/T-2-08 race-cancel correctness): channels return new instances rather than mutating; race orchestrator can safely cache references"
    - "Pydantic Literal type validation as primary mitigation — Literal['C1','C2','C3','C4','C5'] rejects invalid ChannelKind ('C9' raises ValidationError) at construction time, no runtime check needed"
    - "@runtime_checkable Protocol — TranslatorRegistry + ChannelRegistry can isinstance() against duck-typed test fakes without nominal subclassing"
    - "D-14 default mapping codified as module-level dict (TIER_TO_CHANNEL_DEFAULT) + auto-inverted (CHANNEL_TO_TIER_DEFAULT) — both consumed by ChannelRegistry.select and ChannelRegistry.tier_for_channel"
    - "Idempotent register() — re-registering same tier/name replaces with structlog.warning event (useful for tests; useful when Wave-2 plans reload)"
    - "select(translator_priority, RacePolicy) is the policy-aware fan-out: RACE returns all bound channels in priority order (de-duped); SINGLE_CHANNEL stops at first available"

key-files:
  created:
    - "cua_overlay/translators/__init__.py — package init re-exporting TargetSpec, Translator, TranslatorTarget, TranslatorRegistry"
    - "cua_overlay/translators/base.py — Translator Protocol + TranslatorTarget + TargetSpec Pydantic schemas"
    - "cua_overlay/translators/registry.py — TranslatorRegistry with register/get/select_for_priority"
    - "cua_overlay/actions/channels/__init__.py — channels sub-package init re-exporting Channel, ChannelOutcome"
    - "cua_overlay/actions/channels/base.py — Channel Protocol + ChannelOutcome frozen Pydantic model"
    - "cua_overlay/actions/channel_registry.py — ChannelRegistry + TIER_TO_CHANNEL_DEFAULT + CHANNEL_TO_TIER_DEFAULT + tier_for_channel"
  modified:
    - "tests/unit/translators/test_translators_registry.py — replaced importorskip stub with 5 real tests"
    - "tests/unit/actions/test_channel_registry.py — replaced importorskip stub with 11 real tests"

key-decisions:
  - "TranslatorTarget uses ConfigDict(arbitrary_types_allowed=True) — needed for ax_element: Optional[Any] (raw AXUIElementRef opaque from PyObjC). Pydantic v2 rejects Any-typed bytes-like opaque handles by default. This is the only translator-target field that breaks pure-Pydantic typing."
  - "TargetSpec uses ConfigDict(frozen=True) but TranslatorTarget does NOT — translators may need to mutate extras dict to attach pre-fire state (e.g. T5 Pixel attaches pre_phash before fire); freezing TranslatorTarget would force a copy-on-write pattern that adds complexity for no safety benefit (TranslatorTarget never crosses race boundary)."
  - "ChannelOutcome IS frozen — channels MUST return a new instance rather than mutate. This is the T-2-06/T-2-08 race-cancel correctness contract: race orchestrator may cache outcome references across cancel_scope boundaries; mutation would corrupt the verifier's view of who won."
  - "tier_for_channel is a pure D-14 lookup, NOT a registration-derived map. Even if a ChannelRegistry has zero channels registered, tier_for_channel('C2') returns 'T1'. Rationale: race orchestrator (Plan 02-10) calls this to fill ActionCanonical.tier on the winning ChannelOutcome — the orchestrator does NOT know which translator produced the target; it must INFER tier from channel via the canonical D-14 mapping."
  - "CHANNEL_TO_TIER_DEFAULT computed once at module load (not per-call) — tests that mutate TIER_TO_CHANNEL_DEFAULT mid-test (e.g. test_select_dedupes_channel_appearing_in_multiple_tiers) must rebuild this map themselves. Documented inline in channel_registry.py."
  - "ChannelRegistry.select honors RacePolicy.RACE vs RacePolicy.SINGLE_CHANNEL but does NOT honor RacePolicy.AUTO — caller must call resolve_race_policy first. Rationale: select() is a pure dispatcher; AUTO requires action_type which the registry doesn't have. Plan 02-10 race orchestrator calls resolve_race_policy(policy, action.action_type) → ChannelRegistry.select(priority, resolved_policy)."
  - "Wave-0 importorskip stubs replaced with active tests — Phase 2 Wave 2+ plans now have a concrete contract surface. Tests catch protocol shape regressions immediately."

patterns-established:
  - "Per-feature sub-package mirror — cua_overlay/translators/ + cua_overlay/actions/channels/ both follow the per-feature shape established in Phase 1 (state/, ax/, profile/, verifier/)"
  - "Module-level constant + inverted-once pattern — TIER_TO_CHANNEL_DEFAULT + CHANNEL_TO_TIER_DEFAULT (auto-inverted dict comprehension at module load) is the canonical shape for any future bidirectional lookup table"
  - "Protocol + runtime_checkable + duck-typed test fakes — Translator/Channel Protocols accept any object with .tier/.name + .resolve()/.fire() async methods; tests use plain classes (no subclassing required)"
  - "Wave-0 stub → Wave-1 real test transition: replace `pytest.importorskip(MODULE)` with the actual import; replace placeholder assertion with comprehensive test suite. Plans 02-02 (idempotency, race_policy, duplicate_receipt) and 02-03 (known_apps) followed the same pattern. Phase 2 Wave 2 plans (02-05..02-09) will continue."

requirements-completed:
  - TRANS-01
  - TRANS-02
  - TRANS-03
  - TRANS-04
  - TRANS-05
  - ACT-01

# Threats mitigated
threats_mitigated:
  - "T-2-06 channel registry — Pydantic Literal['C1','C2','C3','C4','C5'] enforces ChannelKind at ChannelOutcome construction time. Test test_channel_outcome_pydantic_rejects_bad_kind verifies ValidationError on channel='C9'. Mitigation is type-system enforced + test-verified, no runtime branch needed."
  - "T-2-08 race-cancel correctness (precursor) — ChannelOutcome.model_config = ConfigDict(frozen=True) prevents channels from mutating outcomes. Test test_channel_outcome_is_frozen verifies ValidationError on outcome.status = 'errored'. Race orchestrator (Plan 02-10) builds on this contract; this plan ships the immutable foundation."

# Metrics
duration: 4min
completed: 2026-04-30
---

# Phase 2 Plan 04: Translator + Channel Registries Summary

**Interface-first Wave 1 plan — ships the Translator and Channel Protocol contracts plus their two registries. ZERO concrete translators or channels created; Wave 2 plans (02-05..02-09) subclass these to register T1-T5 + C1-C5 without redefining schemas. D-14 default tier→channel binding codified; ChannelRegistry.tier_for_channel reverse lookup unblocks Plan 02-10 race orchestrator.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-04-30T06:49:33Z
- **Completed:** 2026-04-30T06:52:53Z
- **Tasks:** 2 (both `type=auto`, both green on first run)
- **Files modified:** 8 (6 created in cua_overlay/, 2 stub tests rewritten with real assertions)

## Accomplishments

- **Translator Protocol shipped** — `Translator(Protocol)` with `tier: Literal['T1'..'T5']`, async `resolve(bundle_id, pid, target_spec) -> Optional[TranslatorTarget]`, async `validate(target) -> bool`. `@runtime_checkable` so Wave-2 fakes don't need nominal subclassing.
- **TranslatorTarget envelope** — Pydantic model carrying `element: UIElement` plus per-tier optional handles (`ax_element`, `cdp_node_id` + `cdp_session_id`, `as_target_spec`, `grounded_bbox`, `extras` dict). Mutable (not frozen) so translators can attach pre-fire state to extras.
- **TargetSpec frozen Pydantic** — caller-side request shape (key, x, y, label, role, aria_label, css, as_verb). All fields default to `""` or `0` so tests can construct partial specs.
- **TranslatorRegistry** — tier-keyed dict with `register/get/select_for_priority(priority_list)`. `select_for_priority` skips unregistered tiers (graceful degradation during partial Wave-2 builds).
- **Channel Protocol shipped** — `Channel(Protocol)` with `name: Literal['C1'..'C5']`, async `fire(action, target, store, cancel_event) -> ChannelOutcome`. Docstring locks the fire-path contract: `try_claim BEFORE syscall`, `cancel_event.is_set() BEFORE syscall`, return frozen ChannelOutcome.
- **ChannelOutcome frozen Pydantic model** — `channel`, `status` (Literal `fired|skipped|cancelled|errored`), `fired_at_ns`, `error`, `skipped_reason`, `verified` (set by orchestrator post-verifier, never by channel itself). T-2-06 + T-2-08 mitigation.
- **D-14 mapping codified** — `TIER_TO_CHANNEL_DEFAULT` module constant: `{T1: C2, T2: C5, T3: C4, T4: C1, T5: C3}`. `CHANNEL_TO_TIER_DEFAULT` auto-inverted at module load.
- **ChannelRegistry.tier_for_channel** — O(1) reverse lookup. Pure D-14 lookup (no registration needed). Used by Plan 02-10 race orchestrator to fill ActionCanonical.tier on winning ChannelOutcome.channel.
- **ChannelRegistry.select(translator_priority, RacePolicy)** — RACE returns all channels for priority tiers (de-duped); SINGLE_CHANNEL stops at first available. Skips unregistered channels (graceful degradation).
- **16/16 unit tests pass** (5 translator + 11 channel) in 0.03s.
- **No regressions** — full unit suite: **169 passed / 10 skipped / 0 errors** (was 153/12 in 02-03; gain of 16 new tests, drop of 2 stubs flipped to active).

## Task Commits

1. **Task 1: Translator Protocol + TranslatorTarget + TargetSpec + TranslatorRegistry**
   - `87767ad` (feat) — translators package + 5 tests pass

2. **Task 2: Channel Protocol + ChannelOutcome + ChannelRegistry with D-14 default binding**
   - `21e9583` (feat) — channels sub-package + channel_registry + 11 tests pass

**Plan metadata commit:** to be appended after this SUMMARY.md is written.

## D-14 Default Binding Verified

| Tier | Channel | Test verb | Test target |
|------|---------|-----------|-------------|
| T1 (AX) | C2 (kAXPress) | `AXUIElementPerformAction(elem, kAXPressAction)` | Cocoa toolbar buttons, AX-rich apps |
| T2 (CDP) | C5 (CDP Input.dispatchMouseEvent) | `Input.dispatchMouseEvent({type:'mousePressed',...})` | Electron renderer (Slack/Cursor/Obsidian) |
| T3 (AS) | C4 (AppleScript) | `tell application "X" to ...` | iWork apps, Mail, Calendar, scriptable apps |
| T4 (Vision/uitag) | C1 (CGEvent — public; SkyLight in Phase 6) | `CGEventPostToPid(pid, event)` | Vision-grounded targets (Chess, canvas) |
| T5 (Pixel) | C3 (CGEvent.postToPid w/ cursor) | `CGEventPostToPid(pid, event)` w/ cursor warp | Last-resort pixel grounding |

Verified by `test_select_race_returns_all_channels_for_priority` and `test_d14_default_binding_complete`.

## Files Created/Modified

### Created
- `cua_overlay/translators/__init__.py` — package init; re-exports TargetSpec, Translator, TranslatorTarget, TranslatorRegistry
- `cua_overlay/translators/base.py` — Translator Protocol (tier Literal T1-T5, async resolve/validate) + TranslatorTarget (element + per-tier optional handles + extras dict) + TargetSpec frozen Pydantic
- `cua_overlay/translators/registry.py` — TranslatorRegistry with register/get/select_for_priority; structlog events `translator.replaced`, `translator.registered`, `translator.tier_not_registered`
- `cua_overlay/actions/channels/__init__.py` — channels sub-package init; re-exports Channel, ChannelOutcome
- `cua_overlay/actions/channels/base.py` — Channel Protocol (name Literal C1-C5, async fire) + ChannelOutcome frozen Pydantic
- `cua_overlay/actions/channel_registry.py` — ChannelRegistry + TIER_TO_CHANNEL_DEFAULT (D-14 verbatim) + CHANNEL_TO_TIER_DEFAULT (auto-inverted) + tier_for_channel reverse lookup; structlog events `channel.replaced`, `channel.registered`, `channel.not_registered`

### Modified
- `tests/unit/translators/test_translators_registry.py` — Wave-0 importorskip stub → 5 real tests (register/get, select_for_priority order, skip-unregistered, replace-idempotent, TranslatorTarget optional handles)
- `tests/unit/actions/test_channel_registry.py` — Wave-0 importorskip stub → 11 real tests (register/get, RACE all-channels, SINGLE_CHANNEL stops, skip unregistered, dedupe across tiers, T-2-06 Pydantic Literal rejects C9, frozen=True mutation rejected, default verified=False, D-14 binding complete, tier_for_channel inverse, CHANNEL_TO_TIER_DEFAULT inverse-of-TIER_TO_CHANNEL_DEFAULT)

## Decisions Made

See `key-decisions` in frontmatter for the full list. Brief rationale highlights:

- **TranslatorTarget mutable, ChannelOutcome frozen** — TranslatorTarget never crosses the race boundary (translator → channel only); ChannelOutcome DOES cross (channel → race orchestrator → verifier). The race-cancel correctness contract requires immutability on outcomes, not on targets.
- **`arbitrary_types_allowed=True` on TranslatorTarget** — needed for `ax_element: Optional[Any]` to carry raw AXUIElementRef opaque PyObjC handles. The only field that needs this; documented inline.
- **`tier_for_channel` is a pure D-14 lookup** — does NOT depend on registry state. Race orchestrator (Plan 02-10) calls this on the winning ChannelOutcome to fill ActionCanonical.tier; the orchestrator never knows which translator produced the target, it INFERS tier from channel via the canonical D-14 mapping.
- **`select` does NOT handle RacePolicy.AUTO** — pure dispatcher; AUTO requires action_type. Plan 02-10 race orchestrator calls `resolve_race_policy(policy, action.action_type) → ChannelRegistry.select(priority, resolved_policy)`. Keeping AUTO out of select makes the registry stateless and trivial to test.

## Deviations from Plan

None — plan executed exactly as written. Both tasks landed on first run, no debug iterations needed.

## Issues Encountered

- Two PreToolUse:Write hook reminders fired when the tooling re-prompted to verify Read-before-Edit on the two test stub files. Both files had been read earlier in the session; the writes succeeded as confirmed by post-write verification (`pytest -q ...` passed and `grep` on acceptance literals matched expected counts).

## User Setup Required

None. Pure stdlib + already-installed deps (anyio, pydantic v2, structlog).

## Next Phase Readiness

- **Plan 02-05 (T1 AX translator + C2 kAXPress channel):** can `from cua_overlay.translators.base import Translator, TranslatorTarget, TargetSpec` + `from cua_overlay.actions.channels.base import Channel, ChannelOutcome` immediately. T1AXTranslator subclasses (duck-types) Translator with `tier='T1'`; C2AXChannel implements Channel with `name='C2'`.
- **Plan 02-06 (T2 CDP translator + C5 CDP Input.dispatchMouseEvent channel):** same import path; reads `AppProfile.cdp_available_after_relaunch` from Plan 02-03; calls `cdp-use` for DOM.querySelector + Input.dispatchMouseEvent.
- **Plan 02-07 (T3 AppleScript translator + C4 AppleScript channel):** dedicated ThreadPoolExecutor per Plan 02-03 D-04.
- **Plan 02-08 (T4 Vision translator):** uitag pipeline → TranslatorTarget; binds to C1 by default per D-14.
- **Plan 02-09 (T5 Pixel translator + C1 + C3 channels):** CGWindowList screen reads + ImageHash dHash + CGEvent.postToPid wiring.
- **Plan 02-10 (race orchestrator):** can `from cua_overlay.translators import TranslatorRegistry; from cua_overlay.actions.channel_registry import ChannelRegistry; ChannelRegistry().tier_for_channel(C5)` returns `'T2'` for filling ActionCanonical.tier on winning outcomes.
- **No blockers.** All 16 new tests pass; full unit suite (169 tests, 1.13s) clean; no regressions.

## Self-Check: PASSED

Files created (6 verified):
- FOUND: cua_overlay/translators/__init__.py
- FOUND: cua_overlay/translators/base.py
- FOUND: cua_overlay/translators/registry.py
- FOUND: cua_overlay/actions/channels/__init__.py
- FOUND: cua_overlay/actions/channels/base.py
- FOUND: cua_overlay/actions/channel_registry.py

Files modified (2 verified):
- FOUND: tests/unit/translators/test_translators_registry.py (replaced Wave-0 stub)
- FOUND: tests/unit/actions/test_channel_registry.py (replaced Wave-0 stub)

Commits verified (both in git log):
- FOUND: 87767ad (Task 1: feat 02-04 translator base + registry)
- FOUND: 21e9583 (Task 2: feat 02-04 channel base + registry + D-14)

Acceptance criteria literals (all greppable):
- FOUND: `class Translator(Protocol)`, `class TranslatorTarget`, `class TargetSpec`, `Literal["T1", "T2", "T3", "T4", "T5"]` in cua_overlay/translators/base.py
- FOUND: `class TranslatorRegistry`, `select_for_priority` (×2) in cua_overlay/translators/registry.py
- FOUND: Translator|TranslatorTarget re-exported from cua_overlay/translators/__init__.py
- FOUND: `class Channel(Protocol)`, `class ChannelOutcome`, `Literal["C1", "C2", "C3", "C4", "C5"]` (×2), `frozen=True` in cua_overlay/actions/channels/base.py
- FOUND: `class ChannelRegistry`, `TIER_TO_CHANNEL_DEFAULT` (×5), `"T1": "C2"`, `CHANNEL_TO_TIER_DEFAULT` (×2), `def tier_for_channel` in cua_overlay/actions/channel_registry.py

Verification commands (all pass):
- `uv run pytest -q tests/unit/translators/test_translators_registry.py` → 5 passed in 0.03s
- `uv run pytest -q tests/unit/actions/test_channel_registry.py` → 11 passed in 0.04s
- `uv run pytest -q tests/unit/translators/test_translators_registry.py tests/unit/actions/test_channel_registry.py` → 16 passed in 0.03s
- `uv run pytest -q tests/ -m "not integration and not manual"` → 169 passed, 10 skipped, 36 deselected in 1.13s
- `python -c "from cua_overlay.translators import Translator, TranslatorTarget, TargetSpec, TranslatorRegistry; from cua_overlay.actions.channels.base import Channel, ChannelOutcome; from cua_overlay.actions.channel_registry import ChannelRegistry, TIER_TO_CHANNEL_DEFAULT; print('ok')"` → `ok`

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
