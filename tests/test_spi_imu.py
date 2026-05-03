"""Tests for SPI-08 IMU wrapper.

Per RESEARCH.md §"AppleSPUHIDDevice IMU (SPI-08)" L133-177:
- Capability probe returns False on Intel/non-IMU hardware
- Graceful skip in tests when not available
- All read functions return None when unavailable
"""
import pytest
from dataclasses import dataclass

from basicctrl.spi.imu import IMUBridge, IMUData, get_imu_bridge


# Mock SPICapabilities for testing
@dataclass
class MockSPICapabilities:
    """Minimal mock for testing."""
    imu_available: bool
    skylight_available: bool = False
    ax_remote_available: bool = False
    cgs_display_space_available: bool = False
    endpoint_security_available: bool = False
    dtrace_available: bool = False
    dyld_inject_available: bool = False
    webkit_inspector_available: bool = False


class TestIMUBridge:
    """Test IMUBridge initialization and graceful unavailability."""

    def test_imu_bridge_init_unavailable(self):
        """IMUBridge with available=False stays unavailable."""
        bridge = IMUBridge(available=False)
        assert bridge.available is False
        assert bridge._service is None

    def test_imu_bridge_init_available(self):
        """IMUBridge with available=True attempts discovery."""
        # This will call _discover_imu_service, which uses ioreg.
        # On Intel or if ioreg fails, available should be downgraded to False.
        bridge = IMUBridge(available=True)
        # After discovery, check the state (may be True or False depending on hardware)
        assert isinstance(bridge.available, bool)

    @pytest.mark.asyncio
    async def test_read_imu_unavailable(self):
        """read_imu returns None when unavailable."""
        bridge = IMUBridge(available=False)
        result = await bridge.read_imu()
        assert result is None

    @pytest.mark.asyncio
    async def test_read_imu_available_no_service(self):
        """read_imu returns None when service not discovered."""
        bridge = IMUBridge(available=True)
        bridge._service = None  # Force no service
        result = await bridge.read_imu()
        assert result is None

    @pytest.mark.asyncio
    async def test_read_imu_available_with_service(self):
        """read_imu returns IMUData when service available."""
        bridge = IMUBridge(available=True)
        bridge._service = True  # Simulate successful discovery
        result = await bridge.read_imu()
        assert result is not None
        assert isinstance(result, IMUData)
        # Data fields are None (placeholder implementation)
        assert result.lid_angle is None


class TestIMUData:
    """Test IMUData dataclass."""

    def test_imu_data_init_empty(self):
        """IMUData initializes with all None."""
        data = IMUData()
        assert data.lid_angle is None
        assert data.accel_x is None
        assert data.accel_y is None
        assert data.accel_z is None
        assert data.gyro_x is None
        assert data.gyro_y is None
        assert data.gyro_z is None

    def test_imu_data_partial_init(self):
        """IMUData accepts partial initialization."""
        data = IMUData(lid_angle=45.0, accel_x=0.5)
        assert data.lid_angle == 45.0
        assert data.accel_x == 0.5
        assert data.accel_y is None


class TestGetIMUBridge:
    """Test bridge initialization and caching."""

    @pytest.mark.asyncio
    async def test_get_imu_bridge_caches(self):
        """get_imu_bridge caches result across calls."""
        caps = MockSPICapabilities(imu_available=False)
        bridge1 = await get_imu_bridge(caps)
        bridge2 = await get_imu_bridge(caps)
        assert bridge1 is bridge2, "Bridge should be cached (same object)"

    @pytest.mark.asyncio
    async def test_get_imu_bridge_unavailable(self):
        """get_imu_bridge respects capabilities.imu_available."""
        # Reset the global _bridge for clean test
        import basicctrl.spi.imu as imu_module
        imu_module._bridge = None

        caps = MockSPICapabilities(imu_available=False)
        bridge = await get_imu_bridge(caps)
        assert bridge.available is False
