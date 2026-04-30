"""TRANS-03: T3 AppleScript translator (in-process NSAppleScript on dedicated ThreadPool).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-07 creates t3_applescript.
"""
import pytest
pytest.importorskip("cua_overlay.translators.t3_applescript")


def test_phase2_wave0_t3_applescript_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-07."""
    assert True
