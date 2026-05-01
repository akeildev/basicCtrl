---
phase: 5
slug: visualizer-full-transparency
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-01
---

# Phase 5 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Wave 0 populated with test matrix + pitfall assertions + phase gate criteria.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml (existing Phase 1-4 config) |
| **Quick run command** | `pytest tests/test_visualizer.py::TestImportSkip -v --tb=short` |
| **Full suite command** | `pytest tests/test_visualizer.py -v --tb=short` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_visualizer.py -v --tb=short`
- **After every plan wave:** Run full suite (all 6 VIS + 6 OBS tests)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Test Coverage Matrix

| Requirement | Test Name | Test Type | Command | Wave | Status |
|---|---|---|---|---|---|
| VIS-01 | test_ghost_cursor_lerp_timing | Integration | pytest tests/test_visualizer.py::test_ghost_cursor_lerp_timing -x | 1 | Pending |
| VIS-02 | test_hud_action_history_snapshot | UI snapshot | pytest tests/test_visualizer.py::test_hud_action_history_snapshot -x | 2 | Pending |
| VIS-03 | test_scontent_filter_excludes_overlay | Integration | pytest tests/test_visualizer.py::test_scontent_filter_excludes_overlay -x | 1 | Pending |
| VIS-04 | test_replay_state_reconstruction | Integration | pytest tests/test_visualizer.py::test_replay_state_reconstruction -x | 4 | Pending |
| VIS-05 | test_scontent_filter_excludes_overlay | Unit | pytest tests/test_visualizer.py::test_scontent_filter_excludes_overlay -x | 1 | Pending |
| VIS-06 | test_hotkey_hud_toggle | UI | pytest tests/test_visualizer.py::test_hotkey_hud_toggle -x | 2 | Pending |
| OBS-01 | test_h265_recording_creation | Integration | pytest tests/test_visualizer.py::test_h265_recording_creation -x | 3 | Pending |
| OBS-02 | test_action_log_ndjson_structured | Unit | pytest tests/test_visualizer.py::test_action_log_ndjson_structured -x | 1 | Pending |
| OBS-03 | test_timeline_1000_nodes_60fps | Performance | pytest tests/test_visualizer.py::test_timeline_1000_nodes_60fps -x | 5 | Pending |
| OBS-04 | test_scrub_alignment_frame_accuracy | Integration | pytest tests/test_visualizer.py::test_scrub_alignment_frame_accuracy -x | 4 | Pending |
| OBS-05 | test_counterfactual_dashed_path_snapshot | UI snapshot | pytest tests/test_visualizer.py::test_counterfactual_dashed_path_snapshot -x | 5 | Pending |
| OBS-06 | test_diff_alignment_lcs | Integration | pytest tests/test_visualizer.py::test_diff_alignment_lcs -x | 5 | Pending |

---

## Pitfall Mitigations (Grep-Enforced)

| Pitfall | Assertion | Acceptance Criteria |
|---|---|---|
| P9 (ScreenCaptureKit captures overlay) | `grep -c "SCContentFilter" libs/cua-driver/App/Visualizer*.swift >= 1` | SCContentFilter present in Swift sidecar |
| P10 (sharingType=.none broken) | `grep -c "sharingType.*\.none" libs/cua-driver/App/Visualizer*.swift == 0` | No reliance on .none flag |
| P11 (CALayer CPU spike) | `grep -c "CAShapeLayer\|setHidden\|isHidden" libs/cua-driver/App/Visualizer*.swift >= 1` | Single CAShapeLayer per element, hide during verify |
| P12 (Ghost cursor CALayer) | `grep -c "override func draw" libs/cua-driver/App/Visualizer*.swift >= 1` AND `grep -c "CABasicAnimation\|CAKeyframeAnimation" libs/cua-driver/App/GhostCursor*.swift == 0` | NSView.draw() used, no CALayer animation |

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 5-01-01 | 01 | 0 | VIS-01..OBS-06 | unit + integration | `pytest tests/test_visualizer.py::TestImportSkip -v` | ✅ | Complete |
| 5-01-02 | 01 | 0 | OBS-02 | unit | `pytest tests/test_visualizer.py::TestSessionWriter -v` | ✅ | Complete |
| 5-01-03 | 01 | 0 | VIS-01..OBS-06 | unit + skip | `pytest tests/test_visualizer.py -v --tb=short` | ✅ | Complete |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `tests/test_visualizer.py` — stubs for REQ-VIS-01..OBS-06 + model validation tests
- [x] `tests/conftest.py` — existing Phase 1-4 fixtures (SessionWriter uses tmp_path)
- [x] Framework already installed (pytest 7.x from Phase 1-4)

**Existing infrastructure covers all phase requirements.**

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Ghost cursor visible on screen | VIS-01 | Requires Swift sidecar + NSPanel rendering | Visual inspection during Phase 5 Wave 1 |
| HUD opacity slider works | VIS-02 | Requires SwiftUI event handling | Test in Phase 5 Wave 2 |
| H.265 encoding latency <16ms/frame | OBS-01 | Requires VideoToolbox profiling | Telemetry log review during Phase 5 Wave 3 |
| 3D timeline responsiveness at 1000 nodes | OBS-03 | Requires Canvas performance profiling | Benchmark during Phase 5 Wave 5 |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** 2026-05-01 (Wave 0 complete)

---

## Smoke Test (Wave 0)

```bash
pytest tests/test_visualizer.py::TestImportSkip -v
pytest tests/test_visualizer.py::TestModelValidation -v
pytest tests/test_visualizer.py::TestSessionWriter -v
```

Expected: All pass (no Swift dependencies in Wave 0).
