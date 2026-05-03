---
phase: 2
slug: translators-racing
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-30
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: 02-RESEARCH.md §"Validation Architecture" (Wave 0 fixtures + 17 test files derived from 5 success criteria across 9 phase requirements TRANS-01..05, ACT-01..04).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x (already in `[project.optional-dependencies] dev`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (asyncio_mode=auto, markers=integration\|manual) |
| **Quick run command** | `uv run pytest -x --tb=short -m "not integration and not manual"` |
| **Full suite command** | `uv run pytest --tb=short` |
| **Estimated runtime** | ~30s (unit) / ~3min (full incl. integration) |

Markers in use:
- `@pytest.mark.integration` — requires real macOS app (Slack relaunched, Pages running, Chess.app available)
- `@pytest.mark.manual` — requires human gesture (Slack CDP relaunch confirmation dialog)

---

## Sampling Rate

- **After every task commit:** Run quick (unit-only) — `uv run pytest -x --tb=short -m "not integration and not manual"`
- **After every plan wave:** Run full — `uv run pytest --tb=short` (includes integration but skips manual)
- **Before `/gsd-verify-work`:** Full suite + manual UAT (Slack relaunch dialog) must all be green
- **Max feedback latency:** 30s for unit; 180s for full

---

## Per-Task Verification Map

> Filled by gsd-planner per wave. Each PLAN.md task lists `<verify_command>` and `<acceptance_criteria>`. This table is regenerated after planning by `gsd-tools nyquist build-table 2`.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-W0 | 01 | 0 | scaffolding | — | N/A | unit | `pytest tests/unit/test_translators_registry.py` | ❌ W0 | ⬜ pending |
| 02-01-01 | 01 | 1 | TRANS-01 | T-2-01 race ordering | T1 AX uses TokenBucket from Phase 1 (P2 mitigation) | unit | `pytest tests/unit/translators/test_t1_ax.py` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 1 | TRANS-02 | T-2-02 Slack helper-page filter | T2 CDP filters non-workspace pages | unit | `pytest tests/unit/translators/test_t2_cdp.py` | ❌ W0 | ⬜ pending |
| 02-03-01 | 03 | 1 | TRANS-03 | T-2-03 AS thread isolation | T3 AS runs on dedicated ThreadPool, never main loop | unit | `pytest tests/unit/translators/test_t3_applescript.py` | ❌ W0 | ⬜ pending |
| 02-04-01 | 04 | 1 | TRANS-04 | T-2-04 uitag bbox origin | T4 Vision normalizes uitag detections to UIElement | unit | `pytest tests/unit/translators/test_t4_vision.py` | ❌ W0 | ⬜ pending |
| 02-05-01 | 05 | 1 | TRANS-05 | T-2-05 CGEvent.postToPid no global warp | T5 Pixel uses postToPid (no cursor warp) | unit | `pytest tests/unit/translators/test_t5_pixel.py` | ❌ W0 | ⬜ pending |
| 02-06-01 | 06 | 2 | ACT-01 | T-2-06 channel registry | C1-C5 channels registered + dispatch by ChannelKind | unit | `pytest tests/unit/actions/test_channel_registry.py` | ❌ W0 | ⬜ pending |
| 02-07-01 | 07 | 2 | ACT-03 | T-2-07 idempotency atomicity | Token claimed BEFORE any channel fires; second claim returns Cancelled | unit | `pytest tests/unit/actions/test_idempotency.py` | ❌ W0 | ⬜ pending |
| 02-08-01 | 08 | 3 | ACT-02 | T-2-08 race-cancel correctness | First-verified wins; losers cancelled cleanly; no leaked AS subprocess | integration | `pytest tests/integration/test_race_orchestrator.py` | ❌ W0 | ⬜ pending |
| 02-09-01 | 09 | 3 | ACT-04 | T-2-09 race policy enforcement | submit/send/delete = single-channel; click/scroll/hover = race | unit | `pytest tests/unit/actions/test_race_policy.py` | ❌ W0 | ⬜ pending |
| 02-10-01 | 10 | 4 | MCP-02 ext | T-2-10 MCP schema | 6 tool schemas (click/type/scroll/set_value/destructive/key_combo) validate via Pydantic | unit | `pytest tests/unit/mcp/test_healing_tools_v2.py` | ❌ W0 | ⬜ pending |
| 02-11-01 | 11 | 5 | SC #1 (Slack T2) | — | Slack CDP wins; T1/T3/T4/T5 cancelled cleanly | integration | `pytest tests/integration/test_slack_t2_wins.py -m integration` | ❌ W0 | ⬜ pending |
| 02-11-02 | 11 | 5 | SC #2 (Pages T3) | — | Pages AS verb commits paragraph style | integration | `pytest tests/integration/test_pages_t3_wins.py -m integration` | ❌ W0 | ⬜ pending |
| 02-11-03 | 11 | 5 | SC #3 (Chess T4+T5) | — | uitag grounds e2/e4 → CGEvent fires | integration | `pytest tests/integration/test_chess_t4_t5.py -m integration` | ❌ W0 | ⬜ pending |
| 02-11-04 | 11 | 5 | SC #4 (idempotency stress) | — | 100 racing fires → 0 double-clicks | stress | `pytest tests/integration/test_race_idempotency_stress.py -m integration` | ❌ W0 | ⬜ pending |
| 02-11-05 | 11 | 5 | SC #5 (top-12 priorities) | — | Top-12 association map matches AppProfile.translator_priority for all 12 | unit | `pytest tests/unit/profile/test_top_12_priority.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

> All test files referenced in the verification map MUST be created (with stub or live test) before any Wave-1 task begins. This is the Nyquist gate: every plan task has a real test file.

- [ ] `tests/conftest.py` — extend with fixtures: `slack_cdp_ws`, `pages_running`, `chess_launcher`, `fake_idempotency_store`
- [ ] `tests/unit/test_translators_registry.py` — registry import + base class
- [ ] `tests/unit/translators/__init__.py` + 5 stubs:
  - `test_t1_ax.py` — T1 wraps Phase 1 ax/* (TRANS-01)
  - `test_t2_cdp.py` — T2 cdp-use attach + workspace filter (TRANS-02)
  - `test_t3_applescript.py` — T3 thread pool isolation (TRANS-03)
  - `test_t4_vision.py` — T4 uitag pipeline → UIElement (TRANS-04)
  - `test_t5_pixel.py` — T5 CGWindowList + postToPid (TRANS-05)
- [ ] `tests/unit/actions/__init__.py` + 3 stubs:
  - `test_channel_registry.py` — C1-C5 dispatch (ACT-01)
  - `test_idempotency.py` — token claim atomicity (ACT-03)
  - `test_race_policy.py` — read/mutate enforcement (ACT-04)
- [ ] `tests/unit/mcp/test_healing_tools_v2.py` — 6 tool schemas
- [ ] `tests/unit/profile/test_top_12_priority.py` — known_apps association
- [ ] `tests/integration/__init__.py` + 4 stubs:
  - `test_race_orchestrator.py` — race-cancel correctness (ACT-02)
  - `test_slack_t2_wins.py` — SC #1
  - `test_pages_t3_wins.py` — SC #2
  - `test_chess_t4_t5.py` — SC #3
  - `test_race_idempotency_stress.py` — SC #4

**Total Wave 0 files: 17 (12 unit + 4 integration + conftest extension).**

---

## Fixtures (Wave 0 — `tests/conftest.py` extension)

Phase 1's `tests/conftest.py` already provides `calculator_pid`. Phase 2 adds:

```python
@pytest.fixture
def slack_cdp_ws() -> str:
    """Returns ws URL for a Slack workspace renderer with --remote-debugging-port=9222.
    Skip test with skip_reason if Slack not running on port 9222.
    Manual fixture: human relaunches Slack with the flag once per session."""

@pytest.fixture
def pages_running() -> int:
    """Launches Pages.app via NSWorkspace if not running. Returns pid.
    Cleanup: leaves Pages running (avoids document-loss prompt)."""

@pytest.fixture
def chess_launcher() -> int:
    """Launches /System/Applications/Chess.app. Returns pid.
    Cleanup: terminates Chess.app process group."""

@pytest.fixture
def fake_idempotency_store() -> IdempotencyStore:
    """Returns an in-memory IdempotencyStore for unit tests
    (no SessionWriter NDJSON side-effects)."""
```

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Slack must be relaunched with `--remote-debugging-port=9222` for D-25 / SC #1 | TRANS-02 | P8 — Electron CDP is launch-only; cannot programmatically inject without Phase 6 DYLD; user must confirm restart of running app | `pkill -9 Slack; sleep 1; open -a "Slack" --args --remote-debugging-port=9222`. Wait 5s. Run integration test. |
| TCC Accessibility grant for basicCtrl Python interpreter | All TRANS/ACT | macOS TCC is per-binary user-grant — cannot be automated | System Settings → Privacy & Security → Accessibility → toggle on the Python.app or terminal binary running pytest |

---

## Success Threshold Mapping (Phase 2 → Roadmap success criteria)

| Roadmap SC | Test type | Fixture | Pass threshold |
|---|---|---|---|
| SC #1: T2 wins on Slack | integration | `slack_cdp_ws`, `fake_idempotency_store` | `winner.tier == "T2"` AND `count(loser_cancelled) == 4` AND `count(near_miss_duplicate) == 0` within 2s |
| SC #2: T3 wins on Pages | integration | `pages_running` | `winner.tier == "T3"` AND AS stagger 500ms verified via timing assert AND no main asyncio loop block |
| SC #3: T4+T5 fire on Chess | integration | `chess_launcher` | uitag returns ≥1 detection for "white pawn at e2" AND C3 CGEvent.postToPid emits event AND post-screenshot dHash differs from pre-screenshot |
| SC #4: 0 double-clicks across 100 racing fires | stress | `slack_cdp_ws` OR Calculator (use Calculator — fastest, no auth) | `count(claim_events) == 100` AND `count(near_miss_duplicate) == 0` AND `count(verified_events) == 100` |
| SC #5: Top-12 association matches | unit | none | For all 12 bundleIDs in `known_apps.py`, `AppProfile.translator_priority == known_apps[bid].priority` AND classifier never silently relaunches Slack/Cursor/Obsidian |

---

## Validation Sign-Off

- [ ] All tasks have `<verify_command>` or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING test file references (17 files)
- [ ] No watch-mode flags (pytest -f / --watch) in any verify command
- [ ] Feedback latency < 30s for unit, < 180s for full
- [ ] `nyquist_compliant: true` set in frontmatter (after Wave 0 complete)

**Approval:** pending — set to `approved 2026-MM-DD` once gsd-planner finalizes per-task `<verify_command>` and Wave 0 is green.
