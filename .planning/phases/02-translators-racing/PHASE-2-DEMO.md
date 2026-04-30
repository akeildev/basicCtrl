# Phase 2 Demo — Operator Runbook

**Goal:** Run the 5 Phase 2 success-criteria integration tests end-to-end on Akeil's Mac and walk the manual smoke checks Phase 2 ships against. If every section passes, Phase 2 is ready to hand off to Phase 3 (Failure classifier + 5-branch recovery).

This document mirrors the structure of `PHASE-1-DEMO.md`: pre-flight, demo invocation, automated tests, manual checks, pitfall mitigation references, recovery procedures, phase-exit checklist.

Phase 2 ships 5 protocol translators (T1 AX / T2 CDP / T3 AppleScript / T4 Vision/uitag/ocrmac / T5 Pixel), 5 racing action channels (C1 SkyLight-as-public-CGEvent / C2 AX kAXPress / C3 CGEvent.postToPid / C4 AppleScript / C5 CDP Input.dispatchMouseEvent), the Race Orchestrator, atomic idempotency tokens, the AppleScript 500ms stagger, the top-12 app association map, and 6 MCP tools (`click_with_healing` extended + `type/scroll/set_value/key_combo_with_healing` siblings + `send_destructive`).

---

## Pre-flight (one-time setup)

```bash
# 1. Phase 1 prerequisites — re-confirm before Phase 2
make doctor   # All rows [OK] (Python 3.12, uv, Postgres, AXIsProcessTrusted)

# 2. Phase 2 dependencies (already in pyproject.toml from Plan 02-01)
uv sync       # Pulls cdp-use 1.4.5, uitag 0.6.0, py-applescript 1.0.3, transformers >= 5

# 3. uitag's bundled YOLO11 weights download on first import (~18 MB)
uv run python -c "from uitag import run_pipeline; print('uitag ok')"

# 4. Real-app prerequisites (manual; required for SC #1 / SC #2)

# Slack with remote-debugging port (SC #1):
pkill -9 Slack; sleep 1
open -a "Slack" --args --remote-debugging-port=9222
# Wait 5s, then verify:
curl -s http://localhost:9222/json/version | head -c 300

# Pages with at least one document open (SC #2):
open -a Pages
# Manually open or create any document (Phase 2 fixture skips if no doc).

# Chess.app — pre-installed on every macOS (SC #3); fixture launches automatically.

# 5. TCC Accessibility for the test runner (Phase 1 already covered this; re-confirm)
# System Settings → Privacy & Security → Accessibility → Python interpreter visible.
```

---

## Run the demo (per success criterion)

There is no single "Phase 2 demo" script — Phase 2 ships 5 SC integration tests that ARE the demo. Run them sequentially:

### SC #1 — T2 CDP wins on Slack (D-25)

```bash
uv run pytest -v -s -m integration tests/integration/test_slack_t2_wins.py
```

Expected output excerpt:

```
test_t2_wins_on_slack_message_click PASSED
  winner.tier = T2
  winner.channel = C5
  losers count = 4 (status in {cancelled, skipped})
  near_miss_duplicate_count = 0
```

If `slack_cdp_ws` returns None, the test SKIPS with a relaunch instruction. Re-run after relaunching Slack.

### SC #2 — T3 AppleScript wins on Pages (D-26)

```bash
uv run pytest -v -s -m integration tests/integration/test_pages_t3_wins.py
```

Expected output excerpt:

```
test_t3_wins_on_pages_format_toolbar_click PASSED
  winner.tier = T3
  AS stagger >= 400ms verified (D-15: 500ms default ± slop)
  >= 1 race_loser event observed (full 5-channel fan-out per WARN-4)
```

If Pages.app has no document open, the test SKIPS with an instruction.

### SC #3 — T4 SoM grounds + T5/C3 fires on Chess.app (D-27)

```bash
uv run pytest -v -s -m integration tests/integration/test_chess_t4_t5.py
```

Expected output excerpt:

