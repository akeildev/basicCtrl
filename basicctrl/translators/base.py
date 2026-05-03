"""Translator Protocol + TranslatorTarget + TargetSpec.

Per CONTEXT.md D-01..D-07: each translator (T1 AX, T2 CDP, T3 AS, T4
Vision, T5 Pixel) implements this same Protocol so the race orchestrator
fans out uniformly.

TranslatorTarget is a Pydantic model carrying the resolved target plus
optional handles each translator type provides (ax_element for T1,
cdp_node_id+cdp_session_id for T2, as_target_spec for T3,
grounded_bbox for T4/T5).
"""
from __future__ import annotations

from typing import Any, Literal, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from basicctrl.state.graph import Bbox, UIElement


class TargetSpec(BaseModel):
    """Caller's request for a target. Translator-agnostic; each translator
    interprets the fields it understands.

    `key` is the canonical composite key (e.g. role_path + label + bbox-centroid)
    used by the verifier to match push events. `x`/`y` is the original cursor
    coordinate (always present). Other fields are optional hints.
    """

    model_config = ConfigDict(frozen=True)

    key: str = ""
    x: int = 0
    y: int = 0
    label: str = ""
    role: str = ""
    aria_label: str = ""
    css: str = ""              # T2 CDP DOM selector
    as_verb: str = ""          # T3 AppleScript verb fragment ("activate", "click button 1 of...")


class TranslatorTarget(BaseModel):
    """Resolved target ready for a Channel to fire on.

    Translator-agnostic envelope; each translator populates the fields its
    Channel will read:

    * T1 AX → element + ax_element
    * T2 CDP → element + cdp_node_id + cdp_session_id + grounded_bbox
    * T3 AS → element + as_target_spec
    * T4 Vision → element + grounded_bbox
    * T5 Pixel → element + grounded_bbox + extras['pre_phash']
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    element: UIElement
    ax_element: Optional[Any] = None       # AXUIElementRef opaque (T1)
    cdp_node_id: Optional[int] = None      # CDP DOM.NodeId (T2)
    cdp_session_id: Optional[str] = None   # CDP Target session (T2)
    as_target_spec: Optional[str] = None   # AppleScript address spec (T3)
    grounded_bbox: Optional[Bbox] = None   # uitag/pixel bbox (T4/T5)
    extras: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Translator(Protocol):
    """Per-tier resolver. Implemented by T1AXTranslator..T5PixelTranslator."""

    tier: Literal["T1", "T2", "T3", "T4", "T5"]

    async def resolve(
        self,
        bundle_id: str,
        pid: int,
        target_spec: TargetSpec,
    ) -> Optional[TranslatorTarget]:
        """Resolve target. Returns None if this translator can't address it."""
        ...

    async def validate(self, target: TranslatorTarget) -> bool:
        """Pre-action validity check (P28 mitigation per ACT-04). Translators
        that don't have an analogous live-state check should return True."""
        ...
