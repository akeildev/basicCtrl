"""SC #4: 100 racing fires -> 0 double-clicks (idempotency stress).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-12 wires the stress harness.
The 100-iteration loop and assertions land then.
"""
import pytest
pytest.importorskip("cua_overlay.actions.race_orchestrator")

# Stress-test target iteration count (asserted by Plan 02-12 implementation).
STRESS_ITERATIONS = 100


@pytest.mark.integration
@pytest.mark.stress
def test_phase2_wave0_race_idempotency_stress_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-12.

    Will exercise STRESS_ITERATIONS=100 racing fires and assert
    count(near_miss_duplicate) == 0.
    """
    assert STRESS_ITERATIONS == 100
