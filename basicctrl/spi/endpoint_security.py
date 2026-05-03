"""SPI-04: Endpoint Security es_new_client (kernel-level fork/exec/file observation).

Per RESEARCH.md §"Per-SPI Status Table" L47:
- Tier B: SIP partial-off required
- Skip gracefully on default Mac (SIP on)
- Requires Endpoint Security entitlement
"""
import ctypes
from typing import Optional
import structlog

from basicctrl.spi.probe import is_sip_partial_off

log = structlog.get_logger(__name__)


class EndpointSecurityBridge:
    """Wrapper for Endpoint Security framework (es_new_client).

    Observes kernel-level fork/exec/file/network events.
    Requires SIP partial-off or full-off + Endpoint Security entitlement.
    Gracefully handles unavailability on default Mac.
    """

    def __init__(self, available: bool = False):
        """Initialize ES bridge.

        Args:
            available: True if probe found es_new_client symbol and SIP allows.
        """
        self.available = available
        self._client = None

        if available:
            self._check_sip_and_entitlement()

    def _check_sip_and_entitlement(self):
        """Verify SIP status and symbol availability.

        Endpoint Security requires:
        1. SIP partial-off or full-off
        2. es_new_client symbol available
        3. Endpoint Security entitlement (app-specific, not checked here)

        On success: _client is set to True (ready to use).
        On failure: _client remains None, available is downgraded to False.
        """
        try:
            # Check SIP status first
            if not is_sip_partial_off():
                log.info(
                    "endpoint_security_unavailable_sip_on",
                    reason="SIP is fully on; Endpoint Security requires SIP partial-off",
                )
                self.available = False
                return

            # Check if es_new_client symbol exists
            libc = ctypes.CDLL(None)
            func = libc.es_new_client
            if func is not None:
                self._client = True
                log.info("endpoint_security_available", sip_status="partial_off")
            else:
                self.available = False
                log.info(
                    "endpoint_security_unavailable", reason="es_new_client symbol not found"
                )
        except (AttributeError, OSError) as e:
            log.warning("endpoint_security_check_failed", error=str(e))
            self.available = False

    async def create_client(self):
        """Create Endpoint Security client.

        Returns:
            True if client created successfully; None if unavailable.

        Note: Raw es_new_client requires complex event handling setup.
        Implementation deferred to Wave 2+.
        """
        if not self.available or self._client is None:
            log.info("endpoint_security_unavailable_skipping_client_creation")
            return None

        try:
            # Implementation deferred: es_new_client setup requires:
            # 1. Define es_event_t and es_client_t opaque types
            # 2. Register es_new_client with ctypes signature
            # 3. Set up event handler callback (requires dispatch_queue)
            # 4. Subscribe to event types (es_subscribe_events)
            # 5. Start message handler loop
            # For now, just log and return None (graceful unavailability).
            log.info("endpoint_security_client_creation_deferred")
            return None
        except Exception as e:
            log.error("endpoint_security_client_creation_failed", error=str(e))
            return None

    async def observe_fork_exec(self):
        """Start observing fork/exec events.

        Returns:
            Generator of fork/exec events if available; None if unavailable.
        """
        if not self.available:
            log.info("endpoint_security_unavailable_skipping_fork_exec_observation")
            return None

        # Implementation deferred
        log.info("endpoint_security_fork_exec_observation_deferred")
        return None


_bridge: Optional[EndpointSecurityBridge] = None


async def get_endpoint_security_bridge(
    capabilities,
) -> Optional[EndpointSecurityBridge]:
    """Get or initialize Endpoint Security bridge.

    Args:
        capabilities: SPICapabilities object from probe_spi_capabilities().

    Returns:
        EndpointSecurityBridge if available (SIP partial-off),
        None if Endpoint Security not available on this Mac.
        Result is cached per session.
    """
    global _bridge
    if _bridge is None:
        _bridge = EndpointSecurityBridge(
            available=capabilities.endpoint_security_available
        )
    return _bridge
