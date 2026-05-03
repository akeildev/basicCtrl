"""STATE-03 — TemporalRingBuffer (last 5 frames + PRECEDES edges)."""
from __future__ import annotations

from datetime import datetime, timezone

from basicctrl.state.graph import (
    Bbox,
    Capability,
    EdgeKind,
    Source,
    StateGraph,
    UIElement,
)
from basicctrl.state.ring_buffer import StateSnapshot, TemporalRingBuffer


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _button(label: str, role_path: str = "AXButton[3]") -> UIElement:
    return UIElement(
        role="AXButton",
        role_path=role_path,
        label=label,
        bbox=Bbox(x=0.0, y=0.0, w=10.0, h=10.0),
        capabilities=[Capability.PRESS],
        source=[Source.AX],
        discovered_at=_now(),
        last_seen_at=_now(),
        pid=1,
        bundle_id="com.apple.Calculator",
        window_id=1,
    )


def _graph_with(*elems: UIElement) -> StateGraph:
    g = StateGraph()
    for e in elems:
        g.upsert(e)
    return g


def test_maxlen_5() -> None:
    """Pushing 6 frames keeps exactly 5 (oldest evicted)."""
    rb = TemporalRingBuffer()
    for i in range(6):
        rb.push(StateSnapshot.from_graph(_graph_with(_button(label=f"v{i}"))))
    assert len(rb.frames) == 5


def test_emits_precedes_edge_on_push() -> None:
    """When two consecutive frames share a composite_key, PRECEDES edge is emitted."""
    rb = TemporalRingBuffer()
    elem = _button("5")
    rb.push(StateSnapshot.from_graph(_graph_with(elem)))
    rb.push(StateSnapshot.from_graph(_graph_with(elem)))

    assert any(
        e.kind is EdgeKind.PRECEDES and e.src == elem.composite_key
        for e in rb.precedes_edges
    ), f"no PRECEDES edge in {rb.precedes_edges}"


def test_no_precedes_for_new_element() -> None:
    """A composite_key that didn't exist in the previous frame gets no PRECEDES edge."""
    rb = TemporalRingBuffer()
    a = _button("A", role_path="AXButton[1]")
    b = _button("B", role_path="AXButton[2]")

    rb.push(StateSnapshot.from_graph(_graph_with(a)))
    rb.push(StateSnapshot.from_graph(_graph_with(b)))  # b is brand new

    # No PRECEDES edge for b (it has no predecessor in the previous frame).
    assert not any(e.dst == b.composite_key for e in rb.precedes_edges)