```
test_t4_t5_on_chess_e2_to_e4 PASSED
  [SC #3 first-run] uitag image dimensions: (image_width=2880, image_height=1800)  # A1 Retina verification
  e2 click winner.tier in {T4, T5}, channel in {C1, C3}
  e4 click winner.tier in {T4, T5}, channel in {C1, C3}
  pawn moved (post-screenshot dHash differs)
```

The Chess.app fixture launches Chess automatically; cleanup terminates it. First-run uitag inference may take 1-5s (Pitfall C — wrapped in asyncio.to_thread).

### SC #4 — 100 racing fires, 0 double-clicks (idempotency stress)

```bash
uv run pytest -v -s -m integration tests/integration/test_race_idempotency_stress.py
```

Expected output excerpt:

```
test_100_racing_fires_zero_double_clicks PASSED
  count(claim_events) == 100
  count(race_winner) == 100
  count(near_miss_duplicate) == 0
  per-action C1/C3 dedup: <= 1 of {C1, C3} fired (WARN-6)
```

This is the core T-2-07 idempotency-atomicity ship gate. If `near_miss_duplicate` appears, the asyncio.Lock around `IdempotencyTokenStore._claims` failed under load.

### SC #5 — Top-12 association matches (unit, no apps required)

```bash
uv run pytest -v -m "not integration" tests/unit/profile/test_top_12_priority.py
```

Expected: all 24 parametrized cases pass (12 D-21 entries + 3 Electron cdp_after_relaunch flags + 9 structural defenses).

---

## Run automated tests (full Phase 2 suite)

```bash
# Unit tests (~30s; no real apps needed)
uv run pytest -x -q -m "not integration and not manual" tests/unit/

# Integration tests skipping manual ones (~60s; needs Calculator + Chess autostart)
uv run pytest -x -v -m "integration and not manual" tests/integration/

# Manual integration tests (Slack relaunched + Pages running prerequisites)
uv run pytest -x -v -m "integration and manual" tests/integration/

# Full Phase 1 + Phase 2 suite
uv run pytest -x --tb=short tests/
```

To skip integration tests on dev hosts without macOS apps:

```bash
SKIP_INTEGRATION=1 uv run pytest -q tests/
```

---

## Manual smoke checks (1× per phase ship)

Per `02-VALIDATION.md` "Manual-Only Verifications":

### Slack CDP relaunch (D-24, P8)

1. Confirm Slack is NOT running with `--remote-debugging-port=9222`:
   ```bash
   curl -s http://localhost:9222/json/version    # should fail or return nothing
   ```
2. Run `pytest tests/integration/test_slack_t2_wins.py`. Expect: SKIP with relaunch instruction.
3. Relaunch:
   ```bash
   pkill -9 Slack; sleep 1
   open -a "Slack" --args --remote-debugging-port=9222
   ```
4. Wait 5 seconds. Run the same pytest command. Expect: PASSED with `winner.tier == "T2"`.

### Pages document open (D-26)

1. Quit Pages.app entirely.
2. Run `pytest tests/integration/test_pages_t3_wins.py`. Expect: SKIP with "open Pages with a document" instruction.
3. Open Pages, create any new document.
4. Re-run. Expect: PASSED.

### Cursor warp absence (T-2-05)

1. Run `pytest tests/integration/test_chess_t4_t5.py`.
2. While the test runs, watch the cursor on screen — it MUST NOT warp to the Chess board (Phase 2 uses CGEvent.postToPid only; never CGEvent.post or kCGSessionEventTap).
3. If the cursor visibly jumps during the test, T-2-05 mitigation broke — file a regression.

### Race telemetry visible in action_log

1. Run any of SC #1 / #2 / #3.
2. Inspect the per-session action log:
   ```bash
   ls -t ~/.cua/sessions/ | head -1
   tail -50 ~/.cua/sessions/<latest>/action_log.ndjson | jq 'select(.event | startswith("race_"))'
   ```
