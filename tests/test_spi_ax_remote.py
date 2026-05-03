"""Tests for SPI-02 AX remote bridge (formalization from Phase 2)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from basicctrl.spi.ax_remote import AXRemoteBridge, get_ax_remote_bridge, is_ax_remote_available
from basicctrl.spi.probe import SPICapabilities
from basicctrl.ax.observer import Subscription


@pytest.mark.asyncio
async def test_ax_remote_bridge_init_available():
    """AXRemoteBridge initializes with available=True."""
    bridge = AXRemoteBridge(available=True)
    assert bridge.available is True


@pytest.mark.asyncio
async def test_ax_remote_bridge_init_unavailable():
    """AXRemoteBridge initializes with available=False (graceful fallback)."""
    bridge = AXRemoteBridge(available=False)
    assert bridge.available is False


@pytest.mark.asyncio
async def test_ax_remote_bridge_set_event_bridge():
    """AXRemoteBridge stores AXEventBridge reference."""
    bridge = AXRemoteBridge(available=True)
    mock_event_bridge = MagicMock()
    bridge.set_event_bridge(mock_event_bridge)
    assert bridge._bridge is mock_event_bridge


@pytest.mark.asyncio
async def test_ax_remote_bridge_subscribe_delegates_to_event_bridge():
    """subscribe_with_remote_support delegates to AXEventBridge."""
    bridge = AXRemoteBridge(available=True)
    mock_event_bridge = MagicMock()

    # Create a mock subscription
    mock_sub = Subscription(
        pid=1234,
        element_key="slack/dm",
        notifications=["AXValueChanged"],
        action_id="action-123",
        subscription_ts_ns=12345,
    )
    mock_event_bridge.subscribe = MagicMock(return_value=mock_sub)

    bridge.set_event_bridge(mock_event_bridge)

    # Call subscribe_with_remote_support
    result = await bridge.subscribe_with_remote_support(
        pid=1234,
        element=MagicMock(),
        element_key="slack/dm",
        notifications=["AXValueChanged"],
        action_id="action-123",
    )

    # Verify it delegated to the event bridge
    mock_event_bridge.subscribe.assert_called_once()
    assert result == mock_sub


@pytest.mark.asyncio
async def test_ax_remote_bridge_subscribe_without_bridge_raises():
    """subscribe_with_remote_support raises if bridge not initialized."""
    bridge = AXRemoteBridge(available=True)
    # Don't set event bridge

    with pytest.raises(RuntimeError, match="not initialized"):
        await bridge.subscribe_with_remote_support(
            pid=1234,
            element=MagicMock(),
            element_key="slack/dm",
            notifications=["AXValueChanged"],
            action_id="action-123",
        )


@pytest.mark.asyncio
async def test_get_ax_remote_bridge_caches_singleton():
    """get_ax_remote_bridge() caches singleton."""
    caps_available = SPICapabilities(
        skylight_available=False,
        ax_remote_available=True,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )

    # Reset global to ensure fresh singleton
    import basicctrl.spi.ax_remote as ax_remote_module
    ax_remote_module._bridge = None

    bridge1 = await get_ax_remote_bridge(caps_available)
    bridge2 = await get_ax_remote_bridge(caps_available)

    # Same instance
    assert bridge1 is bridge2
    assert bridge1.available is True


@pytest.mark.asyncio
async def test_get_ax_remote_bridge_respects_capability():
    """get_ax_remote_bridge() respects capability probe result."""
    caps_unavailable = SPICapabilities(
        skylight_available=False,
        ax_remote_available=False,  # Not available
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )

    # Reset global
    import basicctrl.spi.ax_remote as ax_remote_module
    ax_remote_module._bridge = None

    bridge = await get_ax_remote_bridge(caps_unavailable)
    assert bridge.available is False


@pytest.mark.asyncio
async def test_is_ax_remote_available():
    """is_ax_remote_available() reflects capability."""
    caps_available = SPICapabilities(
        skylight_available=False,
        ax_remote_available=True,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )

    assert is_ax_remote_available(caps_available) is True


@pytest.mark.asyncio
async def test_is_ax_remote_unavailable():
    """is_ax_remote_available() returns False when unavailable."""
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

    assert is_ax_remote_available(caps_unavailable) is False
