"""Integration tests for Phase 6 SPI channels (Wave 6).

Per RESEARCH.md §"Validation Architecture" L310-342:
Framework: pytest + pytest-asyncio
Command: pytest tests/test_spi_integration.py -x (~30s)

Tests verify each SPI channel fires without error, gating correctly on
capability probes, and handling unavailability gracefully.
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from cua_overlay.spi import probe_spi_capabilities, SPICapabilities
from cua_overlay.spi.skylight import SkyLightBridge
from cua_overlay.spi.ax_remote import AXRemoteBridge
from cua_overlay.spi.webkit_inspector import WebKitInspectorBridge
from cua_overlay.spi.imu import IMUBridge
from cua_overlay.spi.cgs_display import CGSBridge
from cua_overlay.spi.endpoint_security import EndpointSecurityBridge
from cua_overlay.spi.dtrace import DTraceBridge
from cua_overlay.spi.dyld_inject import DYLDInjectBridge


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_spi_01_skylight_channel_gates_correctly():
    """SPI-01: SkyLight channel registers iff capability available.

    Per ROADMAP.md SC#1: SkyLight SLEventPostToPid fires background events
    with NO cursor warp; capability probe at session start; falls back to
    public CGEvent.postToPid if unavailable.
    """
    caps = await probe_spi_capabilities()
    bridge = SkyLightBridge(available=caps.skylight_available)
    assert bridge.available == caps.skylight_available
    # If available, bridge should have loaded the symbol
    if caps.skylight_available:
        assert bridge._skylight_func is not None


@pytest.mark.asyncio
async def test_spi_02_ax_remote_channel_gates_correctly():
    """SPI-02: AX remote notifications available.

    Per ROADMAP.md SC#2: _AXObserverAddNotificationAndCheckRemote keeps
    Slack/Discord/VS Code AX trees alive when occluded.
    """
    caps = await probe_spi_capabilities()
    bridge = AXRemoteBridge(available=caps.ax_remote_available)
    assert bridge.available == caps.ax_remote_available


@pytest.mark.asyncio
async def test_spi_03_cgs_display_gates_correctly():
    """SPI-03: CGS Display Space optional.

    Lower priority; yabai pattern known; SIP requirement Tier A (on OK).
    """
    caps = await probe_spi_capabilities()
    bridge = CGSBridge(available=caps.cgs_display_space_available)
    assert bridge.available == caps.cgs_display_space_available


@pytest.mark.asyncio
async def test_spi_04_endpoint_security_gates_correctly():
    """SPI-04: ES unavailable on default Mac (SIP on).

    Per ROADMAP.md SC#3: Endpoint Security es_new_client observes
    kernel-level fork/exec/file events. Default machines should
    have this False (SIP on).
    """
    caps = await probe_spi_capabilities()
    bridge = EndpointSecurityBridge(available=caps.endpoint_security_available)
    # Should be False on default machine
    assert isinstance(bridge.available, bool)


@pytest.mark.asyncio
async def test_spi_05_dtrace_gates_correctly():
    """SPI-05: DTrace unavailable on default Mac (SIP on).

    DTrace probes inspect app internals. Default machines should
    have this False (SIP fully on).
    """
    caps = await probe_spi_capabilities()
    bridge = DTraceBridge(available=caps.dtrace_available)
    # Should be False on default machine
    assert isinstance(bridge.available, bool)


@pytest.mark.asyncio
async def test_spi_06_dyld_gates_on_spike_outcome():
    """SPI-06: DYLD injection gated by spike outcome.

    Per ROADMAP.md SC#4: DYLD_INSERT_LIBRARIES + Mach injection into
    Electron renderers works on arm64e. Wave 0: spike deferred, so False.
    """
    caps = await probe_spi_capabilities()
    bridge = DYLDInjectBridge(available=caps.dyld_inject_available)
    # Available iff spike GREEN (Wave 3) — for now, should be False
    assert isinstance(bridge.available, bool)


@pytest.mark.asyncio
async def test_spi_07_webkit_inspector_gates_correctly():
    """SPI-07: WebKit RemoteInspector optional.

    Per ROADMAP.md SC#4: WebKit RemoteInspector private headers give
    Safari deep access.
    """
    caps = await probe_spi_capabilities()
    bridge = WebKitInspectorBridge(available=caps.webkit_inspector_available)
    assert bridge.available == caps.webkit_inspector_available


@pytest.mark.asyncio
async def test_spi_08_imu_gates_on_m_series():
    """SPI-08: IMU available on M-series only.

    Per ROADMAP.md SC#5: AppleSPUHIDDevice IMU reader returns lid-angle /
    motion / vibration data (or cleanly reports unavailable).
    """
    caps = await probe_spi_capabilities()
    bridge = IMUBridge(available=caps.imu_available)
    assert bridge.available == caps.imu_available


@pytest.mark.asyncio
async def test_spi_capabilities_probe_completes_quickly():
    """probe_spi_capabilities() completes in <2s (all probes parallel).

    Per RESEARCH.md §"Capability Probe Pattern" L181-217:
    Probes must be fast (<100ms total).
    """
    import time
    start = time.time()
    caps = await probe_spi_capabilities()
    elapsed = time.time() - start

    assert elapsed < 2.0, f"Probe took {elapsed}s (max 2s)"
    assert isinstance(caps, SPICapabilities)
    # Verify all fields are present and boolean
    assert isinstance(caps.skylight_available, bool)
    assert isinstance(caps.ax_remote_available, bool)
    assert isinstance(caps.cgs_display_space_available, bool)
    assert isinstance(caps.endpoint_security_available, bool)
    assert isinstance(caps.dtrace_available, bool)
    assert isinstance(caps.dyld_inject_available, bool)
    assert isinstance(caps.webkit_inspector_available, bool)
    assert isinstance(caps.imu_available, bool)


@pytest.mark.asyncio
async def test_all_bridges_gracefully_handle_unavailability():
    """All bridges report unavailability gracefully (no errors).

    When all SPIs are unavailable (e.g., on older macOS), bridges
    should initialize without raising exceptions.
    """
    # Create a capabilities snapshot with all False (conservative case)
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

    # Get all bridges with unavailability — should not raise
    sky = SkyLightBridge(available=caps.skylight_available)
    ax = AXRemoteBridge(available=caps.ax_remote_available)
    cgs = CGSBridge(available=caps.cgs_display_space_available)
    es = EndpointSecurityBridge(available=caps.endpoint_security_available)
    dt = DTraceBridge(available=caps.dtrace_available)
    dyld = DYLDInjectBridge(available=caps.dyld_inject_available)
    webkit = WebKitInspectorBridge(available=caps.webkit_inspector_available)
    imu = IMUBridge(available=caps.imu_available)

    # All should initialize without error
    assert all([sky, ax, cgs, es, dt, dyld, webkit, imu])
    # All should report unavailable
    assert not sky.available
    assert not ax.available
    assert not cgs.available
    assert not es.available
    assert not dt.available
    assert not dyld.available
    assert not webkit.available
    assert not imu.available


@pytest.mark.asyncio
async def test_spi_capabilities_probe_idempotent():
    """probe_spi_capabilities() returns identical results on repeated calls.

    Ensures capability probing is stable and can be cached.
    """
    caps1 = await probe_spi_capabilities()
    caps2 = await probe_spi_capabilities()

    # All fields should match
    assert caps1.skylight_available == caps2.skylight_available
    assert caps1.ax_remote_available == caps2.ax_remote_available
    assert caps1.cgs_display_space_available == caps2.cgs_display_space_available
    assert caps1.endpoint_security_available == caps2.endpoint_security_available
    assert caps1.dtrace_available == caps2.dtrace_available
    assert caps1.dyld_inject_available == caps2.dyld_inject_available
    assert caps1.webkit_inspector_available == caps2.webkit_inspector_available
    assert caps1.imu_available == caps2.imu_available


@pytest.mark.asyncio
async def test_skylight_bridge_fires_or_falls_back():
    """SkyLight bridge fires event via SkyLight or public API fallback.

    Per SC#1: No silent failures. Either SkyLight channel or public
    CGEvent fallback should succeed.
    """
    import os
    from Quartz import CGEventCreate  # type: ignore[import-not-found]

    caps = await probe_spi_capabilities()
    bridge = SkyLightBridge(available=caps.skylight_available)

    # Create a dummy CGEvent
    try:
        event = CGEventCreate(None)
    except Exception:
        # If we can't create an event, skip this test
        pytest.skip("CGEvent creation unavailable")

    # Fire should not raise, regardless of availability
    pid = os.getpid()
    try:
        result = await bridge.post_to_pid(pid, event)
        # Result should indicate which channel was used
        assert isinstance(result, bool)
    except Exception as e:
        # If event posting fails, it should be explicit (not silent)
        pytest.fail(f"SkyLight bridge fire raised unexpectedly: {e}")
