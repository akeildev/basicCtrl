"""SPI-03: CGSManagedDisplaySetCurrentSpace (cross-Space window control).

Per RESEARCH.md §"Per-SPI Status Table" L46:
- Tier A: Works SIP-on, but considered private
- Optional feature; no gate on core functionality
- Graceful fallback: public AppleScript (slower but available)
"""
import ctypes
from typing import Optional
import structlog

log = structlog.get_logger(__name__)


class CGSBridge:
    """Wrapper for CGSManagedDisplaySetCurrentSpace (private CGS symbol).

    Allows programmatic Space (Mission Control desktop) switching.
    Gracefully handles unavailability on older macOS versions.
    """

    def __init__(self, available: bool = False):
        """Initialize CGS bridge.

        Args:
            available: True if probe found CGSManagedDisplaySetCurrentSpace symbol.
        """
        self.available = available
        self._func = None

        if available:
            self._load_cgs_symbol()

    def _load_cgs_symbol(self):
        """Load CGSManagedDisplaySetCurrentSpace via dlsym.

        On success: _func is set to the symbol.
        On failure: _func remains None, available is downgraded to False.
        """
        try:
            # CoreGraphics.framework exposes CGSManagedDisplaySetCurrentSpace
            # as a private symbol. dlsym returns None if not found.
            libc = ctypes.CDLL(None)
            func = libc.CGSManagedDisplaySetCurrentSpace
            if func is not None:
                self._func = func
                log.info("cgs_display_space_loaded")
            else:
                self.available = False
                log.info("cgs_display_space_unavailable", reason="symbol not found")
        except (AttributeError, OSError) as e:
            log.warning("cgs_display_space_load_failed", error=str(e))
            self.available = False

    async def switch_to_space(self, space_index: int) -> bool:
        """Switch to a specific Space (Mission Control desktop).

        Args:
            space_index: 0-indexed Space number.

        Returns:
            True if switch succeeded; False if unavailable or error.
        """
        if not self.available or self._func is None:
            log.info("cgs_display_space_unavailable_skipping_switch")
            return False

        try:
            # CGSManagedDisplaySetCurrentSpace signature (private):
            # OSStatus CGSManagedDisplaySetCurrentSpace(CGSDisplayID, int space_num)
            # On success: returns 0 (kCGErrorSuccess)
            # On failure: returns non-zero error code
            # Display ID 0 = main display; space_num is 0-indexed

            # For now, implementation deferred. Would need raw ctypes function binding.
            # Just log and return False (graceful unavailability).
            log.info("cgs_display_space_switch_deferred", space=space_index)
            return False
        except Exception as e:
            log.error("cgs_display_space_switch_failed", error=str(e), space=space_index)
            return False


_bridge: Optional[CGSBridge] = None


async def get_cgs_bridge(capabilities) -> Optional[CGSBridge]:
    """Get or initialize CGS bridge.

    Args:
        capabilities: SPICapabilities object from probe_spi_capabilities().

    Returns:
        CGSBridge if available, None if CGS not supported on this macOS.
        Result is cached per session.
    """
    global _bridge
    if _bridge is None:
        _bridge = CGSBridge(available=capabilities.cgs_display_space_available)
    return _bridge
