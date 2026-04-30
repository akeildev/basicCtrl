# Phase 2: Translators + Racing — Research

**Researched:** 2026-04-30
**Domain:** 5 protocol translators (T1-T5) + 5 racing action channels (C1-C5) + atomic idempotency + per-action-class race policy + AppleScript stagger + top-12 app map + MCP surface extension
**Confidence:** HIGH (CONTEXT.md locked 31 decisions via 4-sub-agent fan-out; this research fills concrete implementation patterns, no alternatives re-litigated)

## Summary

Phase 2 ships the **execution layer**: translators resolve targets, channels deliver events, race orchestrator picks winners, idempotency tokens prevent double-fires. All decisions of substance are already locked in CONTEXT.md (D-01..D-31). This research's job is **implementation patterns** — exact API shapes, race-cancel semantics, edge cases, and Validation Architecture for Nyquist Dimension 8.

**Three central facts shape every plan:**

1. **anyio task groups need an explicit cancel-scope race wrapper** — anyio 4.13 has no built-in `FIRST_COMPLETED`. Pattern: spawn N tasks via `tg.start_soon`, each task writes its result to a shared dict + sets an `anyio.Event`; first writer triggers `tg.cancel_scope.cancel()`. Channel coroutines must `with anyio.CancelScope(shield=False)` their fire path so cancellation is delivered cleanly. CGEvent.postToPid + AppleEvent at C4 have a ~50µs uncancellable kernel-side window; idempotency token + `cancel_event.is_set()` check immediately before the syscall is the only mitigation.
2. **The verifier (Phase 1) decides race winners; channels are the muscle.** Phase 1's `Aggregator.verify` returning `confidence ≥ 0.5` is the race-end signal. Channels emit a `ChannelOutcome` (success/error/cancelled) but the orchestrator does NOT trust the channel's own success bit — it trusts the verifier. This is the core counter-double-click guarantee: even if both C2 and C5 "succeed" at the OS level, the verifier saw exactly one state delta and the second post is dropped at the idempotency receipt ring buffer (D-19).
3. **Top-12 short-circuits the classifier** — D-20 says known apps skip live capability probe. The bundled map at `cua_overlay/profile/known_apps.py` gives translator priority directly; capability probe runs only on cache miss. Cache invalidation happens automatically via Phase 1's `should_invalidate_cache` (`bundle_version`/`bundle_build` mismatch with the live `Info.plist`) — the bundled map participates by exposing a `min_known_version` field; if the live version is newer than the bundled-known one, fall through to live probe.

