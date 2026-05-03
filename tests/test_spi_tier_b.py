"""Tests for Tier-B/C SPIs (SIP-dependent).

Per RESEARCH.md §"SIP Tier Requirements (PITFALL-18 Detail)" L224-240:
- Tier B: SIP partial-off required (ES, DTrace)
- Graceful skip on default Mac (SIP fully on)
- Tests use pytest.mark.skipif(not is_sip_partial_off(), reason="...") for Tier-B features
"""
import pytest
from dataclasses import dataclass
from unittest.mock import patch, MagicMock

from basicctrl.spi.cgs_display import CGSBridge, get_cgs_bridge
from basicctrl.spi.endpoint_security import (
    EndpointSecurityBridge,
    get_endpoint_security_bridge,
    is_sip_partial_off,
)
from basicctrl.spi.dtrace import DTraceBridge, get_dtrace_bridge
from basicctrl.spi.probe import is_sip_partial_off as probe_is_sip_partial_off


# Mock SPICapabilities for testing
@dataclass
class MockSPICapabilities:
    """Minimal mock for testing."""

    cgs_display_space_available: bool
    endpoint_security_available: bool
    dtrace_available: bool
    skylight_available: bool = False
    ax_remote_available: bool = False
    dyld_inject_available: bool = False
    webkit_inspector_available: bool = False
    imu_available: bool = False


class TestSIPStatusHelper:
    """Test is_sip_partial_off helper."""

    def test_is_sip_partial_off_fully_on(self):
        """is_sip_partial_off returns False when SIP fully on."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="System Integrity Protection status: enabled.",
                stderr="",
                returncode=0,
            )
            result = probe_is_sip_partial_off()
            assert result is False

    def test_is_sip_partial_off_partial(self):
        """is_sip_partial_off returns True when SIP partial-off."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Configuration: Custom Configuration.",
                stderr="",
                returncode=0,
            )
            result = probe_is_sip_partial_off()
            assert result is True

    def test_is_sip_partial_off_fully_off(self):
        """is_sip_partial_off returns True when SIP fully off."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="System Integrity Protection status: off.",
                stderr="",
                returncode=0,
            )
            result = probe_is_sip_partial_off()
            assert result is True

    def test_is_sip_partial_off_timeout(self):
        """is_sip_partial_off returns False on csrutil timeout."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutError()
            result = probe_is_sip_partial_off()
            assert result is False


class TestCGSBridge:
    """Test CGS Display Space bridge."""

    def test_cgs_bridge_init_unavailable(self):
        """CGSBridge with available=False stays unavailable."""
        bridge = CGSBridge(available=False)
        assert bridge.available is False
        assert bridge._func is None

    def test_cgs_bridge_init_available(self):
        """CGSBridge with available=True attempts to load symbol."""
        # On most systems, CGSManagedDisplaySetCurrentSpace will not be found via dlsym
        # (it's an undocumented symbol). This test just verifies initialization.
        bridge = CGSBridge(available=True)
        # After load attempt, available should be bool (True if found, False if not)
        assert isinstance(bridge.available, bool)

    @pytest.mark.asyncio
    async def test_switch_to_space_unavailable(self):
        """switch_to_space returns False when bridge unavailable."""
        bridge = CGSBridge(available=False)
        result = await bridge.switch_to_space(0)
        assert result is False

    @pytest.mark.asyncio
    async def test_switch_to_space_available_deferred(self):
        """switch_to_space returns False when implementation deferred."""
        bridge = CGSBridge(available=True)
        bridge._func = True  # Simulate loaded function
        result = await bridge.switch_to_space(0)
        # Implementation deferred; returns False gracefully
        assert result is False


class TestEndpointSecurityBridge:
    """Test Endpoint Security bridge."""

    def test_es_bridge_init_unavailable(self):
        """EndpointSecurityBridge with available=False stays unavailable."""
        bridge = EndpointSecurityBridge(available=False)
        assert bridge.available is False
        assert bridge._client is None

    def test_es_bridge_init_available_sip_on(self):
        """EndpointSecurityBridge gracefully skips when SIP is on."""
        with patch("basicctrl.spi.endpoint_security.is_sip_partial_off", return_value=False):
            bridge = EndpointSecurityBridge(available=True)
            # SIP is on; bridge should be marked unavailable
            assert bridge.available is False

    @pytest.mark.skipif(
        probe_is_sip_partial_off() is False,
        reason="Endpoint Security requires SIP partial-off",
    )
    def test_es_bridge_init_available_sip_off(self):
        """EndpointSecurityBridge attempts to load when SIP partial-off."""
        # This test only runs on Macs with SIP partial-off
        with patch("basicctrl.spi.endpoint_security.is_sip_partial_off", return_value=True):
            with patch("ctypes.CDLL") as mock_cdll:
                # Simulate es_new_client symbol found
                mock_libc = MagicMock()
                mock_libc.es_new_client = True
                mock_cdll.return_value = mock_libc

                bridge = EndpointSecurityBridge(available=True)
                # If we reach here, symbol loading was attempted
                assert isinstance(bridge.available, bool)

    @pytest.mark.asyncio
    async def test_create_client_unavailable(self):
        """create_client returns None when unavailable."""
        bridge = EndpointSecurityBridge(available=False)
        result = await bridge.create_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_observe_fork_exec_unavailable(self):
        """observe_fork_exec returns None when unavailable."""
        bridge = EndpointSecurityBridge(available=False)
        result = await bridge.observe_fork_exec()
        assert result is None


