"""STATE-01 unit tests — UIElement Pydantic round-trip + StateGraph store + snapshot.

These tests lock the system-wide state-graph contract that every downstream
phase imports verbatim. If any of them break, every translator/recovery/
cognition module breaks with them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from basicctrl.state.graph import (
    Bbox,
    Capability,
    Edge,
    EdgeKind,
    Source,
    StateGraph,
    UIElement,
)
from basicctrl.state.snapshot import dump_snapshot, load_snapshot


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _build_button(
    label: str = "5",
    role_path: str = "AXButton[3]",
    bundle_id: str = "com.apple.Calculator",
    *,
    ax_identifier: str | None = None,
    bbox: Bbox | None = None,
) -> UIElement:
    return UIElement(
        role="AXButton",
        role_path=role_path,
        label=label,
        ax_identifier=ax_identifier,
        bbox=bbox or Bbox(x=100.0, y=100.0, w=40.0, h=40.0),
        value="0",
        capabilities=[Capability.PRESS],
        source=[Source.AX],
        discovered_at=_now(),
        last_seen_at=_now(),
        pid=12345,
        bundle_id=bundle_id,
        window_id=1,
    )


def test_pydantic_roundtrip() -> None:
    """UIElement -> JSON -> UIElement preserves every field including bbox.centroid."""
    elem = _build_button()
    raw = elem.model_dump_json()
    parsed = UIElement.model_validate_json(raw)

    assert parsed.role == elem.role
    assert parsed.role_path == elem.role_path
    assert parsed.label == elem.label
    assert parsed.bbox.x == elem.bbox.x
    assert parsed.bbox.centroid == elem.bbox.centroid
    assert parsed.capabilities == elem.capabilities
    assert parsed.source == elem.source
    assert parsed.pid == elem.pid
    assert parsed.bundle_id == elem.bundle_id
    assert parsed.composite_key == elem.composite_key


def test_uielement_required_fields() -> None:
    """role/role_path/label/bbox/discovered_at/last_seen_at/pid/bundle_id/window_id required."""
    required = {
        "role",
        "role_path",
        "label",
        "bbox",
        "discovered_at",
        "last_seen_at",
        "pid",
        "bundle_id",
        "window_id",
    }
    base_kwargs = dict(
        role="AXButton",
        role_path="AXButton[3]",
        label="5",
        bbox=Bbox(x=0.0, y=0.0, w=10.0, h=10.0),
        discovered_at=_now(),
        last_seen_at=_now(),
        pid=1,
        bundle_id="com.apple.Calculator",
        window_id=1,
    )
    for missing in required:
        kwargs = {k: v for k, v in base_kwargs.items() if k != missing}
        with pytest.raises(ValidationError):
            UIElement(**kwargs)  # type: ignore[arg-type]


def test_default_factories_no_shared_state() -> None:
    """Two UIElement instances must have INDEPENDENT default lists (no shared mutable default)."""
    a = _build_button()
    b = _build_button()
    a.capabilities.append(Capability.FOCUS)
    a.source.append(Source.OCR)
    a.history_ids.append("step-001")
    a.causes.append("ax://child")

    assert Capability.FOCUS not in b.capabilities
    assert Source.OCR not in b.source
    assert b.history_ids == []
    assert b.causes == []


def test_state_graph_upsert_and_get() -> None:
    """upsert(elem) keys by composite_key; get(key) returns the same instance."""
    g = StateGraph()
    elem = _build_button()
    g.upsert(elem)
    assert g.get(elem.composite_key) is elem


def test_state_graph_emits_contains_edge_on_parent_child() -> None:
    """add_child(parent, child) writes Edge(kind=CONTAINS, src=parent.key, dst=child.key)."""
    g = StateGraph()
    parent = _build_button(label="window", role_path="AXWindow[0]")
    parent_obj = parent.model_copy(update={"role": "AXWindow"})
    child = _build_button(label="5", role_path="AXButton[3]")

    g.add_child(parent_obj, child)

    assert any(
        e.kind is EdgeKind.CONTAINS
        and e.src == parent_obj.composite_key
        and e.dst == child.composite_key
        for e in g.edges
    ), f"no CONTAINS edge in {g.edges}"


def test_snapshot_roundtrip(session_dir: Path) -> None:
    """dump_snapshot then load_snapshot returns an equivalent graph."""
    g = StateGraph()
    a = _build_button(label="A")
    b = _build_button(label="B", role_path="AXButton[4]")
    g.upsert(a)
    g.upsert(b)
    g.add_child(a, b)

    path = session_dir / "snapshot.json"
    dump_snapshot(g, path)
    assert path.exists()

    loaded = load_snapshot(path)
    assert set(loaded.nodes.keys()) == {a.composite_key, b.composite_key}
    assert len(loaded.edges) == 1
    assert loaded.edges[0].kind is EdgeKind.CONTAINS
    assert loaded.nodes[a.composite_key].label == "A"
    assert loaded.nodes[b.composite_key].label == "B"
