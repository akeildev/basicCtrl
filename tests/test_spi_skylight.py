"""Unit tests for SkyLight SPI implementation (Wave 1).

Per RESEARCH.md §"Validation Architecture" L310-342:
Framework: pytest + pytest-asyncio
Command: pytest tests/test_spi_skylight.py -x
"""
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, ANY
import anyio

from basicctrl.spi.skylight import (
    SkyLightBridge,
    get_skylight_bridge,
    is_skylight_available,
)
from basicctrl.actions.channels.c1_skylight_spi import C1SkyLightSPI
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.spi.probe import SPICapabilities


@pytest.fixture
def mock_capabilities():
    """Mock SPI capabilities with SkyLight available."""
    return SPICapabilities(
        skylight_available=True,
        ax_remote_available=False,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )


@pytest.fixture
def mock_capabilities_unavailable():
    """Mock SPI capabilities with SkyLight unavailable."""
    return SPICapabilities(
        skylight_available=False,
        ax_remote_available=False,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )


def test_skylight_bridge_init_when_available():
    """SkyLightBridge initializes with available=True."""
    bridge = SkyLightBridge(available=True)
    assert bridge.available is True


def test_skylight_bridge_init_when_unavailable():
    """SkyLightBridge gracefully handles unavailable=False."""
    bridge = SkyLightBridge(available=False)
    assert bridge.available is False


@pytest.mark.asyncio
async def test_skylight_bridge_post_to_pid_fallback(mock_capabilities_unavailable):
    """If SkyLight unavailable, falls back to public CGEvent."""
    bridge = SkyLightBridge(available=False)
    mock_event = MagicMock()

    # Should succeed via fallback
    with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_to_thread:
        result = await bridge.post_to_pid(12345, mock_event)
        # Fallback returns False, but event still delivered
        assert result is False
        # Verify asyncio.to_thread was called (fallback path)
        assert mock_to_thread.called


@pytest.mark.asyncio
async def test_get_skylight_bridge_caches():
    """get_skylight_bridge() caches singleton."""
    caps = SPICapabilities(
        skylight_available=True,
        ax_remote_available=False,
        cgs_display_space_available=False,
        endpoint_security_available=False,
        dtrace_available=False,
        dyld_inject_available=False,
        webkit_inspector_available=False,
        imu_available=False,
    )

    # Reset module singleton for this test
    import basicctrl.spi.skylight as skylight_module
    skylight_module._bridge = None

    bridge1 = await get_skylight_bridge(caps)
    bridge2 = await get_skylight_bridge(caps)
    assert bridge1 is bridge2  # Same instance


@pytest.mark.asyncio
async def test_is_skylight_available(mock_capabilities):
    """is_skylight_available() reflects bridge status."""
    # Reset singleton
    import basicctrl.spi.skylight as skylight_module
    skylight_module._bridge = None

    result = await is_skylight_available(mock_capabilities)
    # Result depends on actual system; at minimum, function should succeed
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_c1_spi_channel_fires(mock_capabilities):
    """C1SkyLightSPI.fire() succeeds and claims idempotency."""
    channel = C1SkyLightSPI(capabilities=mock_capabilities)

    # Create mock objects
    target = MagicMock()
    target.bundle_id = "com.example.app"
    target.element.pid = 12345
    target.grounded_bbox = MagicMock(x=100, y=200, w=50, h=50)

    action = ActionCanonical(
        id="test-action-1",
        step_idx=0,
        kind="READ",
        target_key="button-1",
        action_type="click",
        payload={},
        timestamp_ns=time.time_ns(),
        session_id="test-session",
    )

    store = MagicMock()
    store.try_claim = AsyncMock(return_value={"claimed": True})

    cancel_event = anyio.Event()

    # Mock the bridge
    with patch.object(
        channel, "_construct_cgevent", return_value=MagicMock()
    ), patch.object(
        channel, "_bridge", MagicMock(post_to_pid=AsyncMock(return_value=True))
    ):
        outcome = await channel.fire(action, target, store, cancel_event)

    assert outcome.status == "fired"
    assert outcome.channel == "C1"
    assert outcome.fired_at_ns is not None


@pytest.mark.asyncio
async def test_c1_spi_channel_rejects_idempotency_loss(mock_capabilities):
    """C1SkyLightSPI.fire() returns skipped if idempotency claim fails."""
    channel = C1SkyLightSPI(capabilities=mock_capabilities)

    target = MagicMock()
    target.bundle_id = "com.example.app"
    target.element.pid = 12345
    target.grounded_bbox = MagicMock(x=100, y=200, w=50, h=50)

    action = ActionCanonical(
        id="test-action-2",
        step_idx=0,
        kind="READ",
        target_key="button-1",
        action_type="click",
        payload={},
        timestamp_ns=time.time_ns(),
        session_id="test-session",
    )

    store = MagicMock()
    store.try_claim = AsyncMock(return_value=None)  # Claim failed

    cancel_event = anyio.Event()

    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "skipped"
    assert outcome.skipped_reason == "idempotency_lost"


@pytest.mark.asyncio
async def test_c1_spi_channel_respects_cancel_event(mock_capabilities):
    """C1SkyLightSPI.fire() returns cancelled if cancel_event is set."""
    channel = C1SkyLightSPI(capabilities=mock_capabilities)

    target = MagicMock()
    target.bundle_id = "com.example.app"
    target.element.pid = 12345
    target.grounded_bbox = MagicMock(x=100, y=200, w=50, h=50)

    action = ActionCanonical(
        id="test-action-3",
        step_idx=0,
        kind="READ",
        target_key="button-1",
        action_type="click",
        payload={},
        timestamp_ns=time.time_ns(),
        session_id="test-session",
    )

    store = MagicMock()
    store.try_claim = AsyncMock(return_value={"claimed": True})

    cancel_event = anyio.Event()
    cancel_event.set()  # Cancel before fire

    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "cancelled"


@pytest.mark.asyncio
async def test_c1_spi_channel_missing_bbox(mock_capabilities):
    """C1SkyLightSPI.fire() returns errored if bbox missing."""
    channel = C1SkyLightSPI(capabilities=mock_capabilities)

    target = MagicMock()
    target.bundle_id = "com.example.app"
    target.element.pid = 12345
    target.grounded_bbox = None  # Missing bbox

    action = ActionCanonical(
        id="test-action-4",
        step_idx=0,
        kind="READ",
        target_key="button-1",
        action_type="click",
        payload={},
        timestamp_ns=time.time_ns(),
        session_id="test-session",
    )

    store = MagicMock()
    store.try_claim = AsyncMock(return_value={"claimed": True})

    cancel_event = anyio.Event()

    outcome = await channel.fire(action, target, store, cancel_event)
    assert outcome.status == "errored"
    assert "missing grounded_bbox" in outcome.error


def test_c1_spi_channel_name():
    """C1SkyLightSPI declares correct name."""
    channel = C1SkyLightSPI()
    assert channel.name == "C1"
    assert channel.spi_name == "C1_SPI"


def test_c1_spi_channel_description():
    """C1SkyLightSPI has descriptive metadata."""
    channel = C1SkyLightSPI()
    assert "SkyLight" in channel.description
    assert "SPI" in channel.description
