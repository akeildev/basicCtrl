"""HealEvent Pydantic model for auditable selector healing.

Per CONTEXT.md D-14, D-20: Pydantic frozen HealEvent emitted by recovery
branches when a healed selector is discovered. Only STABLE LOCATOR TIERs
(AXIdentifier, AXLabel, AXTitle, AXRoleDescription) are written back to the
canonical cassette; Vision and Coordinate-based heals are session-only.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


LocatorTier = Literal[
    "AXIdentifier", "AXLabel", "AXTitle", "AXRoleDescription", "Vision", "Coordinate"
]


class HealEvent(BaseModel):
    """Immutable event emitted when a recovery branch heals a selector.

    Fields:
      - old_locator: original (stale) selector that failed
      - new_locator: healed selector that worked
      - reason: why heal happened (e.g. "uitag regrounding", "AX role changed")
      - trace_id: UUID linking to action_id for traceability
      - ts: timestamp of heal
      - locator_tier: stability tier (determines cassette write-back eligibility)
      - source_branch: which recovery branch produced this heal (e.g. "B1_RESCROLL")
    """

    model_config = ConfigDict(frozen=True)

    old_locator: str
    new_locator: str
    reason: str
    trace_id: str
    ts: datetime = Field(default_factory=datetime.utcnow)
    locator_tier: LocatorTier
    source_branch: str

    def is_stable_tier(self) -> bool:
        """Return True if locator_tier is stable (cassette-writable).

        Per D-20: AXIdentifier, AXLabel, AXTitle, AXRoleDescription are
        stable. Vision and Coordinate are session-only (never write back).
        """
        stable_tiers = {
            "AXIdentifier",
            "AXLabel",
            "AXTitle",
            "AXRoleDescription",
        }
        return self.locator_tier in stable_tiers

    def serialize_for_ndjson(self) -> dict:
        """Return dict suitable for NDJSON serialization.

        Converts ts to ISO string; other fields pass through.
        """
        return {
            "old_locator": self.old_locator,
            "new_locator": self.new_locator,
            "reason": self.reason,
            "trace_id": self.trace_id,
            "ts": self.ts.isoformat(),
            "locator_tier": self.locator_tier,
            "source_branch": self.source_branch,
        }
