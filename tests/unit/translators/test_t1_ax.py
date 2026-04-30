"""TRANS-01: T1 AX translator wraps Phase 1 cua_overlay.ax.* (Pitfall P2 mitigation).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-05 creates t1_ax.
"""
import pytest
pytest.importorskip("cua_overlay.translators.t1_ax")


def test_phase2_wave0_t1_ax_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-05."""
    assert True