3. Expect: one `race_winner` event + N `race_loser` events per click.

---

## Known limitations

| Limitation | Source | Impact |
|------------|--------|--------|
| **A1 Retina assumption** (uitag returns physical pixels) | T-2-04 | Verified at first SC #3 run via `(image_width, image_height)` print. If `image_width != display_width * 2.0` on Retina, divide by `scale_factor` in T4 before C3 fire. |
| **A2 CGEventPostToPid quirks** (drops to backgrounded apps) | Pitfall G | C1/C3 channels rely on target window being foreground. SC #3 verifies via dHash diff. For background apps, fall back to AppleScript C4 or surface a foreground prompt. |
| **P8 Electron CDP launch-only** | D-24 | Slack/Cursor/Obsidian require manual `--remote-debugging-port=9222` relaunch. MCP healing tool prompts user once per session; never silently relaunches. |
| **AppleScript 500ms stagger** | D-15, P5 | C4 always trails C2/C5 by 500ms. Acceptable when faster channels exist; SC #2 specifically tests AS-wins-anyway when AX/CDP unavailable on Pages canvas. |
| **MacPaw/Screen2AX deferred** | D-06 | Not on PyPI + pyobjc 10.3 conflict. uitag covers the same need. Re-evaluate if uitag's flat detection list proves insufficient on real workloads. |
| **Tahoe SCScreenshotManager** | Pitfall H | 1-5% capture-failure rate on macOS 26. Phase 1 L1 retry path covers; T4 reuses. |

---

## Pitfalls verified mitigated

