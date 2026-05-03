---
phase: 02-translators-racing
verified: 2026-04-30T12:00:00Z
status: human_needed
score: 1/5
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 1/5
  gaps_closed: []
  gaps_remaining: []
  regressions:
    - "key_combo D-12 wiring gap found: action_type='key_combo' not in RACE_ALLOWLIST; cmd+c/cmd+v default to SINGLE_CHANNEL"
    - "T1 _MAX_DEPTH=6 deviates from CLAUDE.md hard rule (3 levels max) — documented but not overridden"
    - "T1 resolution burst at 200/sec deviates from CLAUDE.md 20/sec rule — documented but not overridden"
human_verification:
  - test: "Run SC #1: pkill -9 Slack; sleep 1; open -a Slack --args --remote-debugging-port=9222; wait 5s; uv run pytest -v -s -m integration tests/integration/test_slack_t2_wins.py"
    expected: "winner.tier=='T2', winner.channel=='C5', >=4 losers with status in {cancelled,skipped}, near_miss_duplicate_count==0"
    why_human: "Requires live Slack with --remote-debugging-port=9222. Marked integration+manual. T2 CDP needs real WS socket + workspace renderer."
  - test: "Run SC #2: Open Pages.app with any document; uv run pytest -v -s -m integration tests/integration/test_pages_t3_wins.py"
    expected: "winner.tier=='T3', winner.channel=='C4', AS-fire >= earliest-loser-fire + 400ms, >=1 race_loser event"
    why_human: "Requires live Pages.app + document. 500ms stagger only verifiable against real wall-clock timestamps."
  - test: "Run SC #3: uv run pytest -v -s -m integration tests/integration/test_chess_t4_t5.py"
    expected: "action_e2.tier in ('T4','T5'), action_e2.channel in ('C1','C3'), pre/post L1Cheap dHash diff != 0"
    why_human: "Requires uitag YOLO11 model download + Screen Recording TCC + real Chess.app. A1 Retina coordinate mismatch observable only at runtime."
  - test: "Run SC #4: Open Calculator.app (TCC Accessibility grant required); uv run pytest -v -s -m integration tests/integration/test_race_idempotency_stress.py"
    expected: "count(claim_events)==100, count(race_winner)==100, count(near_miss_duplicate)==0, per-action len(cgevent_fires)<=1"
    why_human: "Requires live Calculator.app + TCC Accessibility grant for the pytest runner."
  - test: "Manual cursor-warp check: run any click_with_healing that routes C1 or C3; watch the screen cursor position"
    expected: "User cursor does NOT move; target element receives the click event"
    why_human: "T-2-05 (CGEventPostToPid vs CGEvent.post). Cursor stability is only observable by watching the screen."
---

# Phase 2: Translators + Racing — Verification Report

**Phase Goal:** Drive any of trycua's covered apps via the BEST translator for that bundle, racing 5 channels in parallel with atomic idempotency — no double-clicks, no double-submits, ever.
**Verified:** 2026-04-30
**Status:** human_needed
**Re-verification:** Yes — previous report was an orchestrator spot-check (2026-04-30). This is the full goal-backward verification.

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Click on Slack message: T2 CDP wins; T1/T3/T4/T5 cancelled cleanly with no second-fire | ? HUMAN NEEDED | Implementation is complete and wired: T2CDPTranslator resolves via cdp-use with D-24 workspace filter; C5CDPInputChannel fires mousePressed+mouseReleased; RaceOrchestrator cancel_event.set() on first winner; IdempotencyTokenStore blocks second claims. Integration test `test_slack_t2_wins.py` is substantive (not stub). Cannot verify without live Slack relaunched with --remote-debugging-port=9222. |
| 2 | Click on Pages toolbar: T3 AppleScript wins (in own thread pool, staggered 500ms after T1/T2/T5) | ? HUMAN NEEDED | Implementation complete: T3AppleScriptTranslator uses dedicated ThreadPoolExecutor(max_workers=2, thread_name_prefix='cua-as'); C4 stagger enforced at race_orchestrator._staggered_fire with AS_STAGGER_MS_DEFAULT=500. Integration test `test_pages_t3_wins.py` substantive (uses action_type='click' per WARN-4 so all 5 channels fan out). Cannot verify without live Pages.app with document. |
| 3 | Click on game canvas (non-AX app): T4 Vision/uitag SoM grounds; T5 CGEvent fires | ? HUMAN NEEDED | Implementation complete: T4VisionTranslator runs uitag.run_pipeline in asyncio.to_thread with ocrmac fallback; T5 delegates to T4; C1/C3 fire via CGEventPostToPid. Integration test `test_chess_t4_t5.py` substantive with pre-flight Retina check. Cannot verify without uitag + Chess.app + Screen Recording TCC. |
| 4 | Zero double-clicks across 100 racing fires — atomic token written BEFORE fire; destructive actions single-channel | ? HUMAN NEEDED | Implementation complete: IdempotencyTokenStore asyncio.Lock try_claim before syscall; DuplicateReceipt 2s ring buffer; resolve_race_policy forces SINGLE_CHANNEL for D-11 verbs. Unit test suite for idempotency passes (5 tests incl. concurrent claim). Stress test `test_race_idempotency_stress.py` substantive (100 fires on Calculator). Cannot run without live Calculator + TCC grant. |
| 5 | Per-app priority matches association map for top 12 apps; classifier never silently relaunches Electron apps | VERIFIED | `test_top_12_priority.py` parametrized over all 12 D-21 bundle IDs with stubbed probes. classify() returns KNOWN_APPS[bid].translator_priority for all 12. Slack/Cursor/Obsidian cdp_after_relaunch=True verified. `test_no_silent_relaunch_for_electron_apps` reads classifier.py source and asserts no subprocess.run near 'relaunch'. KNOWN_APPS has 17 entries (12 D-21 + 5 D-22 bonus). |

