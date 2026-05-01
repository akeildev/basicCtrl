"""SPI-07: WebKit RemoteInspector for Safari deep access.

Per RESEARCH.md §"WebKit RemoteInspector private headers (Safari deep access)" L35, L50:
- Private framework: WebInspectorUI / RemoteInspector — symbols in WebKit.framework
- Use case: Safari deep access (DOM/JS/network) — like Phase 2's T2 CDP for Electron, but for native Safari
- Capability gate: probe checks for RemoteInspector header availability
- Public-API fallback: AppleScript via Safari's "do JavaScript" (less powerful but works without Remote Automation)

Per PITFALL-P17: Capability probe at session start; graceful fallback if unavailable.
"""
import structlog

log = structlog.get_logger(__name__)


class WebKitInspectorBridge:
    """Wrapper for WebKit RemoteInspector private headers (Safari).

    Stub implementation for Phase 6 Wave 1.
    Full implementation deferred until RemoteInspector protocol is documented or reverse-engineered.

    Per RESEARCH.md L50: "MEDIUM confidence. Private API; check macOS 26 availability.
    Fallback: T3 AppleScript do JavaScript."
    """

    def __init__(self, available: bool = False):
        """Initialize the WebKit inspector bridge.

        Args:
            available: True if RemoteInspector private headers are accessible.
        """
        self.available = available
        if available:
            log.info("webkit_inspector_bridge_loaded", available=True)
        else:
            log.debug("webkit_inspector_bridge_unavailable", will_fallback_to_applescript=True)

    async def evaluate_js_in_safari(self, script: str) -> str:
        """Evaluate JavaScript in Safari (optional advanced feature).

        Requires: RemoteInspector private API + Safari "Allow Remote Automation" enabled.
        Fallback: T3 AppleScript 'do JavaScript' (handled by translator layer).

        Args:
            script: JavaScript code to evaluate in Safari's JS context.

        Returns:
            Result string from JS evaluation, or None if unavailable.
        """
        if not self.available:
            log.warning(
                "webkit_inspector_unavailable; fallback to AppleScript",
                reason="RemoteInspector not available",
            )
            return None

        # Implementation deferred: RemoteInspector protocol is undocumented.
        # Phase 6 Wave 1 ships as stub. Phase 6+ may add Safari deep access.
        log.debug("webkit_evaluate_js_deferred", script_len=len(script))
        return None


_bridge = None


async def get_webkit_inspector_bridge(capabilities):
    """Factory for WebKitInspectorBridge (cached).

    Called once at session start after probe_spi_capabilities() completes.
    Caches the bridge instance for the session.

    Args:
        capabilities: SPICapabilities object with webkit_inspector_available flag.

    Returns:
        WebKitInspectorBridge instance (cached).
    """
    global _bridge
    if _bridge is None:
        _bridge = WebKitInspectorBridge(available=capabilities.webkit_inspector_available)
    return _bridge
