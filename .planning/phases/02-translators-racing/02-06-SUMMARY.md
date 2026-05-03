---
phase: 02-translators-racing
plan: 06
subsystem: t2-cdp-translator-c5-channel
tags: [TRANS-02, ACT-01, T2, C5, cdp-use, Input.dispatchMouseEvent, D-02, D-03, D-14, D-24, P8, T-2-01, T-2-02, T-2-08]

# Dependency graph
requires:
  - phase: 01-foundation
    provides: basicctrl.state.graph.UIElement + Bbox + Source.CDP, basicctrl.state.causal_dag.ActionCanonical, basicctrl.persist.session_writer.SessionWriter
  - phase: 02-translators-racing
    provides: basicctrl.translators.base (Translator Protocol, TranslatorTarget with cdp_node_id/cdp_session_id/extras fields, TargetSpec.css from Plan 02-04), basicctrl.actions.channels.base (Channel Protocol, ChannelOutcome from Plan 02-04), basicctrl.actions.idempotency.IdempotencyTokenStore (Plan 02-02), basicctrl.profile.known_apps.KNOWN_APPS (D-21 cdp_after_relaunch=True for Slack/Cursor/Obsidian, Plan 02-03)
  - external: cdp-use==1.4.5 (D-02; verified PyPI 2026-02-22; vendored alongside browser-harness via shared upstream — D-03 forbids cross-tool import)
provides:
  - basicctrl.translators.t2_cdp.T2CDPTranslator — concrete T2 translator (tier='T2') wrapping cdp-use 1.4.5 with D-24 workspace filter
  - basicctrl.actions.channels.c5_cdp_input.C5CDPInputChannel — concrete C5 channel (name='C5') firing CDP Input.dispatchMouseEvent
  - 9 unit tests for T2 (mocked httpx + workspace filter scenarios) replacing the Wave-0 importorskip stub
  - 9 unit tests for C5 (fake CDPClient factory + idempotency + cancel + bbox center)
  - extras={"ws_url": ws_url} convention on TranslatorTarget for cross-fire CDP re-attach
affects:
  - phase-02 plan 02-10 (race orchestrator wires T2+C5 alongside T1+C2 as second default tier-channel pair per D-14)
  - phase-02 plan 02-11 (MCP healing tool surface reads AppProfile.cdp_available_after_relaunch from KNOWN_APPS to prompt user before T2 path activates)
  - phase-02 plan 02-12 (Slack T2-wins integration test calls T2CDPTranslator.resolve + C5CDPInputChannel.fire end-to-end against a relaunched Slack)
  - plans 02-07..02-09 (T3-T5 follow same Translator+Channel implementation shape; T2/C5 is the second canonical reference pair after T1/C2)

# Tech tracking
tech-stack:
  added: []  # cdp-use==1.4.5 already pinned in pyproject.toml from Wave 0; this plan first uses it
  patterns:
    - "Translator Protocol implementation #2 — T2CDPTranslator implements Translator without nominal subclassing (duck-typed @runtime_checkable Protocol from Plan 02-04). Same shape as T1AXTranslator."
    - "Channel Protocol implementation #2 — C5CDPInputChannel implements Channel similarly. Same shape as C2AXPressChannel."
    - "extras['ws_url'] cross-fire convention — T2 puts the discovered ws URL in TranslatorTarget.extras at resolve-time; C5 reads it at fire-time and re-opens its own CDPClient. Phase 2 trades ~10ms of localhost socket re-open for clean per-fire CDPClient lifecycle. Future translators that need similar cross-call state should use extras with a documented key (per channel: c5='ws_url')."
    - "Bundle-id-keyed workspace filter (D-24) — `_pick_workspace_target` is a switch on bundle_id with explicit per-Electron-app URL substring rules. Slack: '.slack.com' (with leading dot — must match workspace subdomain redirect, not bare slack.com). Cursor: 'vscode-' prefix. Obsidian: 'obsidian' substring. Default: first type=page (handles Chrome native CDP)."
    - "Mocked-CDP unit tests (no real socket) — fake CDPClient context manager with MagicMock-backed cdp.send.<Domain>.<method> tree records all dispatched events. Lets unit tests run on any host without port 9222 setup. Pattern reusable for Plan 02-12 stress tests (1000+ fires)."
    - "TDD strict per task — RED commit (failing tests) → GREEN commit (implementation). Same shape as Plan 02-05 (4 commits total: 2 RED + 2 GREEN)."