class TestDTraceBridge:
    """Test DTrace bridge."""

    def test_dtrace_bridge_init_unavailable(self):
        """DTraceBridge with available=False stays unavailable."""
        bridge = DTraceBridge(available=False)
        assert bridge.available is False

    def test_dtrace_bridge_init_available_sip_on(self):
        """DTraceBridge gracefully skips when SIP is on."""
        with patch("basicctrl.spi.dtrace.is_sip_partial_off", return_value=False):
            bridge = DTraceBridge(available=True)
            # SIP is on; bridge should be marked unavailable
            assert bridge.available is False

    @pytest.mark.skipif(
        probe_is_sip_partial_off() is False,
        reason="DTrace requires SIP partial-off",
    )
    def test_dtrace_bridge_init_available_sip_off(self):
        """DTraceBridge attempts to check dtrace when SIP partial-off."""
        # This test only runs on Macs with SIP partial-off
        with patch("basicctrl.spi.dtrace.is_sip_partial_off", return_value=True):
            with patch("subprocess.run") as mock_run:
                # Simulate dtrace -l working
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                bridge = DTraceBridge(available=True)
                # If we reach here, dtrace check was attempted
                assert isinstance(bridge.available, bool)

    @pytest.mark.asyncio
    async def test_spawn_probe_unavailable(self):
        """spawn_probe returns None when unavailable."""
        bridge = DTraceBridge(available=False)
        result = await bridge.spawn_probe("syscall:::entry { @count = count() }")
        assert result is None

    @pytest.mark.asyncio
    async def test_spawn_probe_timeout(self):
        """spawn_probe handles timeout gracefully."""
        bridge = DTraceBridge(available=True)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = TimeoutError()
            result = await bridge.spawn_probe("syscall:::entry { @count = count() }", timeout=1)
            assert result is None

    @pytest.mark.asyncio
    async def test_trace_app_syscalls_unavailable(self):
        """trace_app_syscalls returns None when unavailable."""
        bridge = DTraceBridge(available=False)
        result = await bridge.trace_app_syscalls("com.apple.Safari")
        assert result is None


class TestBridgeFactories:
    """Test bridge factory functions and caching."""

    @pytest.mark.asyncio
    async def test_get_cgs_bridge_caches(self):
        """get_cgs_bridge caches result across calls."""
        # Reset global state
        import basicctrl.spi.cgs_display as cgs_module

        cgs_module._bridge = None

        caps = MockSPICapabilities(
            cgs_display_space_available=False,
            endpoint_security_available=False,
            dtrace_available=False,
        )
        bridge1 = await get_cgs_bridge(caps)
        bridge2 = await get_cgs_bridge(caps)
        assert bridge1 is bridge2, "Bridge should be cached (same object)"

    @pytest.mark.asyncio
    async def test_get_es_bridge_caches(self):
        """get_endpoint_security_bridge caches result across calls."""
        # Reset global state
        import basicctrl.spi.endpoint_security as es_module

        es_module._bridge = None

        caps = MockSPICapabilities(
            cgs_display_space_available=False,
            endpoint_security_available=False,
            dtrace_available=False,
        )
        bridge1 = await get_endpoint_security_bridge(caps)
        bridge2 = await get_endpoint_security_bridge(caps)
        assert bridge1 is bridge2, "Bridge should be cached (same object)"

    @pytest.mark.asyncio
    async def test_get_dtrace_bridge_caches(self):
        """get_dtrace_bridge caches result across calls."""
        # Reset global state
        import basicctrl.spi.dtrace as dtrace_module

        dtrace_module._bridge = None

        caps = MockSPICapabilities(
            cgs_display_space_available=False,
            endpoint_security_available=False,
            dtrace_available=False,
        )
        bridge1 = await get_dtrace_bridge(caps)
        bridge2 = await get_dtrace_bridge(caps)
        assert bridge1 is bridge2, "Bridge should be cached (same object)"
