"""ACT-01: C1-C5 channel registry (SkyLight/AX/CGEvent/AS/CDP).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-04 creates the channel registry.
"""
import pytest
pytest.importorskip("cua_overlay.actions.channel_registry")


def test_phase2_wave0_channel_registry_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-04."""
    assert True
