"""SC #3 (D-27): T4 SoM grounder + T5 CGEvent fires on Apple Chess.app.

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-12 wires the e2e race.
"""
import pytest
pytest.importorskip("cua_overlay.actions.race_orchestrator")


@pytest.mark.integration
def test_phase2_wave0_chess_t4_t5_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-12."""
    assert True
