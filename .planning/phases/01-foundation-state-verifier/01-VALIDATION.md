---
phase: 1
slug: foundation-state-verifier
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-29
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio 0.23+ |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (Wave 0 installs) |
| **Quick run command** | `uv run pytest -x -q tests/` |
| **Full suite command** | `uv run pytest -v --tb=short tests/` |
| **Estimated runtime** | ~30 seconds (Phase 1 — no LLM calls, no remote deps) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -x -q tests/`
- **After every plan wave:** Run `uv run pytest -v --tb=short tests/`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

> Filled by gsd-planner. Tasks below are placeholders to be replaced after PLAN.md generation.
> Every task in PLAN.md must have a corresponding row here with an automated command (or Wave 0 dependency).

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 1-XX-XX | XX  | N    | REQ-XX      | T-1-XX / — | {to fill}       | unit      | `{cmd}`           | ❌ W0       | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — `[project]` + `[tool.pytest.ini_options]` (asyncio_mode=auto)
- [ ] `tests/conftest.py` — shared fixtures (Calculator launch helper, sample AppProfile)
- [ ] `tests/test_state_graph.py` — STATE-01..03 stubs
- [ ] `tests/test_axobserver.py` — VERIFY-01..03 stubs
- [ ] `tests/test_verifier_layers.py` — VERIFY-04..07 stubs
- [ ] `tests/test_appprofile.py` — CORE-03 stubs
- [ ] `tests/test_persistence.py` — PERSIST-01..03 stubs
- [ ] `tests/test_mcp_proxy.py` — MCP-01..02 stubs
- [ ] `uv add --dev pytest pytest-asyncio` — install if not present

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Calculator click → kAXValueChanged → VERIFIED in <50ms | Success criterion 1 | Requires real macOS app + TCC grant; cannot run in CI | Launch Calculator.app; run `uv run python -m cua_overlay.demo.calculator_click`; assert log line `VERIFIED step_idx=N latency_ms<50` |
| TCC revocation surfaced (P24) | Hard rule | Must toggle Accessibility privacy setting manually | Disable Accessibility for terminal; run probe; assert structlog event `tcc.revoked` |
| Modal alert blocks AX (P25) | Hard rule | Requires interactive modal | Open System Settings password prompt; run probe; assert HoarePost has `modal_blocking=true` |
| Postgres crash-resume scaffold | PERSIST-03 | Requires manual `pg_ctl stop` + restart sequence | Start session; checkpoint; `kill -9` python; restart; assert state restored |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
