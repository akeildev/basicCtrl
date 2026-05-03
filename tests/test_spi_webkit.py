"""Tests for SPI-07 WebKit RemoteInspector (stub).

Per RESEARCH.md §"Validation Architecture (Nyquist Gate)" L312-343:
- Framework: pytest + pytest-asyncio
- Pattern: Unit tests for capability gates; integration tests deferred to Wave 2+
- Coverage: Bridge init, cache behavior, fallback logging

SPI-07 confidence is MEDIUM (private API); tests validate that the stub loads
cleanly and graceful fallback is wired (no exceptions when unavailable).
"""
import pytest
from basicctrl.spi.webkit_inspector import (
    WebKitInspectorBridge,
    get_webkit_inspector_bridge,
)
from basicctrl.spi.probe import SPICapabilities


def test_webkit_inspector_bridge_init_available():
    """Bridge initializes cleanly when available=True."""
    bridge = WebKitInspectorBridge(available=True)
    assert bridge.available is True


def test_webkit_inspector_bridge_init_unavailable():
    """Bridge initializes cleanly when available=False."""
    bridge = WebKitInspectorBridge(available=False)
    assert bridge.available is False


@pytest.mark.asyncio
async def test_evaluate_js_in_safari_unavailable():
    """evaluate_js_in_safari returns None when unavailable (graceful fallback)."""
    bridge = WebKitInspectorBridge(available=False)
    result = await bridge.evaluate_js_in_safari("console.log('test');")
    assert result is None


@pytest.mark.asyncio
async def test_evaluate_js_in_safari_available_deferred():
    """evaluate_js_in_safari returns None (deferred implementation) even when available."""
    bridge = WebKitInspectorBridge(available=True)
    # Phase 6 Wave 1: implementation deferred
    result = await bridge.evaluate_js_in_safari("console.log('test');")
    assert result is None


@pytest.mark.asyncio
async def test_get_webkit_inspector_bridge_caches():
    """get_webkit_inspector_bridge caches the instance (singleton pattern)."""
    # Create mock capabilities
    caps = SPICapabilities(
        skylight_available=False,
        ax_remote_available=False,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )

    # Reset global bridge for test isolation
    import basicctrl.spi.webkit_inspector as webkit_module

    webkit_module._bridge = None

    # First call should create the bridge
    bridge1 = await get_webkit_inspector_bridge(caps)
    # Second call should return the same instance
    bridge2 = await get_webkit_inspector_bridge(caps)

    assert bridge1 is bridge2
    assert bridge1.available is False

    # Cleanup
    webkit_module._bridge = None


@pytest.mark.asyncio
async def test_get_webkit_inspector_bridge_respects_capability():
    """get_webkit_inspector_bridge respects the webkit_inspector_available flag."""
    caps_available = SPICapabilities(
        skylight_available=False,
        ax_remote_available=False,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=True,
        imu_available=False,
    )

    # Reset global bridge for test isolation
    import basicctrl.spi.webkit_inspector as webkit_module

    webkit_module._bridge = None

    bridge = await get_webkit_inspector_bridge(caps_available)
    assert bridge.available is True

    # Cleanup
    webkit_module._bridge = None


@pytest.mark.asyncio
async def test_get_webkit_inspector_bridge_unavailable():
    """get_webkit_inspector_bridge creates bridge with available=False when capability missing."""
    caps_unavailable = SPICapabilities(
        skylight_available=False,
        ax_remote_available=False,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )

    # Reset global bridge for test isolation
    import basicctrl.spi.webkit_inspector as webkit_module

    webkit_module._bridge = None

    bridge = await get_webkit_inspector_bridge(caps_unavailable)
    assert bridge.available is False

    # Cleanup
    webkit_module._bridge = None
