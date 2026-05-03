"""Cassette NDJSON format with step-by-step record of actions and their outcomes.

Per CONTEXT.md D-18: Cassette is a session-level replay artifact that records
a sequence of actions (steps) taken to achieve a goal. Each step captures:
  - Hoare triple (pre-condition, canonical action, post-condition)
  - Visual state (screenshot pHash for replay matching)
  - Structural state (AX subtree hash for verification)
  - Healed selectors (if this step was later healed by recovery)

Schema versioning (P-06 mitigation): cassettes include schema_version field
so replay can validate forward/backward compatibility.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from basicctrl.state.causal_dag import ActionCanonical, HoarePost, HoarePre


log = logging.getLogger(__name__)


class CassetteStep(BaseModel):
    """Single step in a cassette: action + pre/post conditions + visual state."""

    model_config = ConfigDict(frozen=True)

    step_idx: int  # Ordinal position in cassette
    hoare_pre: HoarePre  # State before action
    action_canonical: ActionCanonical  # Action that was taken
    hoare_post: HoarePost  # State after action
    screenshot_phash: str  # Perceptual hash of screenshot after action
    ax_subtree_hash: str  # Hash of AX subtree at target element
    healed_selectors: list[str] = Field(
        default_factory=list
    )  # Any selectors healed at this step


class Cassette:
    """Container for a sequence of replay steps.

    Attributes:
        schema_version: version string (e.g., "1.0") — bump on format changes
        steps: list of CassetteStep objects
        cache_key: SHA-256 key for persistence
        bundle_id: app bundle ID (e.g., "com.apple.iWork.Pages")
        instruction: user instruction that led to this cassette
    """

    schema_version: str = "1.0"

    def __init__(
        self,
        cache_key: str,
        bundle_id: str,
        instruction: str,
    ):
        self.cache_key = cache_key
        self.bundle_id = bundle_id
        self.instruction = instruction
        self.steps: list[CassetteStep] = []

    def add_step(self, step: CassetteStep) -> None:
        """Append step to steps list."""
        self.steps.append(step)

    def to_ndjson(self) -> str:
        """Serialize cassette to NDJSON format.

        Format:
          Line 1: {"_metadata": {"schema_version": "1.0", "cache_key": "...", ...}}
          Lines 2+: one JSON line per CassetteStep
        """
        lines: list[str] = []

        # Metadata line
        metadata = {
            "_metadata": {
                "schema_version": self.schema_version,
                "cache_key": self.cache_key,
                "bundle_id": self.bundle_id,
                "instruction": self.instruction,
            }
        }
        lines.append(json.dumps(metadata))

        # Step lines
        for step in self.steps:
            step_dict = {
                "step_idx": step.step_idx,
                "hoare_pre": step.hoare_pre.model_dump(),
                "action_canonical": step.action_canonical.model_dump(),
                "hoare_post": step.hoare_post.model_dump(),
                "screenshot_phash": step.screenshot_phash,
                "ax_subtree_hash": step.ax_subtree_hash,
                "healed_selectors": step.healed_selectors,
            }
            lines.append(json.dumps(step_dict))

        return "\n".join(lines)

    @staticmethod
    def from_ndjson(content: str, cache_key: str) -> Cassette:
        """Deserialize cassette from NDJSON content.

        Parses NDJSON, validates schema_version, returns Cassette instance.
        Logs warning if schema_version mismatch (P-06 gate).
        """
        lines = content.strip().split("\n")
        if not lines:
            raise ValueError("Empty NDJSON content")

        # Parse metadata from first line
        metadata_line = json.loads(lines[0])
        metadata = metadata_line.get("_metadata")
        if not metadata:
            raise ValueError("Missing _metadata in first line")

        schema_version = metadata.get("schema_version", "1.0")
        if schema_version != Cassette.schema_version:
            log.warning(
                f"Schema version mismatch: got {schema_version}, expected {Cassette.schema_version}"
            )

        bundle_id = metadata.get("bundle_id", "")
        instruction = metadata.get("instruction", "")

        cassette = Cassette(
            cache_key=cache_key,
            bundle_id=bundle_id,
            instruction=instruction,
        )

        # Parse steps from remaining lines
        for line in lines[1:]:
            if not line.strip():
                continue
            step_dict = json.loads(line)

            # Reconstruct Hoare objects
            hoare_pre = HoarePre(**step_dict["hoare_pre"])
            action_canonical = ActionCanonical(**step_dict["action_canonical"])
            hoare_post = HoarePost(**step_dict["hoare_post"])

            step = CassetteStep(
                step_idx=step_dict["step_idx"],
                hoare_pre=hoare_pre,
                action_canonical=action_canonical,
                hoare_post=hoare_post,
                screenshot_phash=step_dict["screenshot_phash"],
                ax_subtree_hash=step_dict["ax_subtree_hash"],
                healed_selectors=step_dict.get("healed_selectors", []),
            )
            cassette.add_step(step)

        return cassette
