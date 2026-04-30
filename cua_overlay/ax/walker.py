# STUB: replaced by Plan 01-03 on merge
"""Depth-limited AX subtree walker — Wave-2 stub.

This is a Wave-2 import-compatibility stub. Plan 01-03 owns the real
implementation (see plan 01-03 Task 2). The orchestrator will overwrite this
file with Plan 01-03's full implementation via ``-X theirs`` strategy on merge.

Plan 01-04 does not actually call walk_subtree at runtime; the stub exists so
``from cua_overlay.ax.walker import walk_subtree`` succeeds during testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class WalkResult:
    """Stub WalkResult — real impl in Plan 01-03."""

    nodes: list[Any]
    truncated: bool
    cap_hit: Optional[str]
    duration_ms: float


async def walk_subtree(
    element: Any,
    pid: int,
    bundle_id: str,
    *,
    max_depth: int = 3,
    max_children: int = 50,
    max_nodes: int = 500,
    bucket: Any = None,
    window_id: int = 0,
    parent_role_path: str = "AXApplication",
) -> WalkResult:
    """Stub walk_subtree. Real impl in Plan 01-03."""
    raise NotImplementedError("Plan 01-03 owns walk_subtree implementation")