key-files:
  created:
    - "basicctrl/translators/t2_cdp.py — T2CDPTranslator (cdp-use 1.4.5; localhost:9222..9225 probe; D-24 workspace filter; flatten=True attach; DOM.querySelector + DOM.getBoxModel → bbox-center; extras['ws_url'] convention)"
    - "basicctrl/actions/channels/c5_cdp_input.py — C5CDPInputChannel (try_claim → cancel-check → ws_url-from-extras → CDPClient → mousePressed+mouseReleased PAIR at bbox center)"
    - "tests/unit/actions/channels/test_c5_cdp_input.py — 9 unit tests with fake CDPClient factory"
  modified:
    - "basicctrl/translators/__init__.py — re-exports T2CDPTranslator alongside T1AXTranslator"
    - "basicctrl/actions/channels/__init__.py — re-exports C5CDPInputChannel alongside C2AXPressChannel"
    - "tests/unit/translators/test_t2_cdp.py — replaced Wave-0 importorskip stub with 9 mocked-CDP unit tests"

key-decisions:
  - "T2 uses ``async with CDPClient(ws_url)`` and DOES NOT keep the connection open across resolve()→fire(). The CDPClient context closes when resolve() returns; C5 re-opens its own client at fire-time using the ws_url stashed in target.extras. This costs ~10ms per fire (localhost handshake) but eliminates cross-fire concurrency hazards in Wave 2 (multiple actions could otherwise share a single CDPClient and race on its socket). Phase 3+ may pool CDPClients per (pid, session_id) when cassette replay needs sub-10ms fire latency."
  - "validate() does NOT do a live DOM round-trip. A live ``DOM.querySelector(node_id)`` call would cost 10-15ms per validate; the orchestrator (Plan 02-10) calls validate() once per channel-fire-cycle, so the round-trip would dominate the race budget. Instead validate() checks that cdp_session_id + cdp_node_id are both populated (cheap struct check); the channel fails fast on dispatch if the session has gone away. This matches T1's choice (validate() does an AXRole probe, not a full re-walk)."
  - "Strict ``.slack.com`` filter (not ``slack.com``) — Slack's workspace renderer URLs are like ``https://app.slack.com/client/T123/D456``. The leading dot ensures we match the workspace subdomain redirect and skip bare slack.com placeholder pages. Documented in module docstring + tested by `test_pick_slack_returns_none_when_no_workspace`."
  - "C5 errors fast when ``target.extras['ws_url']`` is missing rather than re-discovering. Rationale: if a non-T2 translator's TranslatorTarget reaches C5 (orchestrator routing bug), the right behavior is loud failure (status='errored', error='no ws_url in target.extras') so the orchestrator falls through to the next channel. Silently re-discovering would mask routing bugs and add unbounded latency spikes."
  - "9 unit tests for C5 (Rule 2 deviation: matches Plan 02-05 deviation pattern) — the plan only specified a smoke import test as `<verify>`. CI without macOS apps would have zero coverage for C5's fire-path contract. Added the same 9-test shape as C2 covering name='C5', dispatch pair, idempotency_lost, cancel pre-syscall (no client constructed), errored on missing handles, errored on factory raise, bbox-center coords."
  - "TranslatorTarget.extras['ws_url'] (rather than a new typed field) — TranslatorTarget already has an `extras: dict[str, Any]` field for per-translator handles. Adding a typed `ws_url: Optional[str]` would force every other translator (T1/T3/T4/T5) to carry the field as None. extras['ws_url'] is documented in T2 module docstring + C5 docstring + tested via test_fire_errored_when_no_ws_url_in_extras."

