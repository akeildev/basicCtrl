"""SkyLight SLEventPostToPid bridge for background event delivery.

Per RESEARCH.md §"SkyLight SLEventPostToPid (SPI-01)" L56-75:
- Symbol exists in /System/Library/PrivateFrameworks/SkyLight.framework/SkyLight
- Background events (no cursor warp) — higher power than public CGEvent
- Capability probe via dlsym (handled in probe.py)
- Public fallback: CGEvent.postToPid

PITFALL P17: SkyLight breaks across macOS updates → capability probe + version-pinned
signatures + public-API fallback (this file implements fallback logic).
"""
import asyncio
import ctypes
import logging
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# Symbol signature from RESEARCH.md code shape (L68-70)
# @_silgen_name("SLEventPostToPid")
# func SLEventPostToPid(_ pid: pid_t, _ event: CGEvent) -> Void


class SkyLightBridge:
    """Wrapper for SkyLight.framework SLEventPostToPid symbol.

    Per ARCHITECTURE.md L8 SPI integration tier:
    "Every SPI has a public-API fallback — no SPIs are gating features."
    """

    def __init__(self, available: bool = False):
        """
        Args:
            available: Result of probe_skylight() from probe.py
        """
        self.available = available
        self._skylight_func = None

        if self.available:
            try:
                libc = ctypes.CDLL(None)
                self._skylight_func = libc.SLEventPostToPid
                self._skylight_func.argtypes = [ctypes.c_int32, ctypes.py_object]
                self._skylight_func.restype = None
                log.info("skylight_bridge_loaded", available=True)
            except (AttributeError, OSError) as e:
                log.warning("skylight_bridge_load_failed", error=str(e), falling_back=True)
                self.available = False

    async def post_to_pid(self, pid: int, event) -> bool:
        """Fire background event via SkyLight or fallback to public CGEvent.

        Args:
            pid: Target process ID
            event: CGEvent to deliver (pre-constructed by caller)

        Returns:
            True if delivered via SkyLight; False if fallback used (but still delivered)
        """
        try:
            if self.available and self._skylight_func:
                # Async wrapper for sync ctypes call
                await asyncio.to_thread(self._skylight_func, pid, event)
                log.info("skylight_event_posted", pid=pid, via="SkyLight")
                return True
            else:
                # Fallback to public API (cursor visible, but works)
                from Quartz import CGEventPost, kCGEventTapOptionDefault  # type: ignore[import-not-found]

                await asyncio.to_thread(CGEventPost, kCGEventTapOptionDefault, event)
                log.info("skylight_event_posted", pid=pid, via="CGEvent_fallback")
                return False
        except Exception as e:
            log.error("skylight_post_failed", pid=pid, error=str(e))
            raise


# Module-level singleton initialized once at session start
_bridge: Optional[SkyLightBridge] = None


async def get_skylight_bridge(capabilities) -> SkyLightBridge:
    """Get or initialize SkyLight bridge.

    Per RESEARCH.md Capability Probe Pattern L181-217:
    "Every SPI needs a probe that runs at session start and caches the result."

    Args:
        capabilities: SPICapabilities from phase 6 Wave 0 probe

    Returns:
        SkyLightBridge instance (always returns, fallback graceful)
    """
    global _bridge
    if _bridge is None:
        _bridge = SkyLightBridge(available=capabilities.skylight_available)
    return _bridge


async def is_skylight_available(capabilities) -> bool:
    """Check if SkyLight is available on this system.

    Used by channel_registry to gate C1_SPI channel registration.
    """
    bridge = await get_skylight_bridge(capabilities)
    return bridge.available
