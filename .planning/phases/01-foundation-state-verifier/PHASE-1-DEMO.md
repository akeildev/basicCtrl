# Phase 1 Demo — Operator Runbook

**Goal:** Run `python -m basicctrl.demo.calculator_click` end-to-end and walk the manual smoke checks that Phase 1 ships against. If every section passes, Phase 1 is ready to hand off to Phase 2.

This document is the single artifact Akeil needs: pre-flight, the demo invocation, automated tests, manual checks, pitfall mitigation references, recovery procedures, and the phase-exit checklist.

---

## Pre-flight (one-time setup)

```bash
# 1. Install Python deps (uv-managed venv)
make install

# 2. Provision Postgres (idempotent — re-running is safe)
brew services start postgresql@17    # or @16
bash scripts/init_postgres.sh

# 3. Build cua-driver Swift binary (vendored at libs/cua-driver/)
cd libs/cua-driver && swift build -c release && cd -

# 4. Make cua-driver available on PATH (or set CUA_DRIVER_BIN)
export PATH="$PWD/libs/cua-driver/.build/release:$PATH"
# OR
export CUA_DRIVER_BIN="$PWD/libs/cua-driver/.build/release/cua-driver"

# 5. Verify the environment
make doctor
# Expected: every row [OK] (Python 3.12, uv, Postgres listening, AXIsProcessTrusted, Calculator).

# 6. Grant TCC Accessibility to the test runner
# System Settings → Privacy & Security → Accessibility → "+", add:
#   ~/dev/basicCtrl/.venv/bin/python
# (the uv-managed Python interpreter; otherwise AXObserver subscribes silently fail)
```

---

## Run the demo

```bash
uv run python -m basicctrl.demo.calculator_click
```

Expected output (rich-formatted; latency varies):

```
─── Phase 1 Calculator demo ───
{"event": "appprofile_cache_hit", "bundle_id": "com.apple.calculator", ...}
{"event": "session.created", "session_id": "<uuid>", ...}
{"event": "durable.setup_complete", "conn": "postgresql://localhost:5432/basicctrl"}
{"event": "demo.click_scheduled", "cx": 664, "cy": 908}
{"event": "demo.click_fired", ...}
{"event": "verifier.aggregated", "verified": true, "confidence": 1.0, "elapsed_ms": ~30-45, "tier_signals": {"L0": ..., "L1": ..., "L2": null, "L3": null}}
{"event": "durable.checkpoint_written", ...}

─── VERIFIED ───
session_id    = <uuid4>
composite_key = axid:com.apple.calculator:Five
confidence    = 1.000
latency_ms    = ~30-45
L0 signal     = (1.0 if AX delivered, else 0.0 — see "AX delivery quirk" below)
L1 signal     = (1.0 from pasteboard.changeCount or window-list diff)
L2 signal     = None  (None expected for Phase 1)
L3 signal     = None  (None expected for Phase 1)
action_log    = ~/.cua/sessions/<uuid>/action_log.ndjson
profile_cache = ~/.cua/profiles/com.apple.calculator.json
```

Exit code: 0.

### AX delivery quirk (macOS 26 / Calculator)

