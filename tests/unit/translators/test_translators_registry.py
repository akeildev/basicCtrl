"""Translator registry: dict[str, Translator] keyed by tier, picked by AppProfile.priority.

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-04 creates the registry.
"""
import pytest
pytest.importorskip("cua_overlay.translators.registry")


def test_phase2_wave0_translators_registry_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-04."""
    assert True
