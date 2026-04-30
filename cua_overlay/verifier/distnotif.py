"""DistributedNotificationCenter scaffold — Phase 1 contract only.

NSDistributedNotificationCenter is the system-wide IPC notification bus on
macOS. Apps emit named notifications (e.g. ``com.apple.iCloud.SyncDidStart``)
that any process can subscribe to. We'll wire this fully in Phase 2 — for now
we lock the Pydantic event contract so downstream callers that need it (e.g.
verifier.aggregator weighted-vote per-action-class) can import the type.

Per 01-RESEARCH.md "Other push sources": Phase 1 scope is "define CDP DOM
event contract as Pydantic schema (no implementation), wire kqueue EVFILT_PROC
for the demo, define DistributedNotification contract".
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class DistributedNotificationEvent(BaseModel):
    """Pydantic contract for a single NSDistributedNotificationCenter event.

    Phase 1 locks the schema; Phase 2 wires the real subscription manager.

    Fields:
        name: notification name, e.g. ``com.apple.iCloud.SyncDidStart``
        sender: optional sender object string (per Apple's API)
        user_info: arbitrary JSON-serialisable dict from the notification
        received_at: timestamp of receipt (set by the observer, not the sender)
    """

    model_config = ConfigDict(frozen=True)

    name: str
    sender: Optional[str] = None
    user_info: dict[str, Any] = Field(default_factory=dict)
    received_at: datetime


class DistributedNotificationObserver:
    """Phase 1 stub — Phase 2 wires NSDistributedNotificationCenter.

    Why ship a stub: downstream Phase 1 code (e.g. verifier.aggregator import)
    needs a stable type to reference. Phase 2 swaps in the real implementation
    without breaking import paths.
    """

    def __init__(self) -> None:
        pass

    def start(self) -> None:
        """Phase 2 wires this. Calling now raises NotImplementedError on purpose."""
        raise NotImplementedError(
            "Phase 2 wires NSDistributedNotificationCenter — Plan 01-04 ships only the contract"
        )

    def stop(self) -> None:
        """Idempotent no-op so callers can safely call stop() in finally blocks."""