On macOS 26 (Tahoe), `kAXValueChanged` from a Calculator button click occasionally fails to deliver to the AXObserver bridge within the 30 ms L0 budget — even though the bridge subscribes correctly and the event fires (verified via standalone probe). When this happens, the L1 cheap-diff tier carries verification (pasteboard.changeCount and dHash both flip on Calculator's display update). Confidence resolves to 1.0 either way thanks to the present-signal renormalization rule (Plan 05 BLOCKER-1 fix).

If the demo reports `verified: false` with all `L0=L1=0`, focus the Calculator window manually (Cmd+Tab) and re-run — the click may have landed on a hidden window.

---

## Run automated tests

```bash
# Unit tests (111+ across all Phase 1 plans; ~1s)
uv run pytest -x -q tests/unit/

# Integration tests (require Calculator + TCC; ~10s)
uv run pytest -x -v -m integration tests/integration/test_calculator_click.py
uv run pytest -x -v -m integration tests/integration/test_phase1_e2e.py
```

`test_phase1_e2e.py::test_all_six_success_criteria` is THE Phase 1 ship-gate. If it passes, all six ROADMAP success criteria are met.

To skip integration tests on dev machines without Calculator launchable:

```bash
SKIP_INTEGRATION=1 uv run pytest -q tests/
```

---

## Manual smoke checks (1× per phase ship)

Per `01-VALIDATION.md` "Manual-Only Verifications":

### TCC revocation (P24)

1. Run the demo green once.
2. System Settings → Privacy & Security → Accessibility → toggle OFF for the Python binary.
3. Re-run `python -m basicctrl.demo.calculator_click`.
4. Expect: structured event `tcc_revoked` in stderr/log with the action URL `x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility`. Process exits 2 (or AssertionError on `pre.target_role` if the revocation hits mid-walk).
5. Re-enable TCC and confirm a fresh demo run passes.

### Modal alert blocks AX (P25)

1. Open System Settings → Privacy & Security → click any "Lock" icon to trigger the password prompt modal.
2. While the modal is up, run the demo.
3. Expect: `AssertionError: A modal is blocking Calculator — close any system dialogs before re-running the demo (Pitfall P25).`
4. Dismiss the modal and confirm a fresh demo run passes.

### SIGKILL crash-resume (PERSIST-03)

1. Start `python -m basicctrl.demo.calculator_click` in one terminal.
2. While Postgres is writing the checkpoint (during `durable.checkpoint_written`), in another terminal: `kill -9 <pid>`.
3. In a third terminal:
   ```python
   import asyncio
   from basicctrl.persist import DurableExecutor, resume_from_checkpoint
   async def main():
       d = DurableExecutor()
       await d.setup()
       ctx = await resume_from_checkpoint("<session_id-from-step-1>", d)
       print(ctx)
       await d.aclose()
   asyncio.run(main())
   ```
4. Expect: `ResumeContext(session_id=..., last_step_idx=1, last_verified_action=ActionCanonical(...))`.

---

## Pitfalls verified mitigated

| Pitfall | Mitigation file | Tests / Demo evidence |
|---------|-----------------|-----------------------|
| **P2** (cmux #2985 / AX rate-limit) | `basicctrl/ax/rate_limit.py::TokenBucket` (20/sec/pid default) | `tests/unit/test_rate_limit.py` (initial-burst-20 + 21st-deny + per-pid isolation + frozen-clock refill) |
| **P3** (full recursive AX = 15-20s on Safari) | `basicctrl/ax/walker.py::walk_subtree` (max_depth=3, max_children=50, max_nodes=500) | `tests/unit/test_walker.py` (caps + no-recursion source-grep) |
| **P14** (AX notifs fail on web/Electron) | `basicctrl/profile/capability_probe.py::probe_ax_observer_works` (`AppProfile.ax_observer_works` field) | `tests/integration/test_app_profile.py::test_calculator_profile` |
| **P24** (TCC revoked mid-session) | `basicctrl/profile/tcc.py::TCCMonitor.check` at every classify() entry | `tests/unit/test_tcc.py` + Manual smoke check above |
| **P25** (modal alert blocks AX) | `basicctrl/ax/modal_probe.py::has_blocking_modal` (window cap=10, no walker) | `tests/integration/test_modal_probe.py` + Manual smoke check above |
| **P28** (stale notification races verifier) | `basicctrl/verifier/axobserver.py::_passes_filter` (5 ms ts guard + action_id refcon match + notif-set check) | `tests/unit/test_axobserver_filter.py` (4 predicates × isolation) |

---

## Failure recovery

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `make doctor: Postgres not listening` | Postgres service down | `brew services start postgresql@17 && bash scripts/init_postgres.sh` |
| `FileNotFoundError: cua-driver` | Swift binary not built | `cd libs/cua-driver && swift build -c release` + `export CUA_DRIVER_BIN=...` |
| `AssertionError: latency NNms exceeds 50ms budget` | First-run module-import / OCR JIT warmup | Re-run twice; median of 3 should pass. If persistent, profile with `time uv run python -m basicctrl.demo.calculator_click`. |
| `AssertionError: ax_rich is False` | Test ran before Calculator finished launching | Bump the `await asyncio.sleep(0.5)` in `run_demo` to 1.0s on slow boots; or activate Calculator manually first. |
| `AssertionError: verifier failed: confidence=0.0` | AX events didn't deliver AND L1 signals didn't change (pasteboard/window static between runs) | Focus Calculator window (Cmd+Tab), re-run. AX event delivery has a known macOS 26 quirk — see "AX delivery quirk" above. |
| `RuntimeError: Calculator '5' button not found after 10.0s` | Calculator window hidden after first launch | Activate Calculator (`osascript -e 'tell application "Calculator" to activate'`) and run again. |
| `TypeError: Callable argument is not a PyObjC closure` | Stale install (pre-fix observer.py) | `git pull && uv pip install -e .` to pick up Plan 01-09's observer.py fix. |

---

## Phase exit checklist

- [ ] `make test` exits 0 (all unit tests).
- [ ] `make doctor` all rows [OK].
- [ ] `python -m basicctrl.demo.calculator_click` exits 0 with VERIFIED + latency_ms < 50.
- [ ] `pytest -m integration tests/integration/test_phase1_e2e.py` shows all 6 SC PASS.
- [ ] Manual TCC revocation smoke check completed.
- [ ] Manual modal-blocking smoke check completed.
- [ ] Manual SIGKILL crash-resume smoke check completed.
- [ ] Per-plan SUMMARY.md files exist for plans 01-09 (`ls .planning/phases/01-foundation-state-verifier/01-0[1-9]-SUMMARY.md`).
- [ ] No edits under `libs/cua-driver/Sources/` (`git diff --name-only libs/cua-driver/Sources/` returns empty).
- [ ] PHASE-1-DEMO.md (this file) reviewed end-to-end.

If every box ticks, Phase 1 is ready to hand off to Phase 2 (Translators + Racing).