**Primary recommendation:** Build **Wave 0** (test fixtures: Slack relaunch helper, Pages AS bootstrap, Chess.app launcher, registry stubs). Then **Wave 1** in parallel: `actions/idempotency.py`, `actions/channel_registry.py`, `translators/registry.py`, `profile/known_apps.py`. Then **Wave 2 sequentially per channel** with C2 first (already wrapped Phase 1's AX), C5 second (CDP — biggest risk surface), C4 third (AS — needs ThreadPoolExecutor wiring), C3/C1 last (pixel paths). Then **Wave 3** the race orchestrator. Then **Wave 4** MCP tool surface. Slack/Pages/Chess integration tests in **Wave 5**.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Translator Stack (T1-T5)**
- **D-01:** T1 AX wraps Phase 1's `cua_overlay.ax.*` (TokenBucket, walker, observer, modal probe). In-process Python via PyObjC HIServices, no Swift IPC.
- **D-02:** T2 CDP takes `cdp-use==1.4.5` as a direct project dependency.
- **D-03:** T2 CDP does NOT vendor or runtime-import browser-harness. Both call cdp-use directly; cua-maximalist must coexist with browser-harness.
- **D-04:** T3 AppleScript uses `py-applescript==1.0.3` on a dedicated `concurrent.futures.ThreadPoolExecutor(max_workers=2)`. Never `osascript` subprocess.
- **D-05:** T4 Vision ships `uitag==0.6.0` + `ocrmac==1.0.1`. uitag's `from uitag import run_pipeline` returns `(PipelineResult, annotated_image, manifest_json)`. Detection → UIElement adapter is direct.
- **D-06:** T4 does NOT include MacPaw/Screen2AX in Phase 2.
- **D-07:** T5 Pixel uses CGWindowList + pyobjc-framework-Quartz + ImageHash dHash (already in Phase 1). Element coords delegate to T4's uitag pipeline.
- **D-08:** Pin `transformers>=5.0.0` for Phase 2 (uitag's load-bearing dep). Phase 4 may install side-by-side via uv extras if 4.x needed.

**Race Orchestrator + Channels (C1-C5)**
- **D-09:** Race policy is per-action-class, encoded on `ActionCanonical.action_type` and validated by a Pydantic enum + module-level dispatch table. The `Literal["READ","MUTATE"]` Phase-1 kind field stays orthogonal; Phase 2 adds a separate `RacePolicy` enum at the orchestrator level.
- **D-10:** RACE allowlist: `click_button`, `click`, `focus`, `scroll_to_position` (absolute), `hover`.
- **D-11:** SINGLE-CHANNEL allowlist: `submit`, `send`, `delete`, `confirm`, `type_into_focused`, `set_value`, `drag_and_drop`, `scroll_by_delta`, `key_combo_destructive` (cmd+s, cmd+enter, cmd+w, cmd+z).
- **D-12:** SAFE-RACE key combos: `cmd+c`, `cmd+v`.
- **D-13:** Race orchestrator is `anyio.create_task_group` with FIRST_COMPLETED-equivalent semantics (custom wrapper — see §"anyio Race Pattern" below).
- **D-14:** Channel-translator binding is soft: T1→C2 default, T2→C5 default, T3→C4 default, T4→C1 default, T5→C3 default. Translators can request alternate channels.
- **D-15:** AppleScript stagger window = **500ms default, tunable per-recipe** via optional `as_class: "fast" | "slow"` field. "fast"=0ms, "slow"=500ms.

**Idempotency**
- **D-16:** Tokens stored in process-local `dict[token_id, ChannelClaim]` guarded by `asyncio.Lock` + written to SessionWriter NDJSON trace. Dict authoritative for live race; NDJSON for replay.
- **D-17:** Token written **BEFORE** any channel fires. Channels read the dict at start of fire path; if `claimed=true`, return `Cancelled` immediately. Format: `{action_id, claimed_at_ns, claimed_by_channel}`.
- **D-18:** OS-level kill-switch — for C1/C3, each channel's coroutine checks `cancel_event.is_set()` immediately before the syscall. ~50µs window remains. C4 AppleEvent uncancellable mid-flight; AS stagger pushes it past most race windows.
- **D-19:** Idempotency receipts — verifier records `(target_axid, action_kind, ts)` in 2-second ring buffer. Second post on same target+kind within 2s = `near_miss_duplicate` log + dropped at verifier.

**App Classifier + Top-12**
- **D-20:** Phase 1's classifier extended with bundled top-12 association map at `cua_overlay/profile/known_apps.py`. Map consulted BEFORE running capability probes.
- **D-21:** Top-12 verified bundleIDs (Calculator, Pages, Numbers, Keynote, Mail, Calendar, Notes, Reminders, Safari, Slack, Cursor, Obsidian).
- **D-22:** Bonus map entries: System Settings, Terminal, Music, Chrome, Chess.
- **D-23:** Discord, Notion, Linear NOT in bundled map — fall through to live probe.
- **D-24:** P8 mitigation — classifier surfaces `cdp_available_after_relaunch=true` for Slack/Cursor/Obsidian. Phase 2 healing tool prompts user once with one-time relaunch dialog, never silent. Slack renderer is multi-process; CDP attach must filter for workspace renderer page (type=page AND url~/\.slack\.com/).

**Test Surface (3 success-criteria race winners)**
- **D-25:** **T2 CDP wins** test — Slack manually relaunched. Test target: `[data-qa="message_container"]`.
- **D-26:** **T3 AppleScript wins** test — Pages 14. Test verb: `make new paragraph style with properties {name:"BoldTest", font name:"Helvetica", font size:14, bold:true}`.
- **D-27:** **T4 SoM + T5 CGEvent fires** test — Apple Chess.app. Click e2 → screenshot dHash → click e4 → confirm pawn moved.

**MCP Surface Evolution**
- **D-28:** Option (a) — extend `click_with_healing` and add domain-named sibling tools. Reject polymorphic `act(ActionCanonical)`.
- **D-29:** Phase 2 MCP tool list (5 new + 1 extended = 6 total new): `click_with_healing` (extended), `type_with_healing`, `scroll_with_healing`, `set_value_with_healing`, `send_destructive`, `key_combo_with_healing`.
- **D-30:** `race_policy` parameter values: `"auto"` (DEFAULT), `"race"` (force, caller-acknowledged risk), `"single_channel"` (force).
- **D-31:** Total MCP tool count after Phase 2: ~10. Well under RAG-MCP ~30 sweet-spot.

### Claude's Discretion

- Internal module structure under `cua_overlay/translators/<t>` and `cua_overlay/actions/channels/<c>` — follow Phase 1's per-feature sub-package pattern.
- Race orchestrator's exact cancellation propagation order (anyio details).
- pytest fixture composition for the 3 test apps (Slack relaunch helper, Pages AS bootstrap, Chess.app launcher).
- Exact `RacePolicy` enum field names and Pydantic v2 validator wiring.
- Telemetry — counter names for race wins per (tier, channel, bundle_id).
- Logging schema for `near_miss_duplicate` + `cdp_relaunch_offered` events.

### Deferred Ideas (OUT OF SCOPE)

- **MacPaw/Screen2AX synthetic AX tree** — Phase 3 spike if uitag empirically insufficient.
- **DYLD inject CDP into already-running Electron renderers** — Phase 6 SPI-06.
- **Swift SkyLight bridge for true `SLEventPostToPid`** — Phase 6 SPI-01.
- **Drag stream first-class API** — Phase 4 alongside speculative pre-execution.
- **Per-app DYLD-equivalent for Tauri/Wails** — Phase 6 SPI work.
- **Multi-renderer Slack CDP attach** — Phase 4 cassette-replay concern.
- **Linear / Discord / Notion bundleID verification** — first probe writes the cache.
- **`transformers 4.x` side-by-side install for mlx-vlm 0.4.4** — Phase 4.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description (from REQUIREMENTS.md) | Research Support |
|----|------------------------------------|------------------|
| TRANS-01 | T1 AX SPI translator — AXUIElement + private `_AXUIElementGetWindow` + `_AXObserverAddNotificationAndCheckRemote` | Phase 1 `cua_overlay/ax/*` already provides safety stack; T1 wraps it. Private SPI deferred Phase 6 — D-01 says T1 is in-process PyObjC, no Swift IPC; private SPI calls (`_AXUIElementGetWindow`) accessed via `objc.loadBundle` + `objc.parseBridgeSupport` on demand. See §"T1 AX Implementation Pattern". |
| TRANS-02 | T2 CDP translator — auto-relaunch Electron with `--remote-debugging-port`, attach via WebSocket | cdp-use 1.4.5 verified PyPI 2026-02-22. Direct dep per D-02. P8 mitigation: classifier flag + one-time user prompt per D-24, never silent. See §"T2 CDP Implementation Pattern". |
| TRANS-03 | T3 AppleScript translator — NSAppleScript in-process via py-applescript, ScriptingBridge typed access for .sdef apps | py-applescript 1.0.3 verified PyPI 2022-01-23 (API frozen). Dedicated `ThreadPoolExecutor(max_workers=2)` per D-04. ScriptingBridge typed access deferred — Phase 2 uses raw NSAppleScript string compile only (simpler, covers Pages D-26 verb). See §"T3 AppleScript Implementation Pattern". |
| TRANS-04 | T4 Vision/Screen2AX translator — Vision OCR (ocrmac) + uitag SoM (Apple Vision + YOLO11 MLX) | uitag 0.6.0 verified PyPI 2026-04-09. Screen2AX deferred per D-06. uitag returns `(PipelineResult, PIL.Image, manifest_json)` 3-tuple; Detection→UIElement adapter direct. See §"T4 Vision Implementation Pattern". |
| TRANS-05 | T5 Pixel translator — CGEvent + SkyLight `SLEventPostToPid` (background, no cursor warp) | True `SLEventPostToPid` deferred Phase 6 SPI-01 per D-07. Phase 2 uses public `Quartz.CGEventPostToPid` as C1 implementation; signature stays stable across the swap. dHash via ImageHash 4.3.2 (already Phase 1 dep). See §"T5 Pixel Implementation Pattern". |
| ACT-01 | Action channel registry — C1 SLEventPostToPid, C2 AX kAXPress, C3 CGEvent.postToPid, C4 AppleScript, C5 CDP Input.dispatch | Channel registry at `cua_overlay/actions/channel_registry.py` per D-14. Each channel is an awaitable `(ActionCanonical, IdempotencyTokenStore, CancelEvent) -> ChannelOutcome`. See §"Channel Registry Shape". |
| ACT-02 | Race orchestrator — `asyncio.wait(FIRST_COMPLETED)` across channels, cancel losers when first verifier passes | anyio task group with custom FIRST_COMPLETED wrapper per D-13. Verifier passes is the race-end signal, NOT channel success. See §"anyio Race Pattern". |
| ACT-03 | Atomic idempotency tokens — written to shared state before fire, channels skip if claimed | Process-local `dict[token_id, ChannelClaim]` + `asyncio.Lock` per D-16/D-17. ActionCanonical.id (UUID) is the token. See §"Idempotency Implementation". |
| ACT-04 | Action interference mitigations — staggered_race for AppleScript, AX rate-limit (cmux #2985 fix, 20 calls/sec/pid token bucket), pre-action AX validity check, per-action-class race policy | TokenBucket already Phase 1. AS stagger 500ms default per D-15. AX validity pre-check (P28) — every translator calls `AXUIElementCopyAttributeValue(role)` before fire. RacePolicy enum + dispatch table per D-09. |

</phase_requirements>

## Standard Stack

### Core (Phase 2 additions)

| Library | Version | Purpose | Why Standard | Verification |
|---------|---------|---------|--------------|--------------|
| **cdp-use** | 1.4.5 | T2 CDP client (typed CDP wrapper + raw send) | Same upstream as browser-harness; MIT; type-hinted via TypedDict | [VERIFIED: PyPI 2026-02-22, `requires httpx>=0.28.1, typing-extensions>=4.12.2, websockets>=15.0.1`] |
| **uitag** | 0.6.0 | T4 SoM grounder (Apple Vision + YOLO11 MLX, on-device) | 90.8% ScreenSpot-Pro; bundled 18 MB YOLO weights; pure-Python API | [VERIFIED: PyPI 2026-04-09, summary "UI element detection for macOS — Apple Vision + fine-tuned YOLO, on-device, ~1-5s"] |
| **py-applescript** | 1.0.3 | T3 AppleScript via in-process NSAppleScript | API frozen since 2022 (NSAppleScript itself frozen since 10.7); pyobjc transitive; in-process | [VERIFIED: PyPI 2022-01-23] [CITED: github.com/rdhyee/py-applescript — "easy-to-use Python wrapper for NSAppleScript"] |
| **transformers** | ≥5.0.0 | uitag transitive | uitag pyproject pin per D-08 | [ASSUMED — verify at install time uv resolves cleanly with mlx-vlm 0.4.4] |

### Already Phase 1 deps (reused, no version bumps)

| Library | Phase 1 Use | Phase 2 Reuse |
|---------|-------------|---------------|
| pyobjc 12.1 | Vision, AX, AppKit | Quartz CGEventPostToPid (C1/C3); CGWindowList (T5); HIServices (T1) |
| anyio ≥4.0 | Phase 1 capability probe parallel tasks | Race orchestrator task group |
| ImageHash 4.3.2 | L1 cheap dHash | T5 pixel ROI hashing for verify after CGEvent fire |
| ocrmac 1.0.1 | L2 medium OCR | T4 fallback when uitag returns no detections (e.g., 3D Metal Chess board) |
| structlog 25.5.0 | NDJSON action log | New event types: `idempotency_claim`, `race_winner`, `race_loser`, `near_miss_duplicate`, `cdp_relaunch_offered`, `as_stagger_fired` |
| pydantic ≥2.0 | All schemas | RacePolicy enum, ChannelOutcome, IdempotencyToken |

### Installation diff vs Phase 1's pyproject.toml

```toml
# Add to [project].dependencies:
"cdp-use==1.4.5",
"uitag==0.6.0",
"py-applescript==1.0.3",
"transformers>=5.0.0",  # uitag transitive — pin explicit so uv lockfile records it
```

**Version verification commands** (run at Wave 0):
```bash
uv add cdp-use==1.4.5
uv add uitag==0.6.0
uv add py-applescript==1.0.3
uv add 'transformers>=5.0.0'
# Verify nothing in mlx-vlm path breaks (Phase 4 dep, not yet pinned)
uv tree | grep transformers
```

### Alternatives Considered

| Instead of | Could Use | Why Not in Phase 2 |
|------------|-----------|--------------------|
| cdp-use direct | vendor browser-harness | D-03 — browser-harness has no package layout (flat scripts), uses `/tmp/bu-{NAME}.sock` IPC; cua-maximalist must coexist with it daily |
| uitag | Screen2AX (MacPaw) | D-06 — Screen2AX not on PyPI, pinned to pyobjc 10.3.1 (incompatible with our 12.1), heavy deps |
| py-applescript ThreadPoolExecutor | `asyncio.to_thread()` | Either works; ThreadPoolExecutor with max_workers=2 explicit per D-04. `asyncio.to_thread` uses default thread pool which is 32 workers — too many for the staggered AS path |
| Public `Quartz.CGEventPostToPid` (C1) | True SkyLight `SLEventPostToPid` | D-07 — Phase 6 SPI-01. Public C1 has visible cursor warp risk; SkyLight is no-op upgrade later. Phase 2 channel signature stable across the swap |

## Architecture Patterns

### Recommended Project Structure (Phase 2 additions)

```
cua_overlay/
├── translators/                      # NEW — Phase 2
│   ├── __init__.py                   # registry re-exports
│   ├── registry.py                   # dict[tier_name, Translator] + select()
│   ├── base.py                       # Translator protocol / ABC
│   ├── t1_ax.py                      # wraps Phase 1 cua_overlay.ax.*
│   ├── t2_cdp.py                     # cdp-use client + Slack workspace filter
│   ├── t3_applescript.py             # py-applescript ThreadPoolExecutor
│   ├── t4_vision.py                  # uitag run_pipeline + ocrmac fallback
│   └── t5_pixel.py                   # CGWindowList + dHash; delegates coords to T4
├── actions/                           # NEW — Phase 2
│   ├── __init__.py
│   ├── channel_registry.py           # dict[channel_name, Channel] + select()
│   ├── race_orchestrator.py          # anyio FIRST_COMPLETED wrapper
│   ├── race_policy.py                # RacePolicy enum + dispatch table (D-09..D-12)
│   ├── idempotency.py                # IdempotencyTokenStore + ChannelClaim Pydantic
│   ├── channels/
│   │   ├── __init__.py
│   │   ├── base.py                   # Channel protocol / ABC + ChannelOutcome
│   │   ├── c1_skylight.py            # public Quartz.CGEventPostToPid (Phase 6 swap)
│   │   ├── c2_ax_press.py            # AX kAXPress via PyObjC HIServices
│   │   ├── c3_cgevent.py             # CGEvent.postToPid (with cursor)
│   │   ├── c4_applescript.py         # py-applescript "tell app X" + AS stagger
│   │   └── c5_cdp_input.py           # cdp-use Input.dispatchMouseEvent
│   └── duplicate_receipt.py          # 2s ring buffer for D-19
├── profile/
│   ├── known_apps.py                 # NEW — bundled top-12 map (D-20..D-22)
│   └── classifier.py                 # MODIFIED — consult known_apps before probe
├── mcp_server/
│   └── healing_tools.py              # MODIFIED — D-29 5 new tools + click extension
└── persist/
    └── session_writer.py             # MODIFIED — new event types per D-16/D-19/D-24
```

### Pattern 1: Translator Protocol (T1-T5 base)

**What:** Each translator exposes the same async interface — resolve a target by spec, return `(UIElement, ax_element_opaque)`. Channel selection is orthogonal.

**When to use:** Every translator import must conform.

```python
# cua_overlay/translators/base.py
from typing import Protocol
from cua_overlay.state.graph import UIElement

class TranslatorTarget(Protocol):
    """Resolved target ready for a channel to fire on."""
    element: UIElement              # canonical state-graph entity
    ax_element: Any | None          # AXUIElementRef opaque (T1 only)
    cdp_node_id: int | None         # CDP DOM.NodeId (T2 only)
    cdp_session_id: str | None      # CDP Target session (T2 only)
    as_target_spec: str | None      # AppleScript address spec (T3 only)
    grounded_bbox: Bbox | None      # uitag-resolved bbox (T4/T5 only)

class Translator(Protocol):
    tier: Literal["T1", "T2", "T3", "T4", "T5"]

    async def resolve(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,  # {x,y,label,role,aria_label,...}
    ) -> TranslatorTarget | None:
        """Resolve the target. None if this translator can't address it."""
        ...

    async def validate(self, target: TranslatorTarget) -> bool:
        """Pre-action AX validity check (P28 mitigation, ACT-04)."""
        ...
```

### Pattern 2: anyio Race Pattern (D-13)

**What:** Spawn N channel tasks, await first verifier signal, cancel losers. anyio 4.13 has no `FIRST_COMPLETED`; we build it.

**When to use:** Race orchestrator entry point — every action with `RacePolicy.RACE`.

```python
# cua_overlay/actions/race_orchestrator.py
import anyio
from anyio import create_task_group, Event, CancelScope

async def race_first_complete(
    *coros,           # list[Awaitable[ChannelOutcome]]
    on_first_winner,  # async callback when first task completes
) -> tuple[int, ChannelOutcome, list[ChannelOutcome | Exception]]:
    """Race coroutines, return (winner_idx, winner_outcome, all_outcomes).

    All other tasks are cancelled cooperatively via tg.cancel_scope.cancel().
    Losers see asyncio.CancelledError inside their coroutine and clean up.
    """
    results: list[ChannelOutcome | Exception | None] = [None] * len(coros)
    winner: list[int | None] = [None]  # box for nonlocal mutation

    async def _runner(idx: int, coro):
        try:
            with CancelScope(shield=False) as scope:
                outcome = await coro
                results[idx] = outcome
                if winner[0] is None and outcome.verified:
                    winner[0] = idx
                    await on_first_winner(idx, outcome)
                    tg.cancel_scope.cancel()
        except anyio.get_cancelled_exc_class():
            results[idx] = ChannelOutcome.cancelled(idx)
            raise
        except Exception as e:
            results[idx] = e

    async with create_task_group() as tg:
        for idx, coro in enumerate(coros):
            tg.start_soon(_runner, idx, coro)

    if winner[0] is None:
        return (-1, ChannelOutcome.no_winner(), results)
    return (winner[0], results[winner[0]], results)
```

**Critical detail:** `CancelScope(shield=False)` lets cancellation propagate from `tg.cancel_scope.cancel()` INTO the channel coroutine. If channels need a brief shielded section (e.g., to write the idempotency token), wrap that ONE block in `CancelScope(shield=True)` — never the whole channel body.

[CITED: anyio.readthedocs.io/en/stable/cancellation.html — "Cancelling a cancel scope cancels all cancel scopes nested within it"; tg.cancel_scope.cancel() is the documented termination mechanism]

### Pattern 3: Atomic Idempotency Token (D-16, D-17)

**What:** Process-local dict + asyncio.Lock + NDJSON sink. Token written before any channel fires; channels read at start of fire path.

```python
# cua_overlay/actions/idempotency.py
import asyncio
import time
from typing import Literal
from pydantic import BaseModel, ConfigDict

class ChannelClaim(BaseModel):
    model_config = ConfigDict(frozen=True)
    action_id: str            # UUID = ActionCanonical.id
    claimed_at_ns: int        # monotonic
    claimed_by_channel: Literal["C1","C2","C3","C4","C5"]

class IdempotencyTokenStore:
    """Process-local atomic claim store + NDJSON trace.

    Authority hierarchy:
        1. self._claims dict — live race authority
        2. session.action_log.ndjson — replay/forensics

    Claim semantics:
        - try_claim returns True if the action_id is fresh (not yet claimed)
          AND records the claim atomically. Returns False if already claimed.
    """

    def __init__(self, session_writer):
        self._claims: dict[str, ChannelClaim] = {}
        self._lock = asyncio.Lock()
        self._session = session_writer

    async def try_claim(
        self, action_id: str, channel: str
    ) -> ChannelClaim | None:
        """Atomic claim. Returns the winning ChannelClaim or None if lost."""
        async with self._lock:
            existing = self._claims.get(action_id)
            if existing is not None:
                return None  # lost the race
            claim = ChannelClaim(
                action_id=action_id,
                claimed_at_ns=time.monotonic_ns(),
                claimed_by_channel=channel,
            )
            self._claims[action_id] = claim
            self._session.append_action_log({
                "event": "idempotency_claim",
                "action_id": action_id,
                "channel": channel,
                "claimed_at_ns": claim.claimed_at_ns,
            })
            return claim

    def is_claimed(self, action_id: str) -> ChannelClaim | None:
        """Lock-free peek. Channels call this immediately before syscall
        to get the ~50µs OS-level kill-switch (D-18)."""
        return self._claims.get(action_id)
```

**Channel fire path** (every channel):
```python
async def fire(action, store, cancel_event):
    # 1. Try to claim. If lost, skip.
    claim = await store.try_claim(action.id, channel="C2")
    if claim is None:
        return ChannelOutcome.skipped("idempotency_lost")

    # 2. Pre-syscall kill-switch (D-18). ~50µs window remains but shrinks.
    if cancel_event.is_set():
        return ChannelOutcome.cancelled()

    # 3. Fire (the part with the ~50µs uncancellable window for C1/C3).
    await _do_syscall(action)
    return ChannelOutcome.fired(channel="C2", at_ns=time.monotonic_ns())
```

### Pattern 4: T1 AX Implementation (TRANS-01)

**What:** T1 wraps Phase 1's safety stack. Resolve target via locator hierarchy → walker subtree (depth-3 limit) → AX validity check → return `TranslatorTarget` with `ax_element` set. Action delivery via C2 (AX kAXPress) is the default channel binding (D-14).

```python
# cua_overlay/translators/t1_ax.py
class T1AXTranslator:
    tier = "T1"

    def __init__(self, walker, observer_manager, rate_limiter):
        self._walker = walker          # cua_overlay.ax.walker.walk_subtree
        self._mgr = observer_manager   # cua_overlay.verifier.axobserver.AXObserverManager
        self._bucket = rate_limiter    # cua_overlay.ax.rate_limit.TokenBucket

    async def resolve(self, bundle_id, pid, target_spec):
        # 1. Get app AXUIElement (cached per-pid).
        ax_app = await self._get_app_element(pid)
        # 2. Walk depth-limited subtree to find candidate.
        result = await self._walker(ax_app, pid, bundle_id, max_depth=3)
        # 3. Match by AXIdentifier > AXLabel > role+bbox-centroid (10-tier locator).
        match = self._match_locator(result.nodes, target_spec)
        if match is None:
            return None
        # 4. Pre-action validity probe (P28).
        if not await self.validate(match):
            return None
        return TranslatorTarget(element=match.elem, ax_element=match.ax_ref)

    async def validate(self, target):
        """AX validity check — guards against kAXErrorInvalidUIElement on stale
        refs after re-render. Costs 1 bucket token; one Mach roundtrip ~2ms."""
        if not await self._bucket.acquire(target.element.pid):
            return False  # rate-limited; fail-open lets caller retry via cache
        try:
            from HIServices import AXUIElementCopyAttributeValue
            err, _ = AXUIElementCopyAttributeValue(target.ax_element, "AXRole", None)
            return err == 0
        except Exception:
            return False
```

### Pattern 5: T2 CDP Implementation (TRANS-02)

**What:** Detect CDP port via `localhost:9222/json/version`, attach via cdp-use, filter targets, resolve element via DOM.querySelector, return target ready for C5 fire.

```python
# cua_overlay/translators/t2_cdp.py
import httpx
from cdp_use.client import CDPClient

CDP_PORTS = (9222, 9223, 9224, 9225)

class T2CDPTranslator:
    tier = "T2"

    async def _discover_ws_url(self, pid: int) -> str | None:
        """Probe localhost:9222..9225 for /json/version → ws URL."""
        for port in CDP_PORTS:
            try:
                async with httpx.AsyncClient(timeout=0.5) as client:
                    r = await client.get(f"http://localhost:{port}/json/version")
                    if r.status_code == 200:
                        return r.json()["webSocketDebuggerUrl"]
            except Exception:
                continue
        return None

    async def resolve(self, bundle_id, pid, target_spec):
        ws = await self._discover_ws_url(pid)
        if ws is None:
            return None  # P8: not relaunched yet; classifier flags this

        async with CDPClient(ws) as cdp:
            # 1. Filter Target.getTargets for workspace renderer (D-24).
            targets = await cdp.send.Target.getTargets()
            workspace = self._pick_workspace_target(
                targets["targetInfos"],
                bundle_id=bundle_id,
            )
            if workspace is None:
                return None

            # 2. Attach to that target's session.
            attach = await cdp.send.Target.attachToTarget(
                params={"targetId": workspace["targetId"], "flatten": True}
            )
            session_id = attach["sessionId"]

            # 3. Resolve element. Slack: target_spec.css = '[data-qa="message_container"]'.
            doc = await cdp.send.DOM.getDocument(sessionId=session_id)
            node_search = await cdp.send.DOM.querySelector(
                params={"nodeId": doc["root"]["nodeId"], "selector": target_spec.css},
                sessionId=session_id,
            )
            if node_search.get("nodeId", 0) == 0:
                return None

            # 4. Get element box.
            box = await cdp.send.DOM.getBoxModel(
                params={"nodeId": node_search["nodeId"]},
                sessionId=session_id,
            )
            # CDP returns content quad as [x1,y1, x2,y2, x3,y3, x4,y4].
            quad = box["model"]["content"]
            cx = (quad[0] + quad[4]) / 2
            cy = (quad[1] + quad[5]) / 2

            return TranslatorTarget(
                element=UIElement(...),
                cdp_node_id=node_search["nodeId"],
                cdp_session_id=session_id,
                grounded_bbox=Bbox(x=cx-10, y=cy-10, w=20, h=20),
            )

    def _pick_workspace_target(self, target_infos, bundle_id):
        """D-24: filter for workspace renderer page, skip GPU/utility helpers.

        Slack: type='page' AND url ~ /\\.slack\\.com/
        Cursor: type='page' AND url is the workspace, not embedded preview
        Obsidian: type='page' AND url is `app://obsidian.md/...`
        """
        if bundle_id == "com.tinyspeck.slackmacgap":
            for t in target_infos:
                if t["type"] == "page" and ".slack.com" in t.get("url", ""):
                    return t
        elif bundle_id == "com.todesktop.230313mzl4w4u92":  # Cursor
            for t in target_infos:
                if t["type"] == "page" and t.get("url", "").startswith("vscode-"):
                    return t
        elif bundle_id == "md.obsidian":
            for t in target_infos:
                if t["type"] == "page" and "obsidian" in t.get("url", "").lower():
                    return t
        return None
```

[CITED: github.com/browser-use/cdp-use README — `CDPClient` is the main class; `cdp.send.Target.getTargets()` returns `{"targetInfos": [{type, url, targetId, ...}]}`; commands accessed via domain namespaces]

### Pattern 6: T3 AppleScript Implementation (TRANS-03)

**What:** py-applescript on dedicated `ThreadPoolExecutor(max_workers=2)`. Compile once, run many. Default = NSAppleScript string compile (Pages D-26 verb works fine). ScriptingBridge typed access deferred — adds boilerplate without solving Phase 2 needs.

```python
# cua_overlay/translators/t3_applescript.py
import asyncio
import concurrent.futures
import applescript  # py-applescript

class T3AppleScriptTranslator:
    tier = "T3"

    def __init__(self):
        # max_workers=2: enough for staggered race + parallel verification call;
        # avoids saturating thread count when AS is slow (D-04).
        self._exec = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="cua-as",
        )
        self._compiled: dict[str, applescript.AppleScript] = {}  # source → cached

    async def resolve(self, bundle_id, pid, target_spec):
        # T3 doesn't "resolve" in the AX sense — AS targets are addressed
        # by name. The TranslatorTarget carries the spec string.
        return TranslatorTarget(
            element=UIElement(...),  # synthetic — populated post-fire by verifier
            as_target_spec=self._build_target_spec(bundle_id, target_spec),
        )

    def _build_target_spec(self, bundle_id, spec):
        # Pages D-26 example:
        # 'tell application "Pages" to tell document 1 to ...'
        if bundle_id == "com.apple.iWork.Pages":
            return f'tell application "Pages" to {spec.as_verb}'
        # ... per-bundle spec builders ...

    async def execute(self, source: str, args: tuple = ()) -> tuple[str, str | None]:
        """Run AppleScript source on the dedicated thread pool.

        Returns (result, error). Compiled scripts are cached by source string."""
        loop = asyncio.get_running_loop()

        def _sync():
            scpt = self._compiled.get(source)
            if scpt is None:
                scpt = applescript.AppleScript(source=source)
                self._compiled[source] = scpt
            try:
                # py-applescript wraps NSAppleScript.executeAndReturnError_
                # under the hood; it raises ScriptError on failure.
                result = scpt.run(*args)
                return (str(result) if result is not None else "", None)
            except applescript.ScriptError as e:
                return ("", str(e))

        return await loop.run_in_executor(self._exec, _sync)
```

[CITED: github.com/rdhyee/py-applescript — "Scripts may be compiled from source or loaded from disk; standard 'run' handler and user-defined handlers can be invoked with or without arguments; argument and result values are automatically converted between common Python types and their AppleScript equivalents; compiled scripts are persistent"]

### Pattern 7: T4 Vision Implementation (TRANS-04)

**What:** Capture screenshot → write to temp PNG → `uitag.run_pipeline(path)` → adapt Detection list to UIElement list. Fallback to ocrmac when uitag returns no detections (Chess.app D-27 with 3D Metal board).

```python
# cua_overlay/translators/t4_vision.py
import tempfile
from pathlib import Path
from PIL import Image
from uitag import run_pipeline
import ocrmac

class T4VisionTranslator:
    tier = "T4"

    async def resolve(self, bundle_id, pid, target_spec):
        # 1. Screenshot via Phase 1's L1 capture path or new dedicated snap.
        img = await self._screenshot_app_window(pid)  # PIL.Image

        # 2. Save to temp file (uitag accepts file path only, not PIL.Image).
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img.save(f.name)
            screenshot_path = Path(f.name)

        try:
            # 3. Run uitag pipeline. Returns 3-tuple per verified API.
            result, annotated, manifest_json = run_pipeline(
                str(screenshot_path),
                florence_task="<OD>",
                overlap_px=50,
                iou_threshold=0.5,
                recognition_level="accurate",
                use_yolo=True,  # YOLO11 for icon detection
            )

            # 4. Score detections against target_spec.
            best = self._score_detections(result.detections, target_spec)

            if best is None:
                # 5. Fallback to ocrmac for OCR-only path.
                return await self._ocr_fallback(screenshot_path, target_spec)

            return TranslatorTarget(
                element=self._detection_to_uielement(best, pid, bundle_id),
                grounded_bbox=Bbox(x=best.x, y=best.y, w=best.width, h=best.height),
            )
        finally:
            screenshot_path.unlink(missing_ok=True)

    def _detection_to_uielement(self, det, pid, bundle_id) -> UIElement:
        """Adapt uitag.Detection → cua_overlay.state.graph.UIElement.

        Detection fields: label, x, y, width, height, confidence, source, som_id."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        return UIElement(
            role="AXUnknown",  # T4 has no AX role — synthetic placeholder
            role_path=f"AXVision/{det.source}[{det.som_id}]",
            label=det.label,
            bbox=Bbox(x=det.x, y=det.y, w=det.width, h=det.height),
            confidence=det.confidence,
            source=[Source.OCR if det.source == "vision_text" else Source.PIXEL],
            ocr_text=det.label if det.source == "vision_text" else None,
            discovered_at=now,
            last_seen_at=now,
            pid=pid,
            bundle_id=bundle_id,
            window_id=0,
        )
```

[VERIFIED: uitag docs/api.md — `run_pipeline(image_path, florence_task="<OD>", overlap_px=50, iou_threshold=0.5, recognition_level="accurate", backend=None, use_yolo=False)` returns `(PipelineResult, PIL.Image.Image, str)` 3-tuple; `Detection` fields = label, x, y, width, height, confidence, source, som_id; `PipelineResult` carries detections list + image_width + image_height + timing_ms]

[ASSUMED — uitag does NOT document Retina/scale handling. Phase 2 must validate at integration time on Akeil's Retina display whether `Detection.x/y/width/height` are in physical pixels (which would 2× the logical bbox) or logical points. **Action:** first integration test (Chess.app on Retina) prints `(image_width, image_height)` from PipelineResult vs `screensize` from Quartz; if 2:1, we apply a `/scale_factor` divisor in `_detection_to_uielement`. Cite the test result in the planner.]

### Pattern 8: T5 Pixel Implementation (TRANS-05)

**What:** Last-resort path. T5 doesn't really "resolve" — it delegates to T4 for coordinates and hashes the pre-action ROI for verification. Action delivery via C3 CGEvent.postToPid.

```python
# cua_overlay/translators/t5_pixel.py
import imagehash
from PIL import Image

class T5PixelTranslator:
    tier = "T5"

    def __init__(self, t4: T4VisionTranslator):
        self._t4 = t4  # delegate coords (D-07)

    async def resolve(self, bundle_id, pid, target_spec):
        # T5's only resolution is via T4's grounder + the dHash for verify.
        t4_target = await self._t4.resolve(bundle_id, pid, target_spec)
        if t4_target is None or t4_target.grounded_bbox is None:
            return None
        # Pre-action ROI hash for L1 verifier diff.
        roi = await self._capture_roi(t4_target.grounded_bbox)
        ph_pre = imagehash.phash(roi)
        return TranslatorTarget(
            element=t4_target.element,
            grounded_bbox=t4_target.grounded_bbox,
            extras={"pre_phash": str(ph_pre)},  # passed to verifier post-fire
        )
```

### Pattern 9: Channel Registry Shape (ACT-01)

**What:** Each channel is `async (ActionCanonical, IdempotencyTokenStore, anyio.Event) -> ChannelOutcome`. Registry exposes `select(translator_priority, racepolicy) -> list[Channel]`.

```python
# cua_overlay/actions/channels/base.py
from typing import Protocol, Literal
from pydantic import BaseModel, ConfigDict

class ChannelOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    channel: Literal["C1","C2","C3","C4","C5"]
    status: Literal["fired", "skipped", "cancelled", "errored"]
    fired_at_ns: int | None = None
    error: str | None = None
    verified: bool = False  # set by verifier post-fire, not by channel itself

class Channel(Protocol):
    name: Literal["C1","C2","C3","C4","C5"]
    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome: ...
```

### Pattern 10: C3 CGEvent.postToPid (channel detail)

**What:** PyObjC binding for CGEvent.postToPid. The legacy `Quartz.CGEventPost(tap, event)` warps the cursor globally; `CGEventPostToPid(pid, event)` targets a specific process.

```python
# cua_overlay/actions/channels/c3_cgevent.py
import asyncio
import time
from Quartz import (
    CGEventCreateMouseEvent,
    CGEventPostToPid,
    kCGMouseButtonLeft,
    kCGEventMouseMoved,
    kCGEventLeftMouseDown,
    kCGEventLeftMouseUp,
    CGEventSetType,
)

class C3CGEventChannel:
    name = "C3"

    async def fire(self, action, target, store, cancel_event):
        # 1. Try claim.
        claim = await store.try_claim(action.id, "C3")
        if claim is None:
            return ChannelOutcome(channel="C3", status="skipped")

        # 2. Pre-syscall kill-switch (D-18).
        if cancel_event.is_set():
            return ChannelOutcome(channel="C3", status="cancelled")

        bbox = target.grounded_bbox
        cx = bbox.x + bbox.w / 2
        cy = bbox.y + bbox.h / 2
        pid = action.payload["pid"]

        # 3. Fire (C3 ~50µs uncancellable kernel window starts here).
        def _post():
            down = CGEventCreateMouseEvent(
                None, kCGEventLeftMouseDown, (cx, cy), kCGMouseButtonLeft
            )
            up = CGEventCreateMouseEvent(
                None, kCGEventLeftMouseUp, (cx, cy), kCGMouseButtonLeft
            )
            CGEventPostToPid(pid, down)
            CGEventPostToPid(pid, up)

        await asyncio.to_thread(_post)
        return ChannelOutcome(
            channel="C3", status="fired", fired_at_ns=time.monotonic_ns()
        )
```

[CITED: pyobjc-framework-Quartz — `Quartz.CGEventPostToPid(pid, event)`; targets specific process without global cursor warp]
[ASSUMED — Tahoe-specific gotchas for postToPid not surfaced in our research; Phase 2 integration test on Akeil's macOS 26 + flag if mouse delivery shows the "click not received" issue surfaced in pyobjc community search results]

### Pattern 11: AppProfile Top-12 Cache Short-Circuit (D-20)

**What:** Phase 1's `classify()` reads bundled top-12 BEFORE running probes. Cache invalidation cascades: bundle_version mismatch → fall to live probe.

```python
# cua_overlay/profile/known_apps.py
from typing import TypedDict, NamedTuple

class KnownApp(NamedTuple):
    bundle_id: str
    name: str
    electron: bool
    has_sdef: bool
    translator_priority: list[str]
    cdp_after_relaunch: bool      # P8 flag (D-24)
    min_known_version: str | None # AppProfile invalidates if live > this
    notes: str

KNOWN_APPS: dict[str, KnownApp] = {
    "com.apple.calculator": KnownApp(
        bundle_id="com.apple.calculator",
        name="Calculator",
        electron=False,
        has_sdef=False,
        translator_priority=["T1", "T4"],
        cdp_after_relaunch=False,
        min_known_version=None,  # Apple system app, version drift OK
        notes="Phase 1 baseline target",
    ),
    "com.apple.iWork.Pages": KnownApp(
        bundle_id="com.apple.iWork.Pages",
        name="Pages",
        electron=False,
        has_sdef=True,
        translator_priority=["T3", "T1", "T4"],
        cdp_after_relaunch=False,
        min_known_version="14.0",  # Pages 14.x sdef stable; warn on 15+
        notes="Canvas non-AX, AS for paragraph styles (D-26)",
    ),
    "com.tinyspeck.slackmacgap": KnownApp(
        bundle_id="com.tinyspeck.slackmacgap",
        name="Slack",
        electron=True,
        has_sdef=False,
        translator_priority=["T2", "T4", "T5"],  # T2 only after relaunch
        cdp_after_relaunch=True,
        min_known_version=None,  # Slack updates frequently; rely on live CDP probe
        notes="Multi-process renderer; filter URL ~ /\\.slack\\.com/",
    ),
    # ... all D-21..D-22 entries
}
```

**Classifier integration:**
```python
# cua_overlay/profile/classifier.py — modified classify():
async def classify(bundle_id, pid):
    # 1. TCC check (already Phase 1).
    if not await _tcc.check(): await _tcc.on_revocation()

    # 2. Bundle metadata (cheap).
    meta = await probe_bundle_metadata(bundle_id)

    # 3. Disk cache check (already Phase 1).
    cached = load_cached_profile(bundle_id, base=cache_base)
    if cached and not should_invalidate_cache(cached, meta["bundle_version"], meta["bundle_build"]):
        return cached

    # 4. NEW: bundled top-12 short-circuit.
    known = KNOWN_APPS.get(bundle_id)
    if known is not None:
        # Version compatibility check.
        if known.min_known_version and meta["bundle_version"]:
            if _version_is_newer(meta["bundle_version"], known.min_known_version):
                log.warning("known_app.version_drift",
                    bundle=bundle_id,
                    known=known.min_known_version,
                    live=meta["bundle_version"])
                # Fall through to live probe — bundled priority may be stale.
            else:
                # Use bundled priority; skip probe.
                profile = AppProfile(
                    bundle_id=bundle_id,
                    bundle_version=meta["bundle_version"],
                    bundle_build=meta["bundle_build"],
                    bundle_path=meta["bundle_path"],
                    ax_rich=("T1" in known.translator_priority),
                    ax_observer_works=True,  # assumed for known apps
                    applescript_sdef=known.has_sdef,
                    cdp_port=None,  # known.cdp_after_relaunch handled separately
                    cdp_available_after_relaunch=known.cdp_after_relaunch,
                    electron=known.electron,
                    translator_priority=known.translator_priority,
                    probed_at=datetime.now(timezone.utc),
                    probe_latency_ms=0,  # bundled — no probe ran
                )
                save_cached_profile(profile)
                return profile

    # 5. Live capability probe (existing Phase 1 path).
    return await _live_probe(bundle_id, pid, meta)
```

### Pattern 12: MCP Tool Schemas (D-29)

**Pydantic input schemas for the 6 new/extended tools:**

```python
# cua_overlay/mcp_server/healing_tools.py — Phase 2 schemas
from pydantic import BaseModel, Field
from typing import Literal

class RaceWinnerInfo(BaseModel):
    """Embedded in every healing-tool return so callers see who won."""
    tier: Literal["T1","T2","T3","T4","T5"] | None
    channel: Literal["C1","C2","C3","C4","C5"] | None
    elapsed_ms: float
    losers: list[str]              # ["C5:cancelled", "C3:errored:..."]
    near_miss_duplicate: bool      # D-19 flag

class ClickWithHealingInput(BaseModel):
    x: int
    y: int
    bundle_id: str = ""
    pid: int = 0
    label: str = ""
    race_policy: Literal["auto","race","single_channel"] = "auto"  # D-30
    prefer_tier: Literal["T1","T2","T3","T4","T5"] | None = None
    prefer_channel: Literal["C1","C2","C3","C4","C5"] | None = None

class TypeWithHealingInput(BaseModel):
    text: str
    bundle_id: str
    pid: int
    target_label: str = ""
    race_policy: Literal["auto","race","single_channel"] = "auto"
    # Default per D-11: type is single-channel.

class ScrollWithHealingInput(BaseModel):
    direction: Literal["up","down","left","right"]
    amount: int  # if action_kind="absolute": pixel position; if "delta": delta
    action_kind: Literal["absolute","delta"] = "delta"  # D-10/D-11
    bundle_id: str
    pid: int
    race_policy: Literal["auto","race","single_channel"] = "auto"

class SetValueWithHealingInput(BaseModel):
    target_label: str
    value: str
    bundle_id: str
    pid: int
    race_policy: Literal["auto","race","single_channel"] = "auto"
    # Default per D-11: set_value is single-channel.

class SendDestructiveInput(BaseModel):
    """No race_policy param — encodes safety in tool name (D-29)."""
    target_label: str
    bundle_id: str
    pid: int
    confirmation_phrase: str | None = None  # extra safety: caller acknowledges

class KeyComboWithHealingInput(BaseModel):
    combo: str   # "cmd+s" | "cmd+enter" | "cmd+c" | ...
    bundle_id: str
    pid: int
    race_policy: Literal["auto","race","single_channel"] = "auto"
    # auto: orchestrator looks combo up in D-12 table.

class HealingToolResult(BaseModel):
    """Common return shape for all 6 tools."""
    result: object              # upstream tool result content
    session_id: str
    phase: int = 2
    verified: bool
    confidence: float
    race: RaceWinnerInfo
    note: str | None = None
```

**Tool naming conflicts:** trycua's upstream MCP tools (verified at Phase 1 in `proxy.py:ACTION_CLASS_TOOLS` mapping) are `click`, `right_click`, `drag`, `scroll`, `page`, `type_text`, `type_text_chars`, `press_key`, `hotkey`, `set_value`. Our `*_with_healing` suffix is unambiguous. `send_destructive` is novel — no upstream conflict.

### Anti-Patterns to Avoid

- **Tracing the verifier from the channel** — channels DO NOT call verifier. Race orchestrator owns verifier wiring. Channel returns its own `ChannelOutcome` (which only knows "I fired" / "I skipped" / "I errored"); the verifier signal in `outcome.verified` is set by the orchestrator after `Aggregator.verify` runs. Inverting this leaks verifier latency into channel timing budgets.
- **Forgetting `CancelScope(shield=False)` in channel coros** — without it, `tg.cancel_scope.cancel()` does not propagate into the running awaitable; losers leak resources (open httpx clients, AS subprocess threads).
- **Importing browser-harness from cua-maximalist** — D-03 hard rule. Use cdp-use directly.
- **Polling `IdempotencyTokenStore.is_claimed` in tight loops** — channels should call once at the pre-syscall kill-switch. The `try_claim` is the atomic gate.
- **Per-target locks for idempotency** — D-16/D-17 says `asyncio.Lock` around the whole dict, not per-key. The dict mutation is O(1); contention is negligible at our scale (single-user, ~10 actions/sec peak).
- **Subscribing the verifier AFTER the channel fires** — Phase 1 hard rule, must remain. Race orchestrator subscribes (via `axmgr.expect`) BEFORE entering `tg.start_soon`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| CDP wire protocol typed wrappers | Manual websocket + JSON | cdp-use 1.4.5 | TypedDict for 50+ domains; matches browser-harness's choice; auto-generates from CDP spec |
| AppleScript compiler + result conversion | osascript subprocess; or hand-written PyObjC OSAKit calls | py-applescript 1.0.3 | NSAppleScript in-process; auto type conversion; compiled-script caching |
| YOLO11 SoM grounder for non-AX apps | Train your own; or call Apple Vision raw | uitag 0.6.0 | Bundled 18 MB weights; Apple Vision + YOLO11 combined; 90.8% ScreenSpot-Pro |
| Per-process CGEvent posting without global cursor warp | `Quartz.CGEventPost(tap, event)` | `Quartz.CGEventPostToPid(pid, event)` | Targeted; no cursor warp; correct primitive for C3 |
| Image perceptual hashing for verify | OpenCV pHash | imagehash 4.3.2 (Phase 1) | 64-bit hash; Hamming distance; pure NumPy; tolerant to scaling |
| OCR via Vision framework | Raw `VNRecognizeTextRequest` | ocrmac 1.0.1 (Phase 1) | Boilerplate already wrapped; CJK/RTL handled |
| First-completed task race over N coros | Custom event loop polling | anyio task group + custom wrapper (§Pattern 2) | anyio 4.13 has no `FIRST_COMPLETED` built-in but `tg.cancel_scope.cancel()` is the documented termination |
| Cassette format for race winner replay | vcrpy / pytest-recording | Custom JSONL on `session.action_log` | Phase 3 work; Phase 2 only logs `race_winner`/`race_loser` events to existing NDJSON |

**Key insight:** every "deceptively complex" Phase 2 problem (CDP attach, AS in-process, SoM grounding, race cancellation) has either an established library at PyPI 2026-04 OR a documented anyio idiom. Hand-rolling any of these wastes 1-2 weeks per item with worse results.

## Runtime State Inventory

> Phase 2 is feature-add (new modules), not rename/refactor. **Step 2.5 (full inventory) is not required for greenfield additions.** Listed here for completeness:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — Phase 2 adds new dict (in-memory) + NDJSON events to existing session log | No data migration |
| Live service config | None — Phase 2 does not register external services. CDP attach is per-session ephemeral | No external config change |
| OS-registered state | None — Phase 2 doesn't register launch agents, login items, or scheduled tasks | None |
| Secrets/env vars | None new in Phase 2. cdp-use uses no API keys. uitag is local. apple-fm-sdk deferred | None |
| Build artifacts | New PyPI deps (cdp-use, uitag, py-applescript, transformers≥5.0). uv lockfile updated; uitag downloads YOLO weights to its own bundle dir on first import | `uv sync` after `pyproject.toml` update |

**Nothing in remaining categories.** Phase 2 is purely additive code/config.

## Common Pitfalls

> Phase 2 mitigates P1 (action interference / double-clicks), P5 (AS stale-state lag), P8 (Electron CDP launch-only), P12 (Tahoe screenshot regression #870), P14 (AX notifs fail web/Electron), P16 (Bear/Things SQLite drift). PITFALLS.md has full taxonomy; this section calls out Phase-2-specific landmines.

### Pitfall A: anyio `tg.cancel_scope.cancel()` does not propagate into shielded scopes
**What goes wrong:** A channel that wraps its fire path in `CancelScope(shield=True)` for the entire body never sees the cancel signal; it runs to completion even after another channel won the race.
**Why it happens:** `shield=True` blocks cancellation propagation deliberately — that's its purpose, used to protect cleanup blocks.
**How to avoid:** **Only shield the idempotency-claim block** (microseconds). Use `shield=False` (default) for the syscall path so the orchestrator's `tg.cancel_scope.cancel()` raises `CancelledError` inside the awaitable.
**Warning signs:** Race orchestrator returns winner but logs show 2+ `channel.fired` events with `fired_at_ns` AFTER the winner's `fired_at_ns`.

### Pitfall B: cdp-use Target.attachToTarget without `flatten=True` requires a separate session pump
**What goes wrong:** Attaching without `flatten=True` returns a session_id but events come on a separate channel that needs explicit registration; calls to `cdp.send.DOM.querySelector(sessionId=...)` silently hang.
**Why it happens:** CDP has two attach modes — flat (recommended since CDP v1.3) and per-session pump.
**How to avoid:** Always pass `params={"targetId": ..., "flatten": True}`. Use `sessionId=` argument on every subsequent send.
**Warning signs:** First DOM call after attach times out; cdp.send returns generic `connection closed` after 30s.

### Pitfall C: uitag run_pipeline blocks the asyncio loop (1-5s execution time)
**What goes wrong:** uitag is sync Python (Apple Vision + YOLO inference). Calling it directly in an async context freezes the event loop for 1-5s. Race orchestrator's other channels can't make progress.
**Why it happens:** uitag's `run_pipeline` is not async; pyobjc Vision calls block.
**How to avoid:** Always wrap in `await asyncio.to_thread(run_pipeline, ...)` or a dedicated `ThreadPoolExecutor`. Document this at the T4 entry point so future contributors don't bypass.
**Warning signs:** Race orchestrator logs show C1/C2/C5 finishing before the orchestrator even starts processing them; total race latency = uitag inference time.

### Pitfall D: Slack workspace renderer multi-process — wrong target attaches to GPU helper
**What goes wrong:** `Target.getTargets()` returns 5-15 targets. Attaching to `type=other` (the GPU helper) silently succeeds but `DOM.getDocument` returns an empty document.
**Why it happens:** Slack splits its renderer per workspace; the workspace renderer is `type=page` with URL like `https://app.slack.com/client/...`. GPU + utility helpers are also targets.
**How to avoid:** Filter strictly: `type == "page" AND url contains ".slack.com"`. Cursor and Obsidian have analogous filters (D-24).
**Warning signs:** CDP attaches successfully but DOM.getDocument returns `nodeId=0` or empty children; Slack message_container selector returns no matches.

### Pitfall E: py-applescript `applescript.AppleScript(source=...)` compiles on every call without caching
**What goes wrong:** Recompiling AppleScript adds 50-200ms to every call. Defeats the "AS as fast staggered race" budget.
**Why it happens:** py-applescript's `AppleScript(source=...)` constructor compiles fresh each time; caller is responsible for caching.
**How to avoid:** Module-level dict `compiled[source_string] -> AppleScript instance`. Reuse for repeated verbs.
**Warning signs:** AS channel latency shows uniform 100-200ms baseline regardless of script complexity.

### Pitfall F: `IdempotencyTokenStore.try_claim` race when channel coroutines start before await
**What goes wrong:** If `tg.start_soon(channel.fire, ...)` is called for all channels before any awaits the lock, Python's asyncio scheduler may run them in registration order. The first claim "wins" deterministically — defeating the race.
**Why it happens:** `asyncio.Lock` is fair (FIFO); first awaiter wins.
**How to avoid:** This is actually the desired behavior — only one channel claims the token. The "race" is about who delivers to the OS first, not who claims the token first. If we wanted random/timing-based claim, we'd need `asyncio.shield + jitter`. Phase 2 does NOT — D-17 says first-claimer-wins is the contract.
**Warning signs:** Race winner is always C2 (first registered) regardless of which channel actually delivers fastest.
**Resolution:** Confirm with planner — D-17 is "first to call try_claim wins"; the OS-delivery timing is what the verifier measures via push events. The "race" is happening at the OS level, not at the Python claim level. **This is correct by design.**

### Pitfall G: CGEvent.postToPid mouse events ignored by some apps
**What goes wrong:** Search results indicate mouse events to PID don't always deliver, especially to backgrounded apps; keyboard does.
**Why it happens:** Apps that reject HID events from non-foreground senders, or apps that gate input via Carbon HIToolbox.
**How to avoid:** Document this risk. C3 is a fallback channel; primary action paths use C2 (AX) or C5 (CDP). Test on Chess.app at integration time. If mouse delivery fails, fall back to legacy `CGEventPost(kCGSessionEventTap, event)` which warps the cursor but always delivers.
**Warning signs:** C3 reports `status=fired` but verifier sees no state delta; verifier confidence stays low.

[CITED: copyprogramming.com — "While keyboard events can be sent to applications running in the background, mouse events haven't been successfully sent the same way"]

### Pitfall H: Tahoe `SCScreenshotManager` 1-5% capture failure rate (Pitfall P12 from PITFALLS.md)
**What goes wrong:** T4's screenshot step intermittently fails on macOS 26.
**Why it happens:** Documented in trycua/cua issue #870.
**How to avoid:** Retry once with 200ms delay; on second failure fall to `SCStream` single-frame; last resort `CGWindowListCreateImage`. Phase 1's L1 capture path may already implement this — check before duplicating in T4.

## Code Examples

### Race Orchestrator — Full Wired Flow

```python
# cua_overlay/actions/race_orchestrator.py
import time
import uuid
import anyio
from anyio import Event

class RaceOrchestrator:
    def __init__(self, axmgr, aggregator, store, classifier, registry):
        self._axmgr = axmgr
        self._agg = aggregator
        self._store = store
        self._classifier = classifier
        self._reg = registry  # ChannelRegistry

    async def execute(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
        action_type: str,
        payload: dict,
        race_policy: RacePolicy = RacePolicy.AUTO,
    ) -> tuple[ActionCanonical, HoarePost]:
        # 1. Classify app, get translator priority.
        profile = await self._classifier.classify(bundle_id, pid)

        # 2. Resolve race policy (D-09..D-12 dispatch).
        effective = resolve_race_policy(race_policy, action_type)

        # 3. Build action.
        action = ActionCanonical(
            id=uuid.uuid4().hex,
            step_idx=...,
            kind="MUTATE",
            target_key=target_spec.key,
            action_type=action_type,
            payload=payload,
            tier=None,        # filled by winner
            channel=None,     # filled by winner
            timestamp_ns=time.monotonic_ns(),
            session_id=...,
        )

        # 4. Resolve target via primary translator (sequential: most info-dense
        #    first, fall back if it returns None).
        target = await self._resolve_via_translators(profile, target_spec)
        if target is None:
            raise NoTargetResolvable(target_spec)

        # 5. Subscribe AX notifications BEFORE fire (Phase 1 contract).
        before_l1 = await L1Cheap().snapshot(target.element)
        # axmgr.expect returns the awaitable that resolves on first matching event;
        # we DON'T await it here — orchestrator hands it to aggregator.verify later.
        notifs = ["AXValueChanged", "AXFocusedUIElementChanged"]

        # 6. Build channel coroutines.
        channels = self._reg.select(profile.translator_priority, effective)
        cancel_event = anyio.Event()

        # 7. Fire — race or single-channel.
        if effective == RacePolicy.RACE:
            coros = [
                ch.fire(action, target, self._store, cancel_event)
                for ch in channels
            ]
            # AS gets staggered (D-15).
            coros = self._apply_as_stagger(channels, coros)
            winner_idx, outcome, all_outcomes = await race_first_complete(
                *coros, on_first_winner=lambda i, o: cancel_event.set()
            )
        else:
            # Single-channel (D-11): pick first translator's default channel.
            ch = channels[0]
            outcome = await ch.fire(action, target, self._store, cancel_event)
            all_outcomes = [outcome]
            winner_idx = 0

        # 8. Verify (Phase 1 ladder).
        post = await self._agg.verify(
            action=action,
            target=target.element,
            notifs=notifs,
            before_l1=before_l1,
            ax_element=target.ax_element,
            timeout_ms=50,
        )

        # 9. Log race outcome.
        self._log_race(action, all_outcomes, winner_idx, post)

        # 10. Idempotency receipt (D-19) — record (target, kind) for 2s.
        self._store.record_receipt(target.element.composite_key, action_type)

        return action, post
```

### Slack CDP Relaunch Helper (Wave 0 fixture)

```python
# tests/integration/fixtures/slack_relaunch.py
import asyncio
import httpx
import subprocess

async def ensure_slack_cdp_ready(timeout_s: int = 10) -> str | None:
    """Probe localhost:9222. If absent, prompt user (manual fixture)
    to relaunch via `pkill Slack && open -a Slack --args
    --remote-debugging-port=9222`. Returns ws URL when ready, else None."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with httpx.AsyncClient(timeout=1) as c:
                r = await c.get("http://localhost:9222/json/version")
                if r.status_code == 200:
                    return r.json()["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return None
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Walking entire AX tree to find target | Locator hierarchy + depth-3 walker | Phase 1 (CLAUDE.md hard rule) | Mandatory; full walk = 15-20s on Safari |
| Polling AX state for verification | Push-event subscription (AXObserver before fire) | Phase 1 | Mandatory; 1ms vs 100ms |
| Single-channel sequential fallback | Parallel race + atomic idempotency | Phase 2 (this) | 5x latency reduction on apps where multiple translators work |
| `osascript` subprocess for AS | py-applescript in-process NSAppleScript | Phase 2 (D-04) | 50-200ms saved per call (no fork+exec) |
| MacPaw Screen2AX synthetic AX | uitag run_pipeline (Apple Vision + YOLO11) | Phase 2 (D-05/D-06) | uitag is on PyPI, maintained, compatible with pyobjc 12.1 |

**Deprecated/outdated:**
- atomac, pyatomac — abandoned 2013/2018
- vcrpy for non-HTTP cassettes — HTTP-only by design
- Inngest/Restate/Temporal for local CU loops — wrong fit (server-required)

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | uitag returns coordinates in **logical points**, not physical pixels (Retina handling) | Pattern 7 (T4) | Click coords 2× off on Retina display; first integration test must verify |
| A2 | `Quartz.CGEventPostToPid` reliably delivers mouse events to non-foreground processes on macOS 26 (Tahoe) | Pattern 10 (C3) | C3 silently no-ops; verifier confidence stays low; Chess test (D-27) fails. Fallback to legacy `CGEventPost(kCGSessionEventTap)` if observed |
| A3 | uitag's bundled YOLO11 weights work on Apple Silicon at ~1-5s inference time | Pattern 7 (T4) | Inference >5s blocks race budget; Phase 2 may need MLX-converted YOLO11 path |
| A4 | `transformers>=5.0.0` (uitag transitive) installs cleanly alongside Phase 1's mlx-vlm-eligible deps | Stack section | Resolution conflict; uv may need `--prerelease` flag; Phase 4 may need uv extras for transformers 4.x side-by-side |
| A5 | Slack/Cursor/Obsidian remote-debugging port stays 9222 after user relaunches with `--remote-debugging-port=9222` | Pattern 5 (T2) | Some Electron versions add own debug port logic; if user-flag is overridden, T2 attach fails |
| A6 | Phase 1's `AXObserverManager.expect` resolves correctly when called from race orchestrator (multi-channel waiters) | Pattern 11 / Race Orchestrator | Phase 1 dispatcher tested with 1-2 waiters; race orchestrator may push to 5+ waiters per action; test under load |
| A7 | `asyncio.Lock` around the whole IdempotencyTokenStore dict is sufficient (no per-target locks needed) | Pattern 3 / Pitfall F | Confirmed by D-16/D-17; if action throughput exceeds ~100/sec we may need shard locks. Phase 2 single-user load is ~10/sec |
| A8 | py-applescript's `applescript.ScriptError` exception type is the correct catch path for AS failures (it could be `ScriptingError` or `AppleScriptError` depending on lib version) | Pattern 6 (T3) | Wrong exception type leaks AS errors into the race orchestrator; verify at first integration test |
| A9 | uitag emits `Detection.x`/`y` as bbox top-left (not center, not bottom-left) | Pattern 7 (T4) | Click coords offset by half-bbox; verify with Chess board e2-square test |
| A10 | Apple Chess.app's 3D Metal board is detected by uitag's YOLO11 component (not just OCR) | Pattern 7 / D-27 | Test sequence falls to OCR which won't detect chess pieces; if uitag returns no detections, fall to pure pixel-coord mapping (8x8 grid in known viewport) |

**Risk mitigation:** All A1–A10 assumptions are validated in the **Validation Architecture** integration tests below; nothing reaches the race orchestrator unverified.

## Open Questions

1. **Does Phase 1's `AXObserverManager.expect` need per-action_id refcon scoping when 5 channels race?**
   - What we know: Phase 1 already uses `action_id` as the AXObserver refcon (`observer.py:247`), and the dispatcher filters by `event.action_id == sub.action_id`.
   - What's unclear: Does dispatching 5 channels for the same action_id cause refcon hash collisions in the bridge's `_refcon_to_action` dict?
   - Recommendation: Phase 2 channels share ONE action_id (by design — it's the idempotency token). Phase 1 already has unit-test coverage of `_passes_filter`. Add a test where 5 mocked channels share an action_id and verify only one event resolves the future.

2. **Does cdp-use 1.4.5 expose `Page.lifecycleEvent` push subscriptions?**
   - What we know: cdp-use is "type-safe generator" — should expose all CDP domains.
   - What's unclear: Whether `Page.lifecycleEvent` is in the v1.4.5 generator output or requires manual `register` handler.
   - Recommendation: Verify at T2 implementation time via `dir(cdp.send.Page)` and `cdp.register(...)`; document in `t2_cdp.py` docstring.

3. **Will `transformers>=5.0.0` break Phase 4's mlx-vlm path?**
   - What we know: D-08 says install side-by-side via uv extras if needed; mlx-vlm 0.4.4 docs don't pin transformers exactly.
   - What's unclear: Phase 4 may need to downgrade or use uv extras at install time.
   - Recommendation: Defer per D-08. Phase 2 install runs `uv tree | grep transformers` post-install; flag any conflict.

4. **Should `send_destructive` accept `confirmation_phrase` for extra safety?**
   - What we know: D-29 says "no `race_policy` param — encodes safety in tool name".
   - What's unclear: Whether MCP host (Claude Code) should be required to pass an explicit confirmation string.
   - Recommendation: Phase 2 ships `confirmation_phrase: str | None` as **optional** (Pydantic schema above). If None, log a warning. Phase 3 can promote to required after seeing real usage patterns.

5. **What's the correct fallback when uitag returns zero detections on Chess.app?**
   - What we know: uitag is trained on UI elements (buttons, fields, icons). 3D Metal-rendered chess pieces are NOT typical training data.
   - What's unclear: Coverage of chess board; whether OCR alone detects "white pawn" labels (likely no — Chess.app shows pieces graphically).
   - Recommendation: Three-tier T4 fallback: (1) uitag SoM full board, (2) ocrmac for any piece-position labels, (3) pure-pixel-coord mapping (chess board occupies center, 8×8 grid in known viewport — calculate squares geometrically). Document in `t4_vision.py` with the e2/e4 test as a gold reference.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Slack.app | D-25 test | Akeil's Mac (assumed) | Per latest Slack release | Skip CDP-wins integration test; mark `@pytest.mark.manual` |
| Pages.app (iWork 14.x) | D-26 test | Akeil's Mac (assumed) | 14.x | Skip AS-wins integration test; mark manual |
| Chess.app (system) | D-27 test | All macOS by default | Pre-installed | None needed |
| pyobjc 12.1 (Phase 1 dep) | T1, T5, channels | Already installed | 12.1 | — |
| Python 3.12 | All | Already pinned | 3.12 | — |
| Postgres 16 | Phase 1 durable executor | Brew install (manual) | 16 | Phase 2 plans don't add new Postgres tables; existing Phase 1 wiring sufficient |
| uitag's bundled YOLO11 weights | T4 | Auto-downloaded on first import | 0.6.0 bundle | None — required |
| Slack `--remote-debugging-port=9222` | T2 attach | NOT auto — requires manual relaunch (D-24) | n/a | One-time user prompt; skip CDP test if user declines |

**Missing dependencies with no fallback:**
- None — Phase 2 dependencies are all PyPI installable or system-default.

**Missing dependencies with fallback:**
- Slack relaunched with debug port: integration test skipped if not present (test fixture handles).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.23+ (Phase 1 baseline reused) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (asyncio_mode=auto, testpaths=["tests"]) |
| Quick run command | `uv run pytest -x -q tests/unit tests/integration -m 'not manual'` |
| Full suite command | `uv run pytest -v --tb=short tests/` |
| Estimated runtime | ~2 minutes (unit ~30s, integration ~90s with macOS apps; manual tests not run automatically) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|--------------|
| TRANS-01 | T1 AX resolves Calculator '5' button via locator hierarchy | unit + integration | `pytest tests/unit/test_t1_ax.py tests/integration/test_t1_calculator.py -x` | ❌ Wave 0 |
| TRANS-02 | T2 CDP resolves Slack message_container via DOM.querySelector | integration (manual setup) | `pytest tests/integration/test_t2_slack_cdp.py -x -m 'manual'` | ❌ Wave 0 |
| TRANS-03 | T3 AppleScript resolves Pages "make new paragraph style" | integration | `pytest tests/integration/test_t3_pages_as.py -x -m 'manual'` | ❌ Wave 0 |
| TRANS-04 | T4 uitag grounds Chess.app e2 square (Detection→UIElement) | integration | `pytest tests/integration/test_t4_chess_uitag.py -x` | ❌ Wave 0 |
| TRANS-05 | T5 Pixel CGWindowList + dHash captures pre/post ROI | unit | `pytest tests/unit/test_t5_pixel.py -x` | ❌ Wave 0 |
| ACT-01 | Channel registry select returns correct channels for translator priority | unit | `pytest tests/unit/test_channel_registry.py -x` | ❌ Wave 0 |
| ACT-02 | Race orchestrator returns winner, cancels losers via cancel_scope | unit | `pytest tests/unit/test_race_orchestrator.py -x` | ❌ Wave 0 |
| ACT-02 | Race on Slack: T2 wins, T1/T3/T4/T5 cancelled (D-25) | integration | `pytest tests/integration/test_race_slack.py -x -m 'manual'` | ❌ Wave 0 |
| ACT-02 | Race on Pages: T3 wins (staggered 500ms after others) (D-26) | integration | `pytest tests/integration/test_race_pages.py -x -m 'manual'` | ❌ Wave 0 |
| ACT-02 | Race on Chess: T4+T5 fire (D-27) | integration | `pytest tests/integration/test_race_chess.py -x` | ❌ Wave 0 |
| ACT-03 | 100 racing fires → 0 double-clicks (idempotency holds) | stress | `pytest tests/stress/test_idempotency_100x.py -x` | ❌ Wave 0 |
| ACT-04 | AppleScript stagger 500ms applied; AX rate-limit 20/sec/pid honored | unit | `pytest tests/unit/test_as_stagger.py tests/unit/test_ax_rate_limit_t1.py -x` | ❌ Wave 0 |
| ACT-04 | Pre-action AX validity check rejects stale AXUIElement | unit | `pytest tests/unit/test_t1_validity_check.py -x` | ❌ Wave 0 |
| Per-app priority | Top-12 map matches expected priority for all 12 apps | unit | `pytest tests/unit/test_known_apps.py -x` | ❌ Wave 0 |
| MCP surface | All 6 new healing tools expose correct Pydantic schemas | unit | `pytest tests/unit/test_healing_tools_phase2.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest -x -q tests/unit -m 'not manual'` (~15s, no real macOS apps)
- **Per wave merge:** `uv run pytest -v --tb=short tests/unit tests/integration -m 'not manual'` (~60s)
- **Phase gate:** Full suite incl. `-m manual` items run with prerequisite apps (Slack relaunched, Pages open) before `/gsd-verify-work`

### Per-Success-Criterion Validation Tier

| ROADMAP §Phase 2 Criterion | Validation Tier | Sampling | Test File | Threshold |
|----|------|------|-----------|-----------|
| 1. Click on Slack message: T2 CDP wins; others cancelled cleanly | integration (manual) | 1× per phase | `test_race_slack.py` | `winner.tier == "T2"` AND `winner.channel == "C5"` AND `losers count >= 4 with status in {cancelled,skipped}` AND `near_miss_duplicate == False` |
| 2. Click on Pages toolbar: T3 wins (staggered 500ms after T1/T2/T5) | integration (manual) | 1× per phase | `test_race_pages.py` | `winner.tier == "T3"` AND AS-fire-timestamp >= other-channels-fire-timestamp + 500ms |
| 3. Click on Chess game canvas (non-AX): T4 SoM grounds + T5 fires | integration | 3× per phase (stochastic SoM) | `test_race_chess.py` | uitag returns ≥1 detection covering e2 OR fallback geometric mapping triggers; pawn moves verified via dHash diff |
| 4. Zero double-clicks across 100 racing fires (idempotency holds) | stress | 100× per CI run | `test_idempotency_100x.py` | `count(claim_events) == 100 AND count(verified_events) == 100 AND count(near_miss_duplicate) == 0` |
| 5. Per-app translator priority matches association map for top 12 | unit | every commit | `test_known_apps.py` | All 12 entries match expected priority list; `cdp_available_after_relaunch` correctly flagged for Slack/Cursor/Obsidian |

### Required Test Fixtures (Wave 0)

```python
# tests/integration/conftest.py — Phase 2 additions
@pytest.fixture(scope="session")
async def slack_cdp_ws() -> str | None:
    """Skip-if-missing fixture for Slack CDP tests (D-25).

    Probes localhost:9222 for 10s. If absent, prints a manual instruction
    line and returns None (test skipped via @pytest.mark.skipif)."""
    return await ensure_slack_cdp_ready()

@pytest.fixture(scope="session")
def pages_running() -> bool:
    """Pages.app is launched and has at least one document open (D-26).

    Manual fixture — prints instruction line if not satisfied."""
    return _is_app_running_with_doc("com.apple.iWork.Pages")

@pytest.fixture
async def chess_launcher() -> int:
    """Launches Chess.app and returns its pid (D-27).

    `open -a Chess` then poll AXIsProcessTrusted for the pid."""
    pid = subprocess.run(
        ["pgrep", "-f", "/System/Applications/Chess.app"],
        capture_output=True, text=True
    ).stdout.strip()
    if not pid:
        subprocess.Popen(["open", "-a", "Chess"])
        await asyncio.sleep(2)
        pid = subprocess.run(
            ["pgrep", "-f", "/System/Applications/Chess.app"],
            capture_output=True, text=True
        ).stdout.strip()
    yield int(pid)

@pytest.fixture
def fake_idempotency_store(tmp_path):
    """Phase 2 stress test fixture — IdempotencyTokenStore with stub
    SessionWriter routed to tmp_path/action_log.ndjson."""
    sw = SessionWriter(base=tmp_path)
    return IdempotencyTokenStore(sw)
```

### Wave 0 Gaps

- [ ] `tests/unit/test_t1_ax.py` — TRANS-01 unit
- [ ] `tests/integration/test_t1_calculator.py` — TRANS-01 integration
- [ ] `tests/integration/test_t2_slack_cdp.py` — TRANS-02
- [ ] `tests/integration/test_t3_pages_as.py` — TRANS-03
- [ ] `tests/integration/test_t4_chess_uitag.py` — TRANS-04
- [ ] `tests/unit/test_t5_pixel.py` — TRANS-05
- [ ] `tests/unit/test_channel_registry.py` — ACT-01
- [ ] `tests/unit/test_race_orchestrator.py` — ACT-02 unit (mocked channels)
- [ ] `tests/integration/test_race_slack.py` — ACT-02 integration (D-25)
- [ ] `tests/integration/test_race_pages.py` — ACT-02 integration (D-26)
- [ ] `tests/integration/test_race_chess.py` — ACT-02 integration (D-27)
- [ ] `tests/stress/test_idempotency_100x.py` — ACT-03 stress
- [ ] `tests/unit/test_as_stagger.py` + `tests/unit/test_t1_validity_check.py` — ACT-04
- [ ] `tests/unit/test_known_apps.py` — top-12 map
- [ ] `tests/unit/test_healing_tools_phase2.py` — MCP D-29 schemas
- [ ] `tests/integration/conftest.py` — fixtures (slack_cdp_ws, pages_running, chess_launcher, fake_idempotency_store)
- [ ] `tests/stress/__init__.py` + `tests/stress/conftest.py` — new stress directory

## Security Domain

> Phase 2 is local-only single-user (per CLAUDE.md trust model). No new auth/session/access-control surfaces.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | Single-user local; no auth surface added |
| V3 Session Management | no | MCP stdio session; no token rotation |
| V4 Access Control | no | Akeil's Mac, full TCC grant |
| V5 Input Validation | yes | Pydantic v2 enforces ChannelClaim, RacePolicy enum, MCP tool input schemas — all 6 new tools have typed schemas (D-29) |
| V6 Cryptography | no | No new crypto in Phase 2 |

### Known Threat Patterns for Phase 2

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Double-fire on race (P1) | T (Tampering / corruption of user data) | Atomic `IdempotencyTokenStore.try_claim` (D-17) + 2s receipt ring buffer (D-19) |
| AS subprocess injection via target_spec | T | py-applescript compiles AS source via NSAppleScript; no shell. Spec strings still need sanitization — Pydantic `target_spec: str` with regex validator that rejects `"` outside expected positions |
| CDP attaching to wrong renderer (Slack helper not workspace) | I (Information Disclosure / wrong-app-execution) | Strict filter `type=page AND url ~ /\\.slack\\.com/` (D-24) |
| CGEvent.postToPid delivering to wrong PID | T | Pydantic validates `pid: int > 0`; race orchestrator passes pid via ActionCanonical.payload, validated against AppProfile.pid before fire |
| Race orchestrator races destructive action (D-11 violation) | T (data corruption) | RacePolicy enum + dispatch table (D-09); type system rejects `RACE` for `submit/send/delete/...`; planner test asserts every D-11 entry maps to `SINGLE_CHANNEL` |

## Sources

### Primary (HIGH confidence)

- [VERIFIED: PyPI cdp-use 1.4.5](https://pypi.org/project/cdp-use/) — confirmed 1.4.5, 2026-02-22, MIT, requires `httpx>=0.28.1, typing-extensions>=4.12.2, websockets>=15.0.1`
- [VERIFIED: PyPI uitag 0.6.0](https://pypi.org/project/uitag/) — confirmed 0.6.0, 2026-04-09; summary "UI element detection for macOS — Apple Vision + fine-tuned YOLO, on-device, ~1-5s"
- [VERIFIED: PyPI py-applescript 1.0.3](https://pypi.org/project/py-applescript/) — confirmed 1.0.3, 2022-01-23 (API frozen)
- [VERIFIED: PyPI anyio 4.13.0](https://pypi.org/project/anyio/) — current; 4.13.0
- [CITED: github.com/laywens/uitag/blob/main/docs/api.md](https://github.com/laywens/uitag/blob/main/docs/api.md) — `run_pipeline` signature, `PipelineResult`, `Detection` fields verified
- [CITED: github.com/browser-use/cdp-use](https://github.com/browser-use/cdp-use) — `CDPClient` usage, `cdp.send.<Domain>.<method>()` pattern
- [CITED: anyio.readthedocs.io/en/stable/cancellation.html](https://anyio.readthedocs.io/en/stable/cancellation.html) — `tg.cancel_scope.cancel()` pattern; nested cancel scopes
- [CITED: github.com/rdhyee/py-applescript](https://github.com/rdhyee/py-applescript) — NSAppleScript wrapper API; compiled scripts persistent; auto type conversion
- [CITED: pyobjc.readthedocs.io/en/latest/apinotes/Quartz.html](https://pyobjc.readthedocs.io/en/latest/apinotes/Quartz.html) — `CGEventPostToPid` available

### Secondary (MEDIUM confidence)

- [WebSearch verified: copyprogramming.com — "Sending mouse input to a window using Python"] — `CGEventPostToPid` for targeted process; mouse delivery caveat documented
- [WebSearch verified: Apple Developer Documentation — `executeAndReturnError(_:)` of NSAppleScript] — base API surface
- [WebFetch: anyio.readthedocs.io/en/stable/tasks.html] — confirms anyio has no built-in `FIRST_COMPLETED`; custom wrapper required

### Phase 1 deliverables (HIGH confidence — direct read 2026-04-30)

- `cua_overlay/state/graph.py` — UIElement, Source, Capability, Bbox, EdgeKind
- `cua_overlay/state/causal_dag.py` — ActionCanonical (kind: Literal["READ","MUTATE"]; tier and channel Optional fields ready for Phase 2 fill)
- `cua_overlay/profile/classifier.py` — AppProfile + classify(); translator_priority derivation already implements rule-based ordering
- `cua_overlay/ax/observer.py` — AXEventBridge + Subscription with subscription_ts_ns
- `cua_overlay/ax/rate_limit.py` — TokenBucket(20, 20)
- `cua_overlay/ax/walker.py` — depth-3 walk_subtree
- `cua_overlay/verifier/axobserver.py` — AXObserverManager.expect (subscribe-before-fire pattern); _passes_filter validates action_id refcon + 5ms guard
- `cua_overlay/verifier/aggregator.py` — Aggregator.verify L0+L1+L2+L3 ladder
- `cua_overlay/persist/session_writer.py` — append_action_log NDJSON sink
- `cua_overlay/mcp_server/healing_tools.py` — Phase 1 click_with_healing; D-29 extends here
- `cua_overlay/mcp_server/main.py` + `proxy.py` — existing MCP server shape; ProxyDeps + run_action_wrap

### Architecture references (locked, in vault)

- `~/thinker/vault/research/cua-maximalist-self-healing-framework-2026-04-29.md` — THE blueprint
- `~/thinker/research-clones/trycua-cua/libs/cua-driver/` — Swift driver source (do NOT edit per CLAUDE.md hard rule)

### Tertiary (LOW confidence — flagged for Phase 2 integration validation)

- uitag Retina/scale handling — A1 in Assumptions Log; integration test must verify (no docs published)
- CGEventPostToPid mouse delivery on macOS 26 Tahoe — A2; copyprogramming.com hints at issues; Phase 2 Chess test will confirm

### Reference MCP server shapes (D-28 verified)

- [github.com/modelcontextprotocol/servers/blob/main/src/filesystem/index.ts](https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/index.ts) — 14 separate tools pattern
- [github.com/CursorTouch/Windows-MCP/blob/main/src/windows_mcp/tools/input.py](https://github.com/CursorTouch/Windows-MCP/blob/main/src/windows_mcp/tools/input.py) — Click/Type/Scroll/Move/Shortcut pattern (matches our shape)

## Metadata

**Confidence breakdown:**
- Standard stack (cdp-use, uitag, py-applescript): HIGH — all live-verified PyPI 2026-04-30
- Architecture patterns (anyio race, idempotency, channel registry): HIGH — direct reads of Phase 1 source + anyio docs
- T2 CDP Slack workspace filtering: MEDIUM — D-24 documented; first integration test must confirm
- T4 uitag detection adapter for non-UI canvases (Chess.app): MEDIUM — uitag trained on UI elements, not 3D Metal; fallback chain documented in Open Question 5
- C3 CGEventPostToPid mouse delivery on Tahoe: MEDIUM — community reports "doesn't always work"; Phase 2 integration test must validate
- MCP tool schemas (D-29): HIGH — 6 schemas explicit; no upstream conflicts identified

**Research date:** 2026-04-30
**Valid until:** 2026-05-30 (30 days for stable; cdp-use, uitag, py-applescript all stable releases)

---

*Researched: 2026-04-30 for Phase 2 (Translators + Racing) by gsd-research-phase. Phase boundaries and decisions locked in 02-CONTEXT.md (D-01..D-31). Planner: produce per-translator plans with the channel-orchestrator-MCP wave order in §Summary.*
