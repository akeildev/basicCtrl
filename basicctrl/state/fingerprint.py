"""Composite-key derivation: the tier ladder for UIElement identity.

Tier 1 (most stable): AXIdentifier — explicitly set by the app developer.
Tier 2: role_path + label — stable across re-renders if the visible text
    holds. Used for the typical labelled control case.
Tier 3 (fallback): role + bbox_centroid (4px grid) — for unlabelled or
    framework-anonymous elements like Canvas children, native popovers, etc.

Keeping the tier ladder in a single function (not three classes, not a
visitor pattern) keeps it easy for downstream phases to predict identity:
"if I observe an ax_identifier, I always get axid:..."

Reference: ARCHITECTURE.md L466-470, AX-tree paper 2603.20358.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cua_overlay.state.graph import UIElement


def compute_composite_key(elem: "UIElement") -> str:
    """Resolve a UIElement to a stable string identifier.

    Args:
        elem: a fully-populated UIElement.

    Returns:
        ``axid:<bundle_id>:<ax_identifier>`` if Tier 1 hits, else
        ``path:<bundle_id>:<role_path>:<label>`` if Tier 2 hits, else
        ``bbox:<bundle_id>:<role>:<cx>:<cy>`` (Tier 3 fallback).
    """
    if elem.ax_identifier:
        return f"axid:{elem.bundle_id}:{elem.ax_identifier}"
    if elem.role_path and elem.label:
        return f"path:{elem.bundle_id}:{elem.role_path}:{elem.label}"
    cx, cy = elem.bbox.centroid
    return f"bbox:{elem.bundle_id}:{elem.role}:{cx}:{cy}"
