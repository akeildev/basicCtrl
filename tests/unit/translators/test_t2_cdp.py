"""TRANS-02: T2 CDP translator (cdp-use attach + workspace filter).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-06 creates t2_cdp.
"""
import pytest
pytest.importorskip("cua_overlay.translators.t2_cdp")


def test_phase2_wave0_t2_cdp_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-06."""
    assert True
