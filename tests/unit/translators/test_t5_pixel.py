"""TRANS-05: T5 Pixel translator (CGWindowList + CGEvent.postToPid, no global cursor warp).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-09 creates t5_pixel.
"""
import pytest
pytest.importorskip("cua_overlay.translators.t5_pixel")


def test_phase2_wave0_t5_pixel_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-09."""
    assert True
