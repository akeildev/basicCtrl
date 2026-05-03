"""SPI-02: AX remote notifications for occluded-app automation.

Per RESEARCH.md §"AX Remote Notifications (SPI-02)" L78-91:
- Private HIServices SPI: _AXObserverAddNotificationAndCheckRemote
- Enables Slack/Discord/VS Code background automation when occluded
- Already available in Phase 2 AXObserver; this formalizes as SPI-02

PITFALL P14 (ROADMAP Phase 1 BLOCKER): AX notifs fail on web/Electron
→ Solution: _AXObserverAddNotificationAndCheckRemote keeps trees alive.
"""
import logging
from typing import Optional

import structlog
from basicctrl.ax.observer import AXEventBridge

log = structlog.get_logger(__name__)


class AXRemoteBridge:
    """Wrapper for AX remote notifications (Phase 2 formalization).

    Per ARCHITECTURE.md L8 SPI integration tier:
    Already available; this just documents SPI status and gating.
    """

    def __init__(self, available: bool = True):
        """
        Args:
            available: Capability probe result (True if _AXObserverAddNotificationAndCheckRemote is available)
        """
        self.available = available
        # Delegate to Phase 2 AXEventBridge (already has subscription logic)
        self._bridge: Optional[AXEventBridge] = None

        if available:
            log.info("ax_remote_bridge_loaded", available=True)
        else:
            log.info("ax_remote_bridge_loaded", available=False, fallback="public_AXObserverAddNotification")

    def set_event_bridge(self, bridge: AXEventBridge) -> None:
        """Set the AXEventBridge instance for delegation.

        Args:
            bridge: AXEventBridge instance from Phase 2
        """
        self._bridge = bridge

    async def subscribe_with_remote_support(
        self, pid: int, element, element_key: str, notifications: list[str], action_id: str
    ):
        """Subscribe to AX notifications with remote support (keeps occluded trees alive).

        Delegates to Phase 2 AXEventBridge, which uses the public AXObserverAddNotification
        by default. If capability.ax_remote_available=True, the AXEventBridge can optionally
        use _AXObserverAddNotificationAndCheckRemote for Electron app occluded-app support.

        Args:
            pid: Process ID of target app (Slack, Discord, VS Code, etc)
            element: AXUIElement reference
            element_key: Stable key for the element (e.g., "slack/DM[5]")
            notifications: List of notification types (e.g., ["AXValueChanged", "AXTitleChanged"])
            action_id: Unique action identifier for this subscription

        Returns:
            Subscription handle (from Phase 2 AXEventBridge.subscribe)
        """
        if self._bridge is None:
            raise RuntimeError("AXRemoteBridge not initialized — call set_event_bridge first")

        if not self.available:
            log.debug(
                "ax_remote_unavailable_using_public_api",
                pid=pid,
                element_key=element_key,
            )

        try:
            # Delegate to Phase 2 AXEventBridge
            subscription = self._bridge.subscribe(pid, element, element_key, notifications, action_id)

            log.info(
                "ax_remote_subscription_created",
                pid=pid,
                element_key=element_key,
                notification_count=len(notifications),
                spi_available=self.available,
            )
            return subscription
        except Exception as e:
            log.error(
                "ax_remote_subscription_failed",
                pid=pid,
                element_key=element_key,
                error=str(e),
            )
            raise


# Module-level singleton
_bridge: Optional[AXRemoteBridge] = None


async def get_ax_remote_bridge(capabilities) -> AXRemoteBridge:
    """Get or initialize AX remote bridge.

    Args:
        capabilities: SPICapabilities from Wave 0 probe.py

    Returns:
        AXRemoteBridge instance
    """
    global _bridge
    if _bridge is None:
        _bridge = AXRemoteBridge(available=capabilities.ax_remote_available)
    return _bridge


def is_ax_remote_available(capabilities) -> bool:
    """Check if AX remote SPI is available.

    Args:
        capabilities: SPICapabilities from Wave 0 probe.py

    Returns:
        True if _AXObserverAddNotificationAndCheckRemote is available
    """
    return capabilities.ax_remote_available
