"""ChannelRegistry — name-keyed registration + tier-priority-driven selection.

Race orchestrator (Plan 02-10) calls select(translator_priority, RacePolicy)
to get the channel coroutines to fan out.

Per CONTEXT.md D-14 default tier-to-channel mapping:
    T1 → C2  (kAXPress)
    T2 → C5  (CDP Input.dispatchMouseEvent)
    T3 → C4  (AppleScript)
    T4 → C1  (CGEvent — public; SkyLight upgrade in Phase 6)
    T5 → C3  (CGEvent.postToPid with cursor)

Per CONTEXT.md D-14 the binding is SOFT — translators may request alternate
channels at action time. The default is what select() returns when no
override is given.
"""
from __future__ import annotations

from typing import Optional

import structlog

from basicctrl.actions.channels.base import Channel
from basicctrl.actions.race_policy import RacePolicy


_log = structlog.get_logger()


# D-14 default tier → channel binding.
TIER_TO_CHANNEL_DEFAULT: dict[str, str] = {
    "T1": "C2",
    "T2": "C5",
    "T3": "C4",
    "T4": "C1",
    "T5": "C3",
}


# Inverted map for tier_for_channel reverse lookup. Computed once at module
# import; mutating TIER_TO_CHANNEL_DEFAULT after import will NOT update this
# (tests that mutate TIER_TO_CHANNEL_DEFAULT must also rebuild this map).
CHANNEL_TO_TIER_DEFAULT: dict[str, str] = {v: k for k, v in TIER_TO_CHANNEL_DEFAULT.items()}


class ChannelRegistry:
    """Channel registry. Channels self-register; orchestrator queries by name."""

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def register(self, channel: Channel) -> None:
        """Register a channel under its name (C1..C5). Idempotent."""
        if channel.name in self._channels:
            _log.warning(
                "channel.replaced",
                name=channel.name,
                prev=str(self._channels[channel.name]),
            )
        self._channels[channel.name] = channel
        _log.info("channel.registered", name=channel.name)

    def get(self, name: str) -> Optional[Channel]:
        """Return the registered channel for name (C1..C5) or None."""
        return self._channels.get(name)

    def tier_for_channel(self, channel_name: str) -> Optional[str]:
        """Reverse lookup: given a channel name (C1..C5), return the default
        tier (T1..T5) per D-14 binding. Returns None if channel unknown.

        Used by RaceOrchestrator (Plan 02-10) to fill ActionCanonical.tier
        from the winning ChannelOutcome.channel — the orchestrator does NOT
        know which translator produced the target the winner fired on, so it
        infers tier from the channel via the D-14 default mapping.
        """
        return CHANNEL_TO_TIER_DEFAULT.get(channel_name)

    async def register_with_capabilities(self, capabilities):
        """Register channels based on capability probe results.

        Per RESEARCH.md §"Pattern: Capability-Based Channel Registration" L403-428:
        "Register channels only if their SPIs are available."

        Args:
            capabilities: SPICapabilities from probe.py
        """
        # SPI-optional channels (Wave 1+)
        if capabilities.skylight_available:
            from basicctrl.actions.channels.c1_skylight_spi import C1SkyLightSPI
            self.register(C1SkyLightSPI(capabilities=capabilities))
            _log.info("registered_c1_spi_channel")

    def select(
        self, translator_priority: list[str], policy: RacePolicy
    ) -> list[Channel]:
        """Return channels to fire for this action.

        For RacePolicy.RACE: returns the channel for EACH tier in priority order
        (de-duped — a channel that maps to multiple tiers fires once).

        For RacePolicy.SINGLE_CHANNEL: returns the channel for the FIRST tier
        in priority order (which is the AppProfile-preferred translator).

        Skips tiers whose default channel is not registered (during partial
        Wave 2 builds some channels may be unregistered).
        """
        seen_names: set[str] = set()
        out: list[Channel] = []
        for tier in translator_priority:
            cname = TIER_TO_CHANNEL_DEFAULT.get(tier)
            if cname is None:
                continue
            if cname in seen_names:
                continue
            ch = self._channels.get(cname)
            if ch is None:
                _log.debug("channel.not_registered", name=cname, tier=tier)
                continue
            out.append(ch)
            seen_names.add(cname)
            if policy == RacePolicy.SINGLE_CHANNEL:
                # SINGLE_CHANNEL stops at the first available channel.
                break
        return out
