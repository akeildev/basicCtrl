"""MCP-02 ext (D-29): 6-tool surface schema validation (Pydantic).

Mitigates T-2-10 (MCP schema typing).

Wave 0 stub: skips on ModuleNotFoundError until Plan 02-11 lands the
healing_tools schema extensions.
"""
import pytest
pytest.importorskip("cua_overlay.mcp_server.healing_tools")


def test_phase2_wave0_healing_tools_v2_stub_collected() -> None:
    """Wave-0 stub. Real tests live in Plan 02-11."""
    assert True
