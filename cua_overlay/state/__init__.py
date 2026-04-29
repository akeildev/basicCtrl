"""Public state-graph subsystem.

Re-exports Pydantic v2 contracts that ALL downstream phases (translators,
recovery, cognition, visualizer, SPI bridges) read and write verbatim. Do not
redefine these types elsewhere — extend in place via a new plan that updates
this module.
"""
from __future__ import annotations

from cua_overlay.state.graph import (
    Bbox,
    Capability,
    Edge,
    EdgeKind,
    Source,
    StateGraph,
    UIElement,
)

__all__ = [
    "Bbox",
    "Capability",
    "Edge",
    "EdgeKind",
    "Source",
    "StateGraph",
    "UIElement",
]
