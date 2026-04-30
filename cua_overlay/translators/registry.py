"""TranslatorRegistry — tier-keyed registration + priority-ordered selection.

Race orchestrator (Plan 02-10) calls select_for_priority(profile.translator_priority)
to iterate translators in the order the AppProfile classifier preferred.
"""
from __future__ import annotations

from typing import Optional

import structlog

from cua_overlay.translators.base import Translator


_log = structlog.get_logger()


class TranslatorRegistry:
    """Tier-keyed translator registry (T1..T5).

    Translators register themselves at module import; the race orchestrator
    requests them by translator_priority order from AppProfile.

    Per D-14 the channel binding is soft — translators provide targets;
    channels deliver. The registry exposes only target resolution.
    """

    def __init__(self) -> None:
        self._translators: dict[str, Translator] = {}

    def register(self, translator: Translator) -> None:
        """Register a translator under its tier name. Idempotent — re-register
        replaces (useful for tests)."""
        if translator.tier in self._translators:
            _log.warning(
                "translator.replaced", tier=translator.tier, prev=str(self._translators[translator.tier])
            )
        self._translators[translator.tier] = translator
        _log.info("translator.registered", tier=translator.tier)

    def get(self, tier: str) -> Optional[Translator]:
        """Return the registered translator for tier (T1..T5) or None if none."""
        return self._translators.get(tier)

    def select_for_priority(self, priority: list[str]) -> list[Translator]:
        """Translate a priority list (e.g. ['T1','T4']) into the corresponding
        translator instances. Skips tiers that aren't registered (during
        partial Wave 2 builds some tiers may be unregistered; race orchestrator
        handles short lists gracefully).
        """
        out: list[Translator] = []
        for tier in priority:
            t = self._translators.get(tier)
            if t is not None:
                out.append(t)
            else:
                _log.debug("translator.tier_not_registered", tier=tier)
        return out
