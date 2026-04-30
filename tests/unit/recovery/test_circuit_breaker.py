"""Tests for circuit breaker.

Skips until circuit_breaker.py ships.
"""
import pytest

pytest.importorskip("cua_overlay.recovery.circuit_breaker")


def test_placeholder_skip_until_module_ships() -> None:
    """Placeholder test — actual tests added in Wave 1."""
    pass
