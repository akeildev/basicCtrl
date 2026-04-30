"""D-19: 2-second ring buffer of (axid, action_kind, ts) for near_miss_duplicate dedup.

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-02 creates the duplicate-receipt module.
"""
import pytest
pytest.importorskip("cua_overlay.actions.duplicate_receipt")


def test_phase2_wave0_duplicate_receipt_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-02."""
    assert True