**Score:** 1/5 programmatically verifiable (SC #5). 4/5 require human testing with real apps.

### Deferred Items

No items deferred — all gaps are Phase 2 scope. No later phase in ROADMAP.md covers them.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `basicctrl/translators/t1_ax.py` | T1 AX translator | VERIFIED | 371 lines, substantive. TokenBucket rate_limiter, walker via AXUIElementCopyAttributeValue in asyncio.to_thread. resolve + validate implemented. |
| `basicctrl/translators/t2_cdp.py` | T2 CDP translator | VERIFIED | 245 lines. _discover_ws_url probes 9222-9225. _pick_workspace_target D-24 Slack/Cursor/Obsidian filter. Pitfall B flatten=True enforced. |
| `basicctrl/translators/t3_applescript.py` | T3 AppleScript translator | VERIFIED | 204 lines. ThreadPoolExecutor(max_workers=2, thread_name_prefix='cua-as'). execute() via loop.run_in_executor(self._exec). Compiled script cache. |
| `basicctrl/translators/t4_vision.py` | T4 Vision translator | VERIFIED | 299 lines. uitag.run_pipeline in asyncio.to_thread. ocrmac fallback. Retina (image_width, image_height) logging per A1. |
| `basicctrl/translators/t5_pixel.py` | T5 Pixel translator | VERIFIED | 107 lines. Delegates to T4.resolve(). Pre-fire phash via imagehash.phash in extras. validate() checks grounded_bbox. |
| `basicctrl/actions/channels/c1_skylight.py` | C1 channel — CGEventPostToPid | VERIFIED | 93 lines. Uses Quartz.CGEventPostToPid (NOT CGEvent.post). cancel_event.is_set() pre-syscall. try_claim before syscall. |
| `basicctrl/actions/channels/c2_ax_press.py` | C2 channel — AX kAXPress | VERIFIED | 118 lines. AXUIElementPerformAction in asyncio.to_thread. Claim → cancel-check → validate ax_element → fire. |
| `basicctrl/actions/channels/c3_cgevent.py` | C3 channel — CGEventPostToPid | VERIFIED | 76 lines. Delegates to _post_left_click from C1. Claim → cancel → fire. |
| `basicctrl/actions/channels/c4_applescript.py` | C4 channel — AS via T3 executor | VERIFIED | 154 lines. Reads target.as_target_spec. Delegates to T3.execute(). No osascript subprocess. |
| `basicctrl/actions/channels/c5_cdp_input.py` | C5 channel — CDP Input.dispatchMouseEvent | VERIFIED | 167 lines. Re-opens CDPClient at ws_url from target.extras. mousePressed + mouseReleased pair at bbox center. |
| `basicctrl/actions/race_orchestrator.py` | Race orchestrator | VERIFIED | 377 lines. anyio.create_task_group via race_first_complete. _staggered_fire for C4 (500ms). axmgr.expect before fan-out. cancel_event.set() on first winner. 12-step contract matches D-13..D-19. |
| `basicctrl/actions/idempotency.py` | IdempotencyTokenStore | VERIFIED | 98 lines. asyncio.Lock try_claim. is_claimed lock-free peek. NDJSON trace via SessionWriter. D-17: claim written BEFORE syscall. |
| `basicctrl/actions/race_policy.py` | RacePolicy enum + dispatch | VERIFIED | 145 lines. RACE_ALLOWLIST, SINGLE_CHANNEL_ALLOWLIST, DESTRUCTIVE_COMBOS, SAFE_RACE_COMBOS. T-2-09 destructive override. NOTE: 'key_combo' bare string not in RACE_ALLOWLIST — D-12 wiring gap (see anti-patterns). |
| `basicctrl/actions/duplicate_receipt.py` | DuplicateReceipt — 2s ring buffer | VERIFIED | 78 lines. deque popleft pruning. record() returns is_duplicate. near_miss_duplicate structlog event. |
| `basicctrl/actions/channel_registry.py` | ChannelRegistry | VERIFIED | 110 lines. TIER_TO_CHANNEL_DEFAULT T1→C2..T5→C3. select() handles RACE (all tiers) vs SINGLE_CHANNEL (first tier). tier_for_channel reverse lookup. |
| `basicctrl/profile/known_apps.py` | Top-12 + 5 bonus association map | VERIFIED | 221 lines. 17 entries. cdp_after_relaunch=True for Slack/Cursor/Obsidian. Chess T4/T5. Pages T3/T1/T4. |
| `basicctrl/mcp_server/healing_tools.py` | 6 MCP healing tools (D-29) | VERIFIED | 363 lines. click_with_healing extended, 5 new siblings. send_destructive has no race_policy param (inspect.signature verified in tests). T-2-09 three-layer defense. RaceOrchestrator.execute wired in all 6 tools. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| T1AXTranslator.validate | TokenBucket.acquire | self._bucket.acquire(pid) | WIRED | Steady-state bucket; resolution burst uses self._walk_bucket (200/sec — see anti-patterns). |
| T2CDPTranslator.resolve | CDPClient (cdp-use) | Lazy import inside resolve() | WIRED | `from cdp_use.client import CDPClient`. D-03 confirmed: no browser-harness import anywhere in file. |
| T3AppleScriptTranslator.execute | applescript.AppleScript | _sync() on loop.run_in_executor(self._exec) | WIRED | Dedicated cua-as ThreadPoolExecutor. Never asyncio.to_thread (different pool). |
| T4VisionTranslator._run_uitag | uitag.run_pipeline | asyncio.to_thread(_sync) | WIRED | Pitfall C mitigation. Sync call in thread; Retina dims logged per A1. |
| T5PixelTranslator.resolve | T4VisionTranslator.resolve | Constructor injection + self._t4.resolve() | WIRED | main.py passes same T4 instance to both registry.register(t4) and T5PixelTranslator(t4=t4). |
| C4AppleScriptChannel.fire | T3AppleScriptTranslator.execute | self._t3.execute(target.as_target_spec) | WIRED | C4 reads as_target_spec built by T3.resolve(). Uses T3's cua-as pool. |
| C5CDPInputChannel.fire | CDPClient.send.Input.dispatchMouseEvent | Re-opens CDPClient(ws_url from extras) | WIRED | ws_url stashed by T2. Fires mousePressed + mouseReleased pair at grounded_bbox center. |
| RaceOrchestrator.execute | resolve_race_policy | effective = resolve_race_policy(race_policy, action_type) — step 1 | WIRED | Before fan-out per T-2-09. |
| RaceOrchestrator.execute | IdempotencyTokenStore | ch.fire(action, target, self._store, cancel_event) | WIRED | Channels call store.try_claim BEFORE syscall (D-17). |
| RaceOrchestrator.execute | AXObserverManager.expect | await self._axmgr.expect(...) before channel fan-out | WIRED | Subscribe-before-fire Phase 1 hard rule honored. |
| MCP healing_tools | RaceOrchestrator.execute | race_orch.execute(...) in each tool body | WIRED | All 6 tools route through orchestrator. register_healing_tools takes race_orch as 4th arg. |
| key_combo_with_healing | race_policy._classify_intrinsic (D-12 RACE) | action_type='key_combo' for cmd+c/cmd+v | NOT WIRED | 'key_combo' is not in RACE_ALLOWLIST. Falls through to conservative SINGLE_CHANNEL. D-12 intent not honored. |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| T1AXTranslator | nodes (UIElement, ax_ref) | AXUIElementCopyAttributeValue in asyncio.to_thread | Yes — live AX API calls gated by TokenBucket | FLOWING |
| T2CDPTranslator | node_id, content_quad | CDP DOM.querySelector + DOM.getBoxModel via cdp-use | Yes — live CDP wire calls | FLOWING |
| T3AppleScriptTranslator | as_target_spec | _build_target_spec returns real tell-block string | Yes — AppleScript executes real verb at fire time | FLOWING |
| T4VisionTranslator | detections | CGWindowListCreateImage → uitag.run_pipeline | Yes — real screenshot then real YOLO11 inference | FLOWING |
| IdempotencyTokenStore | _claims dict | asyncio.Lock-guarded try_claim | Yes — in-memory + NDJSON trace | FLOWING |
| DuplicateReceipt | _buffer deque | record() called from RaceOrchestrator step 11 | Yes — real post-fire receipts with monotonic timestamps | FLOWING |

---

## Behavioral Spot-Checks

Step 7b: SKIPPED for SCs #1-#4 — require live macOS apps and TCC grants. SC #5 is verified via 24 unit tests in `test_top_12_priority.py` with stubbed probes (deterministic, no live apps needed).

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| TRANS-01 | 02-05, 02-12 | T1 AX translator | SATISFIED | t1_ax.py (371 lines). Phase 1 TokenBucket + walker. C2 fires AXPress. Unit tests: test_t1_ax.py. |
| TRANS-02 | 02-06, 02-12 | T2 CDP translator | SATISFIED | t2_cdp.py (245 lines). cdp-use 1.4.5. D-24 workspace filter. C5 fires dispatchMouseEvent. |
| TRANS-03 | 02-07, 02-12 | T3 AppleScript translator | SATISFIED | t3_applescript.py (204 lines). Dedicated ThreadPoolExecutor. C4 reuses T3 executor. |
| TRANS-04 | 02-08, 02-12 | T4 Vision translator | SATISFIED | t4_vision.py (299 lines). uitag + ocrmac. asyncio.to_thread for sync pipeline. Screen2AX deferred per D-06 (rationale documented). |
| TRANS-05 | 02-09, 02-12 | T5 Pixel translator | SATISFIED | t5_pixel.py (107 lines). Delegates to T4. Pre-fire phash. C1/C3 fire via CGEventPostToPid. |
| ACT-01 | 02-04, 02-12 | Channel registry | SATISFIED | channel_registry.py. TIER_TO_CHANNEL_DEFAULT. select() RACE/SINGLE_CHANNEL paths. |
| ACT-02 | 02-10, 02-12 | Race orchestrator | SATISFIED | race_orchestrator.py (377 lines). anyio task group + race_first_complete. 12-step contract. |
| ACT-03 | 02-02, 02-12 | Atomic idempotency tokens | SATISFIED | idempotency.py asyncio.Lock. NDJSON trace. DuplicateReceipt 2s buffer. |
| ACT-04 | 02-02, 02-12 | Race policy + interference mitigations | PARTIALLY SATISFIED | RacePolicy enum + resolve_race_policy + T-2-09 override + AS stagger + AX rate-limit + pre-action validity. Gap: D-12 key_combo safe-race dispatch not wired (see anti-patterns). |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `basicctrl/actions/race_policy.py` | 36-44 | `RACE_ALLOWLIST` does not include `'key_combo'` | Blocker | `healing_tools.key_combo_with_healing` dispatches `action_type='key_combo'` for cmd+c/cmd+v, but this string is not in RACE_ALLOWLIST. Falls through to conservative SINGLE_CHANNEL default. D-12 intent (safe-race combos should race) not reached via the MCP surface. Functionally safe (conservative), but D-12 is violated. |
| `basicctrl/translators/t1_ax.py` | 53 | `_MAX_DEPTH = 6` | Warning | Violates CLAUDE.md literal rule "Always depth-limited (3 levels max)". Code provides engineering justification: Calculator buttons are at depth 5 on macOS 26 Tahoe; 200-node cap is the load-bearing safety bound; this is a one-shot resolution walk. The rule's intent (prevent Safari-scale 15-20s hangs) is honored by the node cap. The deviation is documented, not silent. |
| `basicctrl/translators/t1_ax.py` | 63 | `_RESOLUTION_BUCKET_RATE = 200.0` | Warning | Exceeds CLAUDE.md "Never poll AX at >20 calls/sec/pid" literal rule. Code justifies as one-shot burst (<100ms to complete 200-node walk), not sustained polling. cmux #2985 stall risk is from sustained >30/sec, not a 100ms burst. Documented, not silent. |

**Stub classification:** The `return []` instances in t1_ax.py and t4_vision.py are defensive failure paths (HIServices ImportError, uitag pipeline error) — not stub implementations. Real data flows when imports succeed.

---

## Human Verification Required

### 1. SC #1 — Slack T2 CDP Wins (D-25)

**Test:** `pkill -9 Slack; sleep 1; open -a "Slack" --args --remote-debugging-port=9222`. Wait 5s. Verify: `curl -s http://localhost:9222/json/version`. Then: `uv run pytest -v -s -m integration tests/integration/test_slack_t2_wins.py`
**Expected:** `winner.tier == 'T2'`, `winner.channel == 'C5'`, `>=4 losers` with status in `{cancelled, skipped}`, `near_miss_duplicate_count == 0`
**Why human:** Requires live Slack relaunched with --remote-debugging-port=9222 (P8 — Electron CDP is launch-only). Test marked `integration + manual`.

### 2. SC #2 — Pages T3 AppleScript Wins with 500ms Stagger (D-26)

**Test:** Open Pages.app and any document. Then: `uv run pytest -v -s -m integration tests/integration/test_pages_t3_wins.py`
**Expected:** `winner.tier == 'T3'`, `winner.channel == 'C4'`, AS-fire-timestamp >= earliest-loser + 400ms (D-15 slop), `>=1 race_loser` event (full 5-channel fan-out per WARN-4)
**Why human:** Requires live Pages.app with document. 500ms stagger can only be verified against real wall-clock timestamps from the AS ThreadPool.

### 3. SC #3 — Chess T4/T5 Ground + Fire + Pawn Moves (D-27)

**Test:** `uv run pytest -v -s -m integration tests/integration/test_chess_t4_t5.py`
**Expected:** `action_e2.tier in ('T4','T5')`, `action_e2.channel in ('C1','C3')`, pre/post `L1Cheap.snapshot` dHash diff `!= 0` (pawn moved)
**Why human:** Requires uitag YOLO11 model (~18 MB download). Requires Screen Recording TCC. A1 Retina coordinate mismatch surfaces only at runtime via printed (image_width, image_height). Pitfall G (CGEventPostToPid to backgrounded app) only verifiable live.

### 4. SC #4 — 100 Racing Fires, Zero Double-Clicks

**Test:** Open Calculator.app. Then: `uv run pytest -v -s -m integration tests/integration/test_race_idempotency_stress.py`
**Expected:** `count(claim_events)==100`, `count(race_winner)==100`, `count(near_miss_duplicate)==0`, per-action `len(cgevent_fires) <= 1`
**Why human:** Requires Calculator.app + Accessibility TCC grant for the pytest runner binary.

### 5. Manual Cursor-Warp Absence Check (T-2-05)

**Test:** Run any `click_with_healing` call that routes through C1 or C3 channels. Watch the cursor on screen during execution.
**Expected:** User cursor stays in its resting position; the target element in the app receives the click event.
**Why human:** CGEventPostToPid vs CGEvent.post distinction is only observable by watching the screen — no programmatic assertion captures cursor stability in the overlay.

---

## Gaps Summary

**One functional gap found:**

**D-12 key_combo safe-race dispatch wiring gap** — `healing_tools.key_combo_with_healing` dispatches `action_type='key_combo'` for cmd+c/cmd+v (safe-race per D-12), but `race_policy._classify_intrinsic` only recognizes key combos via the `"key_combo:<combo>"` prefix format. The bare string `'key_combo'` is not in `RACE_ALLOWLIST`, so it falls through to the conservative `SINGLE_CHANNEL` default.

The fix is one of:
- Add `"key_combo"` to `RACE_ALLOWLIST` in `race_policy.py`
- Change `healing_tools.py` to dispatch `action_type=f"key_combo:{combo_lower}"` which the existing `_classify_intrinsic` key_combo-prefix handler already handles correctly

Functionally safe (single-channel is conservative), but D-12 intent is not honored via the MCP surface.

**Two CLAUDE.md hard-rule deviations (Warning, documented in source):**
- T1 `_MAX_DEPTH = 6` vs rule "3 levels max" — documented with sound engineering rationale
- T1 resolution burst 200/sec vs rule "20 calls/sec/pid" — documented as one-shot burst (<100ms), not sustained polling

These are not silent deviations; the code explains the reasoning. Whether they require formal overrides (with `accepted_by` / `accepted_at`) or remain as engineering judgment calls is Akeil's decision.

---

_Verified: 2026-04-30_
_Verifier: Claude (gsd-verifier) — full goal-backward verification_
