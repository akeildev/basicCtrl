"""Private SPI Integration — SkyLight, AX remote, ES, DTrace, DYLD, WebKit, IMU.

Phase 6 main module. Exports SPICapabilities dataclass + probe function.
Gate: pytest.importorskip if platform not macOS.
"""
import sys
import platform

# Hard gate: SPI features only on macOS
if platform.system() != "Darwin":
    import pytest
    pytest.skip("SPI features macOS only", allow_module_level=True)

from .probe import SPICapabilities, probe_spi_capabilities

__all__ = ["SPICapabilities", "probe_spi_capabilities"]
