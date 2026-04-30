"""Atomic JSON snapshot persistence for ``StateGraph``.

PERSIST-02 requires that the on-disk session directory always reflects a
consistent state — never a torn write from a crashed process. We achieve that
with the standard tmp-file + ``os.replace`` dance: ``os.replace`` is atomic on
the same filesystem, so readers either see the previous good snapshot or the
new good snapshot, never a half-written one.

Schema is intentionally simple JSON (Pydantic ``model_dump(mode='json')`` so
``datetime`` becomes ISO-8601 strings) — easy to diff and inspect by hand.

Includes a ``version`` field so future schema migrations can be detected and
gracefully refused / upgraded.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from cua_overlay.state.graph import Edge, StateGraph, UIElement

_SNAPSHOT_VERSION = 1


def dump_snapshot(graph: StateGraph, path: Path) -> None:
    """Write ``graph`` to ``path`` atomically (tmp + os.replace)."""
    data = {
        "version": _SNAPSHOT_VERSION,
        "nodes": {k: v.model_dump(mode="json") for k, v in graph.nodes.items()},
        "edges": [e.model_dump(mode="json") for e in graph.edges],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def load_snapshot(path: Path) -> StateGraph:
    """Read a snapshot file and return a hydrated ``StateGraph``."""
    raw = json.loads(path.read_text())
    if raw.get("version") != _SNAPSHOT_VERSION:
        raise ValueError(
            f"snapshot version mismatch at {path}: "
            f"expected {_SNAPSHOT_VERSION}, got {raw.get('version')!r}"
        )
    g = StateGraph()
    for key, node_raw in raw["nodes"].items():
        g.nodes[key] = UIElement.model_validate(node_raw)
    for edge_raw in raw["edges"]:
        g.edges.append(Edge.model_validate(edge_raw))
    return g
