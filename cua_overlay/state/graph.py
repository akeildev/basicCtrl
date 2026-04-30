"""STATE-01 — UIElement, Bbox, Edge, EdgeKind, Capability, Source, StateGraph.

This module defines the canonical state-graph schema that every translator,
recovery branch, cognition layer, visualizer, and SPI bridge in cua-maximalist
imports. Do NOT redefine these types in downstream modules. If a field is
missing, add a plan that updates THIS file.

Pydantic v2: ``model_dump_json``, ``model_validate_json``, ``ConfigDict``.
"""
from __future__ import annotations

import time
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Bbox(BaseModel):
    """Axis-aligned bounding box in screen pixels (top-left origin)."""

    model_config = ConfigDict(frozen=False)

    x: float
    y: float
    w: float
    h: float

    @property
    def centroid(self) -> tuple[int, int]:
        """Centroid quantised to a 4px grid.

        4px is a deliberate choice: AX frames and CGWindow frames frequently
        differ by 1-3 pixels because of subpixel positioning, layout passes,
        or backing-store rounding. The 4px cell absorbs that jitter so the
        bbox-centroid composite-key fallback stays stable. A 5+ px shift
        intentionally pushes us into the next cell — that IS a different
        element, even if everything else looks identical.
        """
        cx = round((self.x + self.w / 2) / 4) * 4
        cy = round((self.y + self.h / 2) / 4) * 4
        return cx, cy


class Capability(str, Enum):
    """AX-derived element capabilities — what actions the element supports."""

    PRESS = "press"
    INCREMENT = "increment"
    DECREMENT = "decrement"
    SHOWMENU = "show_menu"
    PICK = "pick"
    SET_VALUE = "set_value"
    FOCUS = "focus"


class Source(str, Enum):
    """Translator that provided this UIElement observation.

    A single UIElement may have multiple sources (e.g. AX gave us role+bbox,
    OCR gave us label, pixel gave us a hash) — that's why ``UIElement.source``
    is a list[Source], not a single Source.
    """

    AX = "ax"
    CDP = "cdp"
    APPLESCRIPT = "as"
    OCR = "ocr"
    PIXEL = "pixel"


class EdgeKind(str, Enum):
    """Edge types in the state graph + temporal ring."""

    CONTAINS = "contains"  # parent → child in AX hierarchy
    ENABLES = "enables"  # focus dependency (focusing X enables Y)
    TRIGGERS = "triggers"  # ActionCanonical.id → UIElement.composite_key delta
    PRECEDES = "precedes"  # frame[t-1].key → frame[t].key (TemporalRingBuffer)


class Edge(BaseModel):
    """Directed edge between two state-graph nodes (or action→node)."""

    model_config = ConfigDict(frozen=True)

    src: str
    dst: str
    kind: EdgeKind
    timestamp_ns: int


class UIElement(BaseModel):
    """A single element observation in the state graph.

    The schema mirrors ARCHITECTURE.md L40-49 verbatim. The ``composite_key``
    property delegates to ``cua_overlay.state.fingerprint.compute_composite_key``
    so the tier ladder lives in one place.
    """

    model_config = ConfigDict(frozen=False)

    role: str
    role_path: str
    label: str
    ax_identifier: Optional[str] = None
    bbox: Bbox
    value: Optional[str] = None
    enabled: bool = True
    focused: bool = False
    capabilities: list[Capability] = Field(default_factory=list)
    confidence: float = 1.0
    source: list[Source] = Field(default_factory=list)
    visual_embedding: Optional[bytes] = None
    ocr_text: Optional[str] = None
    pixel_hash: Optional[str] = None
    caused_by: Optional[str] = None
    causes: list[str] = Field(default_factory=list)
    episodic_ref: Optional[str] = None
    history_ids: list[str] = Field(default_factory=list)
    discovered_at: datetime
    last_seen_at: datetime
    pid: int
    bundle_id: str
    window_id: int

    @property
    def composite_key(self) -> str:
        """Stable identity for the element across re-renders.

        Late import dodges the circular dependency between graph.py (which
        UIElement lives in) and fingerprint.py (which type-hints UIElement).
        """
        from cua_overlay.state.fingerprint import compute_composite_key

        return compute_composite_key(self)


class StateGraph:
    """In-memory state-graph store: composite_key -> UIElement plus an edge list.

    Snapshot persistence lives in ``cua_overlay.state.snapshot`` (atomic write
    via tmp + os.replace). The ring-buffer-of-snapshots lives in
    ``cua_overlay.state.ring_buffer``.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, UIElement] = {}
        self.edges: list[Edge] = []

    def upsert(self, elem: UIElement) -> None:
        """Insert or replace ``elem`` keyed by its composite_key."""
        self.nodes[elem.composite_key] = elem

    def get(self, composite_key: str) -> Optional[UIElement]:
        """Return the element for ``composite_key`` or None."""
        return self.nodes.get(composite_key)

    def add_child(self, parent: UIElement, child: UIElement) -> None:
        """Register a parent→child relationship as a CONTAINS edge.

        Both nodes are upserted so callers can build the graph in any order.
        """
        self.upsert(parent)
        self.upsert(child)
        self.edges.append(
            Edge(
                src=parent.composite_key,
                dst=child.composite_key,
                kind=EdgeKind.CONTAINS,
                timestamp_ns=time.monotonic_ns(),
            )
        )
