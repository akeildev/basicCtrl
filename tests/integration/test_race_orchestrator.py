"""ACT-02: Race orchestrator (anyio FIRST_COMPLETED + clean cancel of losers).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-10 creates the orchestrator.
"""
import pytest
pytest.importorskip("cua_overlay.actions.race_orchestrator")


@pytest.mark.integration
def test_phase2_wave0_race_orchestrator_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-10."""
    assert True
