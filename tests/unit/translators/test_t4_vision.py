"""TRANS-04: T4 Vision translator (uitag pipeline -> UIElement adapter).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-08 creates t4_vision.
"""
import pytest
pytest.importorskip("cua_overlay.translators.t4_vision")


def test_phase2_wave0_t4_vision_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-08."""
    assert True