| Pitfall | Mitigation file | Tests / Demo evidence |
|---------|-----------------|-----------------------|
| **Pitfall A** (anyio shield=True breaks race-cancel) | `cua_overlay/actions/race_orchestrator.py:race_first_complete` (CancelScope shield=False) | `test_race_orchestrator.py::test_race_first_complete_winner_idx_zero_cancels_loser` |
| **Pitfall B** (cdp-use without flatten=True hangs) | `cua_overlay/translators/t2_cdp.py` (Target.attachToTarget params={"flatten": True}) | `test_t2_cdp.py` (Plan 02-06) — workspace filter test |
| **Pitfall C** (uitag blocks asyncio loop 1-5s) | `cua_overlay/translators/t4_vision.py:_run_uitag` (asyncio.to_thread wrap) | `test_t4_vision.py::test_run_uitag_runs_in_to_thread` |
| **Pitfall D** (Slack helper-process attaches wrong target) | `cua_overlay/translators/t2_cdp.py:_pick_workspace_target` (type=page AND url~/.slack.com/) | `test_slack_t2_wins.py` (SC #1) |
| **Pitfall E** (py-applescript recompiles every call 50-200ms) | `cua_overlay/translators/t3_applescript.py` (module-level dict cache) | `test_t3_applescript.py` (Plan 02-07) |
| **Pitfall F** (asyncio.Lock first-claimer-wins) | DESIGN — D-17 says first-to-call try_claim wins; OS-delivery timing is what verifier measures | `test_race_idempotency_stress.py` (SC #4) — 0 near_miss_duplicate after 100 fires confirms |
| **Pitfall G** (CGEvent.postToPid sometimes drops to backgrounded apps) | `cua_overlay/actions/channels/c1_skylight.py + c3_cgevent.py` (foreground-only fallback documented) | `test_chess_t4_t5.py` (SC #3) — Chess foreground confirmed via screenshot dHash diff |
| **Pitfall H** (Tahoe SCScreenshotManager 1-5% capture failure) | Phase 1 L1 capture path retries; T4 reuses | Phase 1 already validates |
| **T-2-05** (CGEvent global cursor warp) | `cua_overlay/actions/channels/c1_skylight.py + c3_cgevent.py` use CGEventPostToPid only | grep verified — no `kCGSessionEventTap`; manual smoke (cursor warp absence) above |
| **T-2-09** (race policy enforcement) | `cua_overlay/actions/race_policy.py:resolve_race_policy` + `cua_overlay/mcp_server/healing_tools.py:send_destructive` no-race_policy | `test_race_orchestrator.py::test_race_policy_destructive_force_single_channel` + `test_healing_tools_v2.py::test_send_destructive_always_single_channel` |

---

## Failure recovery

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `slack_cdp_ws fixture: Slack not running on localhost:9222` | Slack relaunched without flag, or quit | `pkill -9 Slack; open -a Slack --args --remote-debugging-port=9222` |
| `pages_running fixture: Pages has no document open` | Quit Pages or no documents | `open -a Pages`, create a new document |
| `chess_launcher fixture: Chess.app not found` | Removed/disabled by user (rare on macOS) | `ls /System/Applications/Chess.app` to confirm |
| SC #3 PASS but `winner.tier == None` (no winner) | uitag returned no detections AND ocrmac fallback empty | Per Open Question 5: add geometric fallback (8x8 grid in known viewport) — Phase 3 spike if recurring |
| SC #4 fails with `near_miss_duplicate > 0` | asyncio.Lock contention bug under stress | Inspect `tests/unit/actions/test_idempotency.py` for atomicity coverage; re-run with `pytest -p no:randomly` to rule out random-order races |
| `image_width == image_height * 2` and clicks land off-target | A1 Retina assumption WRONG (uitag returns physical pixels, not logical points) | Apply `/scale_factor` divisor in `cua_overlay/translators/t4_vision.py:_detection_to_uielement` |
| `kAXErrorInvalidUIElement` from T1 mid-fire | Stale AXUIElement after window re-render | Phase 1 fingerprint module re-resolves; if persistent, force `T1.validate()` re-check before fire (already wired) |
| Cursor jumps visibly during test | T-2-05 broke — wrong CGEvent post mode used | `grep -r 'kCGSessionEventTap\|CGEventPost(' cua_overlay/actions/channels/` — must return zero non-comment matches |
| MCP host (Claude Code) shows old 1-tool surface | `register_healing_tools` 4-arg signature change in Plan 02-11 not applied | Confirm `main.py` calls `register_healing_tools(proxy, upstream, deps, race_orch)` with 4 args |

---

## Phase exit checklist

- [ ] `make test` exits 0 (all unit tests pass).
- [ ] `make doctor` all rows [OK] (Phase 1 prerequisites still healthy).
- [ ] `pytest -m integration tests/integration/test_slack_t2_wins.py` PASSED (SC #1).
- [ ] `pytest -m integration tests/integration/test_pages_t3_wins.py` PASSED (SC #2).
- [ ] `pytest -m integration tests/integration/test_chess_t4_t5.py` PASSED (SC #3).
- [ ] `pytest -m integration tests/integration/test_race_idempotency_stress.py` PASSED (SC #4).
- [ ] `pytest tests/unit/profile/test_top_12_priority.py` PASSED (SC #5).
- [ ] Manual cursor-warp-absence smoke check completed (T-2-05).
- [ ] Manual race-telemetry-visible smoke check completed (NDJSON contains race_winner + race_loser).
- [ ] Manual Slack relaunch smoke check completed (D-24 P8).
- [ ] Manual Pages document smoke check completed (D-26).
- [ ] Per-plan SUMMARY.md files exist for plans 02-01 through 02-12 (`ls .planning/phases/02-translators-racing/02-*-SUMMARY.md`).
- [ ] No edits under `libs/cua-driver/Sources/` (Phase 1 hard rule preserved).
- [ ] `grep -r 'kCGSessionEventTap' cua_overlay/actions/channels/` returns zero non-comment matches (T-2-05 enforcement).
- [ ] `grep -r 'shield=True' cua_overlay/actions/race_orchestrator.py` returns zero matches (Pitfall A).
- [ ] PHASE-2-DEMO.md (this file) reviewed end-to-end.

If every box ticks, Phase 2 is ready to hand off to Phase 3 (Failure classifier + 5-branch recovery).
