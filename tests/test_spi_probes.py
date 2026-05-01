"""Unit tests for SPI capability probes (Wave 0).

Per RESEARCH.md §"Validation Architecture" L310-342:
Framework: pytest + pytest-asyncio
Quick run: pytest tests/test_spi_probes.py -x (<5s)
"""
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from cua_overlay.spi import probe_spi_capabilities, SPICapabilities
from cua_overlay.spi.probe import (
    probe_skylight,
    probe_ax_remote,
    probe_cgs_display_space,
    probe_endpoint_security,
    probe_dtrace,
    probe_dyld_inject,
    probe_webkit_inspector,
    probe_imu,
)


def test_probe_skylight():
    """SPI-01: SkyLight symbol detection via dlsym."""
    result = probe_skylight()
    assert isinstance(result, bool)
    # On macOS 26, should be True if SkyLight.framework available
    if not result:
        # Graceful fallback; SkyLight unavailable on this system (possible on older macOS)
        pass


def test_probe_ax_remote():
    """SPI-02: AX remote notifications via _AXObserverAddNotificationAndCheckRemote."""
    result = probe_ax_remote()
    assert isinstance(result, bool)
    # Should be True on Phase 2+ (already shipping)


def test_probe_cgs_display_space():
    """SPI-03: CGS Display Space control symbol."""
    result = probe_cgs_display_space()
    assert isinstance(result, bool)


def test_probe_endpoint_security():
    """SPI-04: Endpoint Security framework (SIP-dependent)."""
    result = probe_endpoint_security()
    assert isinstance(result, bool)
    # False on default Mac (SIP on); True if SIP partial-off


def test_probe_dtrace():
    """SPI-05: DTrace probes (SIP-dependent)."""
    result = probe_dtrace()
    assert isinstance(result, bool)
    # False on default Mac (SIP on); True if SIP partial-off


def test_probe_dyld_inject():
    """SPI-06: DYLD injection (arm64e signing spike deferred)."""
    result = probe_dyld_inject()
    # Wave 0: always False until spike (Wave 3) determines feasibility
    assert result is False


def test_probe_webkit_inspector():
    """SPI-07: WebKit RemoteInspector private headers."""
    result = probe_webkit_inspector()
    assert isinstance(result, bool)


def test_probe_imu():
    """SPI-08: AppleSPUHIDDevice IMU (M-series only)."""
    result = probe_imu()
    assert isinstance(result, bool)
    # True on M-series; False on Intel


@pytest.mark.asyncio
async def test_probe_spi_capabilities_returns_dataclass():
    """probe_spi_capabilities() returns SPICapabilities with all 8 fields."""
    caps = await probe_spi_capabilities()
    assert isinstance(caps, SPICapabilities)
    assert hasattr(caps, "skylight_available")
    assert hasattr(caps, "ax_remote_available")
    assert hasattr(caps, "cgs_display_space_available")
    assert hasattr(caps, "endpoint_security_available")
    assert hasattr(caps, "dtrace_available")
    assert hasattr(caps, "dyld_inject_available")
    assert hasattr(caps, "webkit_inspector_available")
    assert hasattr(caps, "imu_available")


@pytest.mark.asyncio
async def test_probe_spi_capabilities_all_bool():
    """All fields in SPICapabilities are bool."""
    caps = await probe_spi_capabilities()
    assert all(isinstance(getattr(caps, f), bool) for f in [
        "skylight_available",
        "ax_remote_available",
        "cgs_display_space_available",
        "endpoint_security_available",
        "dtrace_available",
        "dyld_inject_available",
        "webkit_inspector_available",
        "imu_available",
    ])