patterns-established:
  - "Wave-2 plan shape continues from 02-05: replace Wave-0 importorskip stub with TDD RED → GREEN per task. Plans 02-07..02-09 (T3+C4, T4, T5+C1+C3) follow this exact shape."
  - "Cross-fire connection convention via extras['ws_url'] — when a translator opens a connection during resolve() but the channel fires AFTER the translator's context closes, the translator stashes the connection-rebuild handle in extras with a documented key. Plans 02-07 (T3 AS thread-pool handle) and 02-08 (T4 uitag detection cache) may follow if their surfaces need the same shape."
  - "Mocked-protocol unit test pattern — fake CDPClient with MagicMock-backed nested attribute tree. Reusable for any future async client wrapper (cdp-use, applescript wrappers, etc.)."

requirements-completed:
  - TRANS-02
  - ACT-01

# Threats mitigated
threats_mitigated:
  - "T-2-01 race ordering — C5.fire calls store.try_claim(action.id, 'C5') BEFORE the CDP Input.dispatchMouseEvent dispatch. Second fire on the same action_id returns ChannelOutcome(status='skipped', skipped_reason='idempotency_lost'). Verified by tests/unit/actions/channels/test_c5_cdp_input.py::test_fire_skipped_on_idempotency_lost."
  - "T-2-02 Slack workspace filter — T2._pick_workspace_target enforces strict `type='page' AND url contains '.slack.com'` filter (Pitfall D). GPU/utility helpers are skipped. When no workspace target matches, resolve() returns None (P8 mitigation surfaces — orchestrator falls through to T1/T4/T5). Verified by 5 _pick_workspace_target unit tests covering Slack/Cursor/Obsidian + default + miss paths."
  - "T-2-08 race-cancel correctness — C5.fire checks cancel_event.is_set() BEFORE constructing the CDPClient. When set, returns ChannelOutcome(status='cancelled') with NO socket open and NO Input.dispatchMouseEvent dispatched. The claim is held (action_id stays burned) so the orchestrator's race winner stays canonical. async with CDPClient(...) propagates cancellation to socket close on the way out. Verified by test_fire_cancelled_when_cancel_event_set (asserts last_instance is None when cancelled)."
  - "P8 mitigation (Electron CDP launch-only) — T2._discover_ws_url returns None when localhost:9222..9225 are all unreachable; T2._pick_workspace_target returns None when no workspace target matches the bundle filter. Both null paths cause T2.resolve() to return None, and the orchestrator falls through to T1/T4/T5. Plan 02-11's MCP healing tool reads AppProfile.cdp_available_after_relaunch (set by Plan 02-03 KNOWN_APPS) to prompt the user before this falls-through state. Verified by test_discover_ws_url_returns_none_on_all_ports_unreachable + test_pick_slack_returns_none_when_no_workspace."
  - "Pitfall B (cdp-use flatten=True mandatory) — T2.resolve passes `params={'targetId': ..., 'flatten': True}` to Target.attachToTarget. Without flatten, DOM calls hang silently waiting for a separate session-event pump. Verified by grep: `grep -c '\"flatten\": True' basicctrl/translators/t2_cdp.py` returns 1."
  - "D-03 hard rule (no sibling-tool import) — t2_cdp.py contains zero occurrences of the literal `browser_harness` substring. The unit test test_no_browser_harness_import grep-enforces this on every CI run. Required because basicCtrl coexists with the user's other CDP tooling on the same machine and neither owns the other."

# Metrics
duration: ~6min
completed: 2026-04-30
---

# Phase 2 Plan 06: T2 CDP Translator + C5 CDP Input.dispatchMouseEvent Channel Summary

