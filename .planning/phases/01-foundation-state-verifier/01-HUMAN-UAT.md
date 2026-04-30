---
status: partial
phase: 01-foundation-state-verifier
source: ["01-VERIFICATION.md"]
started: 2026-04-29T22:55:00Z
updated: 2026-04-29T22:55:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Calculator click <50ms via L0 push (SC-1)
expected: `uv run python -m cua_overlay.demo.calculator_click` exits 0 with VERIFIED, latency_ms<50, L0 signal=1.0 (or L1 carries per renormalization), L2=None, L3=None
result: [pending]

Pre-step: `brew services start postgresql@17 && ./scripts/init_postgres.sh && open -a Calculator`
Note: agent already ran live during 01-09 execution; reported verified=True, latency 31-45ms. This is a re-verification gate.

### 2. AppProfile cache survives session restart (SC-3 manual)
expected: First run probes Calculator in <500ms; second run reads `~/.cua/profiles/com.apple.calculator.json` in <5ms (cache hit log line)
result: [pending]

### 3. TCC revocation surfaced (P24, manual smoke)
expected: Toggle Accessibility OFF for Python interpreter (System Settings → Privacy & Security → Accessibility); demo emits structured event `tcc_revoked` with action_url, exits 2
result: [pending]

### 4. Modal alert blocks AX (P25, manual smoke)
expected: Open System Settings password prompt while modal up; demo asserts `pre.no_blocking_modal is False`
result: [pending]

### 5. SIGKILL crash-resume (PERSIST-03 manual)
expected: Start session, write 1 checkpoint, `kill -9 <pid>`; `resume_from_checkpoint(session_id)` returns ResumeContext with `last_step_idx=1`
result: [pending]

Note: CI-equivalent test_resume_simulated_crash passes (executor-A writes, aclose, executor-B resumes). The SIGKILL variant requires multi-terminal sequencing.

### 6. MCP proxy + healing tool with real cua-driver (SC-6)
expected: After `swift build` of cua-driver, list_tools returns proxied upstream tools + click_with_healing; `click_with_healing` call writes action_log.ndjson AND now (after WR-02 fix in commit a5656a1) the verifier ladder fires + Postgres checkpoint lands.
result: [pending]

Pre-step: `cd libs/cua-driver && swift build -c release && export CUA_DRIVER_BIN=$(pwd)/.build/release/cua-driver`

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps

### Resolved during this session

- **WR-02 (healing_tools.py bypassed verifier wrap)** — fixed inline by `fix(01): wire click_with_healing through verifier wrap (WR-02)` (commit a5656a1). `run_action_wrap()` extracted to shared helper; both `register_proxied_tool` and `register_healing_tools` route through it. mypy strict clean. 111 unit tests pass.

### Deferred to Phase 2

- **WR-01 — stale element_key on multi-subscribe per-pid** — only matters when Phase 2's race orchestrator subscribes multiple translators against the same pid. Documented in observer.py:255-307 review.
- **WR-04 — RuntimeError leak in AX callback** — `loop.call_soon_threadsafe` on a closed loop raises into the C boundary. Defensive try/except needed. Cheap fix; land before Phase 2 stress-tests `stop()`.

### Deferred to Phase 3

- **WR-03 — unbounded growth of `_callbacks/_refcon_to_action/_subscriptions`** — Phase 3's high-frequency action cycling will hit this. Add cleanup hook on subscription expiry.

### Documentation/cosmetic (no behavior impact)

- **WR-05** — `_mask_conn` over-redacts password-less conn strings (display only).
- **WR-06** — deprecated `asyncio.get_event_loop()` fallback in `kqueue_proc.py:47`.
- **IN-09** — walker `max_depth=3` semantics off-by-one vs docstring (root + 3 child levels = 4 visited).

## Phase 1 Sign-Off Criteria

Phase 1 is approved if **all 6 manual tests pass** OR Akeil approves with documented partial coverage.
