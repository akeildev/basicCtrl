"""ACT-04: Per-action-class race policy (D-09..D-12 dispatch table).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-02 creates the race policy module.
"""
import pytest
pytest.importorskip("cua_overlay.actions.race_policy")


def test_phase2_wave0_race_policy_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-02."""
    assert True