**T2 CDP translator + C5 CDP Input.dispatchMouseEvent channel ship together as the canonical D-14 default tier-channel pair for Electron apps. T2 probes localhost:9222..9225 via httpx, attaches via cdp-use 1.4.5 with mandatory flatten=True (Pitfall B), filters Slack/Cursor/Obsidian workspace renderers (D-24 / Pitfall D), resolves elements via DOM.querySelector + DOM.getBoxModel; C5 dispatches mousePressed+mouseReleased pair at bbox center after atomic try_claim + cancel-event guard. The D-03 hard rule (no cross-tool import of the user's other CDP tooling) is grep-enforced by unit test.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-04-30T07:18:33Z
- **Completed:** 2026-04-30T07:24:00Z
- **Tasks:** 2 (both `type=auto tdd=true`)
- **Files created:** 3 (basicctrl/translators/t2_cdp.py, basicctrl/actions/channels/c5_cdp_input.py, tests/unit/actions/channels/test_c5_cdp_input.py)
- **Files modified:** 3 (basicctrl/translators/__init__.py, basicctrl/actions/channels/__init__.py, tests/unit/translators/test_t2_cdp.py — replaced Wave-0 stub)

## Task Commits

1. **Task 1 RED — failing T2CDPTranslator unit tests:** `e628995` (test) — 9 tests; ModuleNotFoundError on import.
2. **Task 1 GREEN — T2CDPTranslator implementation:** `27d5756` (feat) — 9/9 unit tests pass; full unit suite 190 passed (was 181).
3. **Task 2 RED — failing C5CDPInputChannel tests:** `1720229` (test) — 9 unit tests; ModuleNotFoundError on import.
4. **Task 2 GREEN — C5CDPInputChannel implementation:** `ac180d3` (feat) — 9/9 unit tests pass; full unit suite 199 passed.

## D-14 T2→C5 Default Binding Verified

Per CONTEXT.md D-14 the canonical Phase 2 default tier-channel mapping is:

| Tier | Channel | Method | Plan / Test |
|------|---------|--------|-------------|
| T1 (AX) | C2 (kAXPress) | `AXUIElementPerformAction(elem, "AXPress")` | 02-05 (shipped, Calculator integ) |
| **T2 (CDP)** | **C5 (Input.dispatchMouseEvent)** | `cdp.send.Input.dispatchMouseEvent(mousePressed/mouseReleased)` | **02-06 (this plan, mocked unit; Slack integ in 02-12)** |
| T3 (AS) | C4 (AppleScript) | (Plan 02-07) | (Plan 02-07) |
| T4 (Vision) | C1 (CGEvent public) | (Plans 02-08, 02-09) | (Plan 02-08) |
| T5 (Pixel) | C3 (CGEvent postToPid) | (Plan 02-09) | (Plan 02-09) |

This plan ships the SECOND default-binding pair end-to-end at the unit-test level. The remaining 3 pairs follow in 02-07..02-09; the Slack T2-wins live integration test lands in 02-12.

## T2 Resolution Flow

```
TargetSpec(css='[data-qa="message_container"]')
   ↓
T2.resolve(bundle_id, pid, target_spec)
   ↓
1. _discover_ws_url(pid):
     for port in (9222, 9223, 9224, 9225):
       httpx.AsyncClient(timeout=0.5).get(f"http://localhost:{port}/json/version")
       on 200 → return webSocketDebuggerUrl
     all fail → return None  ← P8 mitigation surfaces
   ↓ ws_url
2. async with CDPClient(ws_url) as cdp:
     targets = cdp.send.Target.getTargets()
   ↓ target_infos
3. _pick_workspace_target(target_infos, bundle_id):
     Slack:    type=page AND url contains ".slack.com"
     Cursor:   type=page AND url startswith "vscode-"
     Obsidian: type=page AND url contains "obsidian"
     default:  first type=page
     no match → return None  ← Pitfall D / D-24 enforced
   ↓ workspace target
4. cdp.send.Target.attachToTarget(targetId, flatten=True)  ← Pitfall B
   ↓ session_id
5. doc = cdp.send.DOM.getDocument(sessionId)
   node = cdp.send.DOM.querySelector(root_id, css, sessionId)
   if node.nodeId == 0: return None  ← selector miss
   ↓
6. box = cdp.send.DOM.getBoxModel(nodeId, sessionId)
   quad = box.model.content  # [x1,y1, x2,y2, x3,y3, x4,y4]
   cx, cy = (quad[0]+quad[4])/2, (quad[1]+quad[5])/2
   ↓
TranslatorTarget(
    element=UIElement(source=[Source.CDP], ...),
    cdp_node_id=node.nodeId,
    cdp_session_id=session_id,
    grounded_bbox=Bbox(cx-10, cy-10, 20, 20),
    extras={"ws_url": ws_url},  ← C5 reads this at fire-time
)
```

## C5 Fire Flow

```
C5.fire(action, target, store, cancel_event):
   ↓
1. claim = await store.try_claim(action.id, "C5")
   if claim is None: return ChannelOutcome(status="skipped", skipped_reason="idempotency_lost")
   ↓ T-2-01 race ordering: claim BEFORE socket open
2. if cancel_event.is_set(): return ChannelOutcome(status="cancelled")
   ↓ T-2-08 kill-switch: NO CDPClient constructed when cancelled (verified)
3. validate handles:
     target.cdp_session_id, target.grounded_bbox, target.extras["ws_url"], factory all present
     missing → ChannelOutcome(status="errored", error=<reason>)
   ↓
4. cx, cy = bbox.x + bbox.w/2, bbox.y + bbox.h/2  ← canonical bbox center
   ↓
5. async with cdp_client_factory(ws_url) as cdp:
     cdp.send.Input.dispatchMouseEvent(type="mousePressed",  x=cx, y=cy, button="left", clickCount=1, sessionId=...)
     cdp.send.Input.dispatchMouseEvent(type="mouseReleased", x=cx, y=cy, button="left", clickCount=1, sessionId=...)
   ↓ async-with closes socket on cancel propagation (T-2-08)
6. return ChannelOutcome(status="fired", fired_at_ns=time.monotonic_ns())
   ↓ exception path → ChannelOutcome(status="errored", error=str(exc))
```

## Files Created/Modified

### Created
- `basicctrl/translators/t2_cdp.py` (~245 lines) — T2CDPTranslator
  - tier='T2' Literal Protocol field
  - CDP_PROBE_PORTS = (9222, 9223, 9224, 9225)
  - `_discover_ws_url(pid)` — httpx 0.5s/port async probe
  - `_pick_workspace_target(target_infos, bundle_id)` — D-24 strict filter
  - `resolve(bundle_id, pid, target_spec)` — full attach + DOM.querySelector + getBoxModel flow with `flatten=True` (Pitfall B); returns TranslatorTarget with `extras={'ws_url': ws_url}` for C5
  - `validate(target)` — cheap struct check (no DOM round-trip)
- `basicctrl/actions/channels/c5_cdp_input.py` (~165 lines) — C5CDPInputChannel
  - name='C5' Literal Protocol field
  - `__init__(cdp_client_factory=None)` — lazy-imports `cdp_use.client.CDPClient`; tests inject fake factory
  - `fire(action, target, store, cancel_event)` — try_claim → cancel-check → handle-validate → CDPClient open → mousePressed + mouseReleased pair at bbox center
- `tests/unit/actions/channels/test_c5_cdp_input.py` (~205 lines) — 9 unit tests with fake CDPClient

### Modified
- `basicctrl/translators/__init__.py` — adds `T2CDPTranslator` export
- `basicctrl/actions/channels/__init__.py` — adds `C5CDPInputChannel` export
- `tests/unit/translators/test_t2_cdp.py` — replaced Wave-0 importorskip stub with 9 mocked-CDP tests

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Source code grep test caught `browser_harness` substring in module docstrings**
- **Found during:** Task 1 GREEN (first test run after implementation)
- **Issue:** Module docstring AND inline comments contained the literal substring `browser_harness` in prose contexts ("Do not import the browser_harness module") which the strict D-03 grep test correctly forbids — the test enforces ZERO occurrences of that substring anywhere in source, not just in import statements
- **Fix:** Rephrased docstring to refer to "the user's other CDP tooling" / "sibling-tool"; removed the literal `browser_harness` string from all comments. The test is preserved as-is (it's the spec).
- **Files modified:** `basicctrl/translators/t2_cdp.py`
- **Commit:** `27d5756` (rolled into the GREEN commit since the file hadn't been committed yet between the bug discovery and the fix)

**2. [Rule 1 - Bug] Test fixture used wrong SessionWriter kwarg `session_dir` (constructor takes `base`)**
- **Found during:** Task 2 GREEN first test run
- **Issue:** Initial test fixture wrote `SessionWriter(session_dir=tmp_path / "sess")` based on a guess; SessionWriter's actual init signature is `SessionWriter(base: Path)`
- **Fix:** Changed fixture to match the C2 test convention exactly: `IdempotencyTokenStore(SessionWriter(base=tmp_path))`
- **Files modified:** `tests/unit/actions/channels/test_c5_cdp_input.py`
- **Commit:** `ac180d3` (rolled into Task 2 GREEN)

**3. [Rule 1 - Bug] Test fixture constructed ActionCanonical with wrong field shape (used `pre=HoarePre(...)` — ActionCanonical doesn't have a `pre` field)**
- **Found during:** Task 2 GREEN second test run
- **Issue:** The `_fake_action()` helper used a `pre=HoarePre(...)` field that doesn't exist; ActionCanonical needs flat fields: id, step_idx, kind, target_key, action_type, payload, timestamp_ns, session_id (HoarePre is a separate model used by the verifier, not embedded in ActionCanonical)
- **Fix:** Mirrored Plan 02-05's `_fake_action()` shape from `tests/unit/actions/channels/test_c2_ax_press.py:45-55` exactly; removed unused `HoarePre` import
- **Files modified:** `tests/unit/actions/channels/test_c5_cdp_input.py`
- **Commit:** `ac180d3` (rolled into Task 2 GREEN)

**4. [Rule 2 - Missing critical functionality] Added 9 unit tests for C5 (plan specified only a smoke import test)**
- **Found during:** Task 2 planning
- **Issue:** Plan's `<verify>` was just a 1-liner import smoke test. CI without macOS apps would have zero coverage for C5's fire-path contract — the same gap C2 had in Plan 02-05 (which also added unit tests as a Rule 2 deviation)
- **Fix:** 9 unit tests with fake CDPClient factory: name='C5', dispatch pair, idempotency_lost, cancel pre-syscall (asserts no client constructed when cancelled), errored on no_session_id / no_grounded_bbox / no_ws_url, errored on factory raise, bbox-center coordinate math
- **Files modified:** `tests/unit/actions/channels/test_c5_cdp_input.py`
- **Commit:** `1720229` (RED) + `ac180d3` (GREEN — no impl changes for unit tests)

## Issues Encountered

- **Multiple PreToolUse:Edit hook re-prompts** — runtime asks the agent to re-read files between edits. All files had been read or written in this session; edits succeeded as confirmed by post-edit `pytest` and `grep` runs.
- **No real Slack integration test in this plan** — the plan's success criteria explicitly note "If real Slack/Discord not available for integration tests, mark with @pytest.mark.manual and skip-with-reason." The Slack T2-wins live integration test is the responsibility of Plan 02-12 (per Phase 2 wave structure: 02-06 ships unit-tested T2+C5; 02-12 integrates against a real relaunched Slack with manual UAT). No `@pytest.mark.manual` test added in this plan because none was authored — Plan 02-12 owns that surface.

## User Setup Required

None for unit tests — they run on any host with `cdp-use==1.4.5` (already in `pyproject.toml`).

For Plan 02-12's eventual Slack integration test, the user will need to manually relaunch Slack with `pkill -9 Slack; sleep 1; open -a "Slack" --args --remote-debugging-port=9222` (D-25 manual UAT path; classifier flag `cdp_after_relaunch=True` from KNOWN_APPS surfaces this prompt via Plan 02-11's healing tool, never silent).

## Next Plan Readiness

- **Plan 02-07 (T3 AppleScript + C4 AppleScript channel):** can `from basicctrl.translators.base import Translator, TranslatorTarget, TargetSpec` + `from basicctrl.actions.channels.base import Channel, ChannelOutcome` and follow the same TDD RED→GREEN shape as 02-05 (T1+C2) and 02-06 (T2+C5). Will use `py-applescript==1.0.3` on a dedicated `concurrent.futures.ThreadPoolExecutor(max_workers=2)` per CONTEXT.md D-04. Pages.app is the integration target (D-26).
- **Plan 02-08 (T4 Vision):** uitag pipeline → grounded_bbox; binds to C1 by default. Will need `await asyncio.to_thread(run_pipeline, ...)` per RESEARCH Pitfall C (uitag is sync — blocks event loop).
- **Plan 02-09 (T5 Pixel + C1 + C3):** CGWindowList screen reads + ImageHash dHash + CGEvent.postToPid wiring.
- **Plan 02-10 (race orchestrator):** wires `TranslatorRegistry.select_for_priority(profile.translator_priority)` against `ChannelRegistry.select(priority, race_policy)` with `IdempotencyTokenStore` + `cancel_event` per the contract this plan exercises end-to-end alongside 02-05. T1+C2 AND T2+C5 are the first two real pairs the orchestrator can race.
- **Plan 02-12 (Slack T2-wins integration test):** real CDP attach + race verification; depends on Plan 02-10 (race orchestrator) and the user's manually relaunched Slack.
- **No blockers.** All 18 unit tests pass (9 T2 + 9 C5). Full unit suite 199 passed.

## Self-Check: PASSED

Files created (verified via `[ -f path ]`):
- FOUND: `basicctrl/translators/t2_cdp.py`
- FOUND: `basicctrl/actions/channels/c5_cdp_input.py`
- FOUND: `tests/unit/actions/channels/test_c5_cdp_input.py`

Files modified (verified):
- FOUND: `basicctrl/translators/__init__.py` (re-exports T2CDPTranslator)
- FOUND: `basicctrl/actions/channels/__init__.py` (re-exports C5CDPInputChannel)
- FOUND: `tests/unit/translators/test_t2_cdp.py` (replaced Wave-0 stub)

Commits verified (all in `git log --oneline`):
- FOUND: `e628995` test(02-06): RED T2CDPTranslator
- FOUND: `27d5756` feat(02-06): GREEN T2CDPTranslator
- FOUND: `1720229` test(02-06): RED C5CDPInputChannel
- FOUND: `ac180d3` feat(02-06): GREEN C5CDPInputChannel

Acceptance criteria literals (all greppable, verified):
- FOUND: `class T2CDPTranslator`, `from cdp_use.client import CDPClient`, `"flatten": True`, `.slack.com`, `vscode-`, `obsidian` in `basicctrl/translators/t2_cdp.py`
- VERIFIED: `grep -c 'browser_harness' basicctrl/translators/t2_cdp.py` returns 0 (D-03 hard rule)
- FOUND: `T2CDPTranslator` in `basicctrl/translators/__init__.py`
- FOUND: `class C5CDPInputChannel`, `name: Literal["C1", "C2", "C3", "C4", "C5"] = "C5"`, `try_claim(action.id, "C5")`, `cancel_event.is_set()`, `mousePressed`, `mouseReleased`, `Input.dispatchMouseEvent` in `basicctrl/actions/channels/c5_cdp_input.py`
- FOUND: `extras={"ws_url": ws_url}` in `basicctrl/translators/t2_cdp.py`
- FOUND: `C5CDPInputChannel` in `basicctrl/actions/channels/__init__.py`

Verification commands (all pass):
- `uv run pytest -q tests/unit/translators/test_t2_cdp.py` → 9 passed in 0.07s
- `uv run pytest -q tests/unit/actions/channels/test_c5_cdp_input.py` → 9 passed in 0.09s
- `grep -c "browser_harness" basicctrl/translators/t2_cdp.py` → 0
- `uv run python -c "from basicctrl.translators import T2CDPTranslator; from basicctrl.actions.channels import C5CDPInputChannel; print('ok')"` → `ok`
- `SKIP_INTEGRATION=1 uv run pytest -q tests/ -m "not integration and not manual"` → 199 passed, 10 skipped, 29 deselected in 1.06s (was 181 after 02-05; +18 from this plan's 9 T2 + 9 C5 unit tests)

---
*Phase: 02-translators-racing*
*Completed: 2026-04-30*
