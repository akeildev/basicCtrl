"""SC #5 (D-21): Top-12 association map matches AppProfile.translator_priority.

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-03 creates known_apps.
"""
import pytest
pytest.importorskip("cua_overlay.profile.known_apps")


def test_phase2_wave0_top_12_priority_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-03."""
    assert True
