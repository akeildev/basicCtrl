"""ACT-03: Atomic idempotency tokens (claim BEFORE fire; second claim returns Cancelled).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-02 creates the idempotency module.
"""
import pytest
pytest.importorskip("cua_overlay.actions.idempotency")


def test_phase2_wave0_idempotency_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-02."""
    assert True
