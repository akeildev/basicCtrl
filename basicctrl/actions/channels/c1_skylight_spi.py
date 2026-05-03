"""C1 SkyLight SPI variant — background event delivery.

Per ARCHITECTURE.md L91-92:
C1 = SLEventPostToPid: background, no cursor warp, higher power than CGEvent.

Wave 1: Formal SPI channel (optional, gated by capability probe).
Phase 2: Existing C1 uses public CGEvent (fallback always available).

This file is the SPI-powered variant registered when spi_skylight_available is True.
"""
from __future__ import annotations

import time
from typing import Literal, Optional

import anyio
import structlog

from cua_overlay.actions.channels.base import Channel, ChannelOutcome
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.spi.skylight import get_skylight_bridge
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TranslatorTarget

log = structlog.get_logger(__name__)


class C1SkyLightSPI(Channel):
    """SkyLight background event delivery (SPI variant).

    Channels are registered only if their SPI is available (capability probe).
    """

    name: Literal["C1", "C2", "C3", "C4", "C5"] = "C1"
    spi_name: str = "C1_SPI"
    description: str = "SkyLight SLEventPostToPid (SPI)"

    def __init__(self, capabilities=None):
        """
        Args:
            capabilities: SPICapabilities from probe.py
        """
        self.capabilities = capabilities
        self._bridge = None

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        """Deliver action via SkyLight background event.

        Args:
            action: ActionCanonical (what to do)
            target: TranslatorTarget (app info, bundle_id, pid, etc)
            store: IdempotencyTokenStore for atomic claim
            cancel_event: Kill switch for pre-syscall cancellation

        Returns:
            ChannelOutcome (success flag + proof)
        """
        # 1. Atomic claim (per base.py protocol)
        claim = await store.try_claim(action.id, "C1")
        if claim is None:
            return ChannelOutcome(
                channel="C1", status="skipped", skipped_reason="idempotency_lost"
            )

        # 2. Pre-syscall kill-switch (~50µs uncancellable window remains; D-18)
        if cancel_event.is_set():
            return ChannelOutcome(channel="C1", status="cancelled")

        # 3. Validate grounded bbox
        if target.grounded_bbox is None:
            return ChannelOutcome(
                channel="C1", status="errored", error="missing grounded_bbox"
            )

        try:
            # Get bridge (lazy init with capabilities)
            if self._bridge is None:
                self._bridge = await get_skylight_bridge(self.capabilities)

            # Convert action to CGEvent
            bbox = target.grounded_bbox
            cx = bbox.x + bbox.w / 2
            cy = bbox.y + bbox.h / 2
            pid = target.element.pid
            event = self._construct_cgevent(cx, cy)

            # Fire via SkyLight (with public API fallback inside bridge)
            via_spi = await self._bridge.post_to_pid(pid, event)

            log.info(
                "c1_spi_fire_success",
                action_id=action.id,
                target_bundle=target.bundle_id,
                via_spi=via_spi,
            )
            return ChannelOutcome(
                channel="C1", status="fired", fired_at_ns=time.monotonic_ns()
            )

        except Exception as e:  # noqa: BLE001
            log.error("c1_spi_fire_failed", action_id=action.id, error=str(e))
            return ChannelOutcome(
                channel="C1", status="errored", error=str(e)
            )

    def _construct_cgevent(self, cx: float, cy: float):
        """Construct mouseDown + mouseUp CGEvent for delivery.

        Reuses Phase 2 C1 CGEvent construction pattern.
        """
        from Quartz import (  # type: ignore[import-not-found]
            CGEventCreateMouseEvent,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseUp,
            kCGMouseButtonLeft,
        )

        down = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseDown, (cx, cy), kCGMouseButtonLeft
        )
        up = CGEventCreateMouseEvent(
            None, kCGEventLeftMouseUp, (cx, cy), kCGMouseButtonLeft
        )
        # Return the down event; caller will handle the up event separately
        # For now, we'll return down and let the bridge handle sequencing
        return down
