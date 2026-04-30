"""STATE-01 fingerprint tier ladder tests.

Tier 1: AXIdentifier (most stable; explicitly set by the app developer)
Tier 2: role_path + label
Tier 3: role + bbox_centroid (4px grid; absorbs sub-pixel jitter from AX/CGWindow)
"""
from __future__ import annotations

from datetime import datetime, timezone

from cua_overlay.state.graph import Bbox, Capability, Source, UIElement


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make(
    *,
    ax_identifier: str | None = None,
    label: str = "5",
    role: str = "AXButton",
    role_path: str = "AXButton[3]",
    bbox: Bbox | None = None,
    bundle_id: str = "com.apple.Calculator",
) -> UIElement:
    return UIElement(
        role=role,
        role_path=role_path,
        label=label,
        ax_identifier=ax_identifier,
        bbox=bbox or Bbox(x=100.0, y=100.0, w=40.0, h=40.0),
        capabilities=[Capability.PRESS],
        source=[Source.AX],
        discovered_at=_now(),
        last_seen_at=_now(),
        pid=12345,
        bundle_id=bundle_id,
        window_id=1,
    )


def test_axidentifier_wins() -> None:
    """When ax_identifier is set, composite_key uses it regardless of label/role_path."""
    elem = _make(ax_identifier="btn-5", label="something else", role_path="AXOther[99]")
    assert elem.composite_key == "axid:com.apple.Calculator:btn-5"


def test_role_path_label_fallback() -> None:
    """Without ax_identifier, key uses role_path:label."""
    elem = _make(ax_identifier=None, role_path="AXButton[3]", label="5")
    assert elem.composite_key == "path:com.apple.Calculator:AXButton[3]:5"


def test_bbox_centroid_fallback() -> None:
    """Without ax_identifier and without label, key uses role:cx:cy on the 4px grid."""
    elem = _make(ax_identifier=None, label="", bbox=Bbox(x=100.0, y=100.0, w=40.0, h=40.0))
    # cx = round((100+20)/4)*4 = 120; cy = round((100+20)/4)*4 = 120
    assert elem.composite_key == "bbox:com.apple.Calculator:AXButton:120:120"


def test_stable_composite_key_under_4px_jitter() -> None:
    """Two elements with identical role/label/bundle but bbox.x differing by 1-3 px on
    the bbox-centroid path collide on composite_key (the 4px grid absorbs jitter).
    A 5px shift moves them apart."""
    a = _make(ax_identifier=None, label="", bbox=Bbox(x=100.0, y=100.0, w=40.0, h=40.0))
    b = _make(ax_identifier=None, label="", bbox=Bbox(x=102.0, y=100.0, w=40.0, h=40.0))
    assert a.composite_key == b.composite_key, (
        f"4px jitter must collide: {a.composite_key} vs {b.composite_key}"
    )

    # 5px shift of the *left* edge moves the centroid from 120 to 124 — different cell.
    c = _make(ax_identifier=None, label="", bbox=Bbox(x=108.0, y=100.0, w=40.0, h=40.0))
    assert a.composite_key != c.composite_key, (
        f"5+ px shift must NOT collide: {a.composite_key} vs {c.composite_key}"
    )
