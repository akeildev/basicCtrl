"""Tests for SPI-06 DYLD injection (conditional on spike outcome).

Per RESEARCH.md §"DYLD Injection + arm64e Signing (SPI-06)" L92-131:
SPIKE OUTCOME (Wave 3, 06-07): GREEN

Tests validate:
1. Bridge respects spike outcome (available=True)
2. Graceful fallback if unavailable
3. Dylib path resolution
4. Architecture and signature validation
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from basicctrl.spi.dyld_inject import (
    DYLDInjectBridge,
    get_dyld_inject_bridge,
    is_dyld_inject_available,
)
from basicctrl.spi.probe import probe_dyld_inject


class TestProbe:
    """Test the capability probe."""

    def test_probe_dyld_inject_returns_true(self):
        """Per spike GREEN: probe should return True on Apple Silicon."""
        result = probe_dyld_inject()
        assert result is True, "Spike GREEN outcome: DYLD injection available"


class TestDYLDInjectBridge:
    """Test DYLDInjectBridge initialization and behavior."""

    def test_bridge_available_when_spike_green(self):
        """Bridge availability reflects spike outcome."""
        bridge = DYLDInjectBridge(available=True)
        assert bridge.available is True

    def test_bridge_unavailable_when_spike_red(self):
        """If spike had failed, bridge would gracefully be unavailable."""
        bridge = DYLDInjectBridge(available=False)
        assert bridge.available is False

    def test_bridge_logs_status(self):
        """Bridge logs initialization status."""
        with patch("basicctrl.spi.dyld_inject.log") as mock_log:
            bridge = DYLDInjectBridge(available=True)
            # Should log that bridge is loaded
            mock_log.info.assert_called()

    def test_bridge_fallback_logged_when_unavailable(self):
        """When unavailable, logs fallback to T1 AX."""
        with patch("basicctrl.spi.dyld_inject.log") as mock_log:
            bridge = DYLDInjectBridge(available=False)
            # Should log unavailable status
            assert mock_log.info.called or mock_log.warning.called


class TestDYLDInjectDylibPath:
    """Test dylib path resolution."""

    def test_default_dylib_path_construction(self):
        """Bridge constructs default dylib path correctly."""
        bridge = DYLDInjectBridge(available=True)
        path = bridge._default_dylib_path()
        assert "spi-dyld" in path
        assert path.endswith("cua_inject.dylib")

    def test_custom_dylib_path(self):
        """Bridge accepts custom dylib path."""
        custom_path = "/tmp/my_custom.dylib"
        bridge = DYLDInjectBridge(available=True, dylib_path=custom_path)
        assert bridge.dylib_path == custom_path


class TestDYLDInjectValidation:
    """Test dylib validation (architecture and signature)."""

    @pytest.mark.asyncio
    async def test_validate_dylib_missing_file(self):
        """Validation fails gracefully if dylib doesn't exist."""
        bridge = DYLDInjectBridge(available=True, dylib_path="/nonexistent/dylib.dylib")
        result = await bridge.validate_dylib()
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_dylib_unavailable_returns_false(self):
        """If bridge unavailable, validation returns False."""
        bridge = DYLDInjectBridge(available=False)
        result = await bridge.validate_dylib()
        assert result is False


class TestDYLDInjectSingleton:
    """Test module-level singleton pattern."""

    @pytest.mark.asyncio
    async def test_get_dyld_inject_bridge_singleton(self):
        """get_dyld_inject_bridge returns same instance on repeated calls."""
        # Mock capabilities
        capabilities = MagicMock()
        capabilities.dyld_inject_available = True

        # Get bridge twice
        bridge1 = await get_dyld_inject_bridge(capabilities)
        bridge2 = await get_dyld_inject_bridge(capabilities)

        # Should be the same object
        assert bridge1 is bridge2

    @pytest.mark.asyncio
    async def test_is_dyld_inject_available(self):
        """is_dyld_inject_available queries bridge availability."""
        capabilities = MagicMock()
        capabilities.dyld_inject_available = True

        result = await is_dyld_inject_available(capabilities)
        assert result is True


class TestDYLDInjectIntegration:
    """Integration tests (skipped if spike RED)."""

    @pytest.mark.skipif(
        not probe_dyld_inject(),
        reason="Spike outcome RED; DYLD injection unavailable",
    )
    @pytest.mark.asyncio
    async def test_inject_into_electron_app_unavailable_logs_fallback(self):
        """If unavailable, logs fallback to T1 AX."""
        bridge = DYLDInjectBridge(available=False)
        with patch("basicctrl.spi.dyld_inject.log") as mock_log:
            result = await bridge.inject_into_electron_app(
                "/Applications/Slack.app", "com.tinyspeck.slackmacgap"
            )
            assert result is False
            mock_log.warning.assert_called()

    @pytest.mark.skipif(
        not probe_dyld_inject(),
        reason="Spike outcome RED; DYLD injection unavailable",
    )
    @pytest.mark.asyncio
    async def test_inject_missing_dylib(self):
        """Injection fails gracefully if dylib doesn't exist."""
        bridge = DYLDInjectBridge(available=True, dylib_path="/nonexistent/dylib.dylib")
        result = await bridge.inject_into_electron_app(
            "/Applications/Slack.app", "com.tinyspeck.slackmacgap"
        )
        assert result is False


# Fixture for spike GREEN outcome (used in integration tests)
@pytest.fixture
def spike_green():
    """Fixture that skips test if spike GREEN not confirmed."""
    if not probe_dyld_inject():
        pytest.skip("Spike outcome: RED — DYLD injection unavailable")
    return True
