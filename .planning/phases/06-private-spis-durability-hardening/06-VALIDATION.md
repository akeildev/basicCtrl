---
phase: 6
slug: private-spis-durability-hardening
status: in-progress
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-01
---

# Phase 6 — Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio 0.23+ |
| **Config file** | tests/conftest.py (existing Phase 1-5) |
| **Quick run command** | `pytest tests/test_spi_probes.py -x` |
| **Full suite command** | `pytest tests/test_spi_*.py -x` |
| **Estimated runtime** | ~30 seconds |

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_spi_probes.py -x` (~5s)
- **After every plan wave:** Run `pytest tests/test_spi_*.py -x` (~30s)
- **Before `/gsd-verify-work`:** Full suite must be green + manual SPI smoke test on Akeil's Mac
- **Max feedback latency:** 30 seconds

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Behavior | Test Type | Automated Command | Status |
|---------|------|------|-------------|----------|-----------|-------------------|--------|
| 6-01-01 | 01 | 0 | SPI-01..08 | All 8 probes return bool | unit | `pytest tests/test_spi_probes.py -x` | ⬜ pending |
| 6-01-02 | 01 | 0 | SPI-01..08 | probe_spi_capabilities() returns SPICapabilities | unit | `pytest tests/test_spi_probes.py::test_probe_spi_capabilities_returns_dataclass -xvs` | ⬜ pending |
| 6-02-01 | 02 | 0 | SPI-01..08 | AppProfile has 8 spi_*_available fields | unit | `pytest tests/test_profile_spi.py::test_app_profile_has_spi_fields -xvs` | ⬜ pending |

## Wave 0 Requirements

- [ ] `tests/test_spi_probes.py` — unit tests for all 8 capability probes
- [ ] `tests/test_profile_spi.py` — AppProfile SPI field tests
- [ ] `.planning/phases/06-private-spis-durability-hardening/06-VALIDATION.md` — filled (this file)

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SkyLight channel fires background events with no cursor warp | SPI-01 | Requires Swift visualizer sidecar + manual observation | Phase 6 Wave 1+ after SkyLight bridge ships |
| AX remote notifications keep Slack trees alive when occluded | SPI-02 | Requires running Slack + occluding window | Phase 6 Wave 1+ integration test |
| DYLD injection succeeds on arm64e | SPI-06 | Requires arm64e signing proof-of-concept | Phase 6 Wave 3 spike |

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING test references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter after Wave 0 complete

**Approval:** pending (populated Wave 0)
