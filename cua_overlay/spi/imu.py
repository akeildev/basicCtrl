"""SPI-08: AppleSPUHIDDevice IMU reader (M-series only).

Per RESEARCH.md §"AppleSPUHIDDevice IMU (SPI-08)" L133-177:
- Bosch BMI286 MEMS sensor on M1-M4 (confirmed via GitHub projects)
- IOKit HID enumeration; graceful skip on Intel
- Undocumented by Apple (intentional — hardware-level access)
- Optional feature; no gate on core functionality
"""
import subprocess
import logging
from typing import Optional
from dataclasses import dataclass

import structlog

log = structlog.get_logger(__name__)


@dataclass
class IMUData:
    """IMU sensor readings (when available)."""
    lid_angle: Optional[float] = None  # Degrees (0-180)
    accel_x: Optional[float] = None
    accel_y: Optional[float] = None
    accel_z: Optional[float] = None
    gyro_x: Optional[float] = None
    gyro_y: Optional[float] = None
    gyro_z: Optional[float] = None


class IMUBridge:
    """Wrapper for AppleSPUHIDDevice IMU (M-series).

    Gracefully handles unavailability on Intel Macs.
    IOKit enumeration performed once at initialization.
    """

    def __init__(self, available: bool = False):
        self.available = available
        self._service = None

        if available:
            self._discover_imu_service()

    def _discover_imu_service(self):
        """Enumerate IOKit for AppleSPUHIDDevice (M-series).

        Uses ioreg(1) for safe, non-blocking enumeration.
        On success: _service is set to True (boolean flag for availability).
        On failure: _service remains None, available is downgraded to False.
        """
        try:
            # Use ioreg to check for sensor (faster than raw IOKit from Python)
            result = subprocess.run(
                ['ioreg', '-r', '-d', '1', '-c', 'AppleSPUHIDDevice'],
                capture_output=True,
                timeout=2,
                text=True
            )
            if "AppleSPUHIDDevice" in result.stdout:
                self._service = True
                log.info("imu_service_discovered", device="AppleSPUHIDDevice")
            else:
                self.available = False
                log.info("imu_not_available", reason="AppleSPUHIDDevice not found in IORegistry")
        except FileNotFoundError:
            log.warning("imu_discovery_failed", error="ioreg not found")
            self.available = False
        except subprocess.TimeoutExpired:
            log.warning("imu_discovery_timeout", timeout_sec=2)
            self.available = False
        except Exception as e:
            log.warning("imu_discovery_error", error=str(e), error_type=type(e).__name__)
            self.available = False

    async def read_imu(self) -> Optional[IMUData]:
        """Read current IMU data.

        Returns:
            IMUData with available fields, or None if IMU not available.

        Currently returns empty IMUData as placeholder.
        Raw IOKit HID report parsing deferred to Wave 2+.
        """
        if not self.available or not self._service:
            return None

        # Implementation deferred: raw IOKit HID report parsing is complex
        # For now, return empty IMUData (feature gracefully available but no data)
        return IMUData()


_bridge: Optional[IMUBridge] = None


async def get_imu_bridge(capabilities) -> Optional[IMUBridge]:
    """Get or initialize IMU bridge.

    Args:
        capabilities: SPICapabilities object from probe_spi_capabilities().

    Returns:
        IMUBridge if available, None if IMU not on this hardware.
        Result is cached per session.
    """
    global _bridge
    if _bridge is None:
        _bridge = IMUBridge(available=capabilities.imu_available)
    return _bridge
