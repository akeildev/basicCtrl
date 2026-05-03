"""Depth-limited iterative AX subtree walker — Pitfall P3 mitigation.

Hard rule from CLAUDE.md:
    Never run a full recursive AX tree walk (15-20s on Safari).
    Always depth-limited (3 levels max).

This walker is the ONLY sanctioned way to walk an AX hierarchy in basicCtrl.
It enforces three independent caps and emits a ``truncated`` flag whenever any
cap fires so downstream verifiers can reduce their confidence:

* ``max_depth=3`` — children of children of children, no deeper.
* ``max_children=50`` — ignore tail siblings beyond this count.
* ``max_nodes=500`` — total bound across the whole walk.

Implementation is iterative (BFS via ``list.pop(0)``) — never Python-recursive,
so we don't blow the stack and the no-recursion grep test stays green forever.
Every AX read is gated on a ``TokenBucket`` (Pitfall P2 mitigation), so a walker
that races other callers degrades gracefully instead of saturating the target
app's main thread.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from basicctrl.ax.errors import AXError, axerror_from_code, kAXErrorAPIDisabled, kAXErrorCannotComplete
from basicctrl.ax.rate_limit import TokenBucket
from basicctrl.state.graph import Bbox, Source, UIElement


@dataclass
class WalkResult:
    """Outcome of a single subtree walk.

    ``truncated`` is True if ANY cap (depth/children/nodes) fired during the
    walk. ``cap_hit`` records which one fired first (for logging / verifier
    confidence reduction). ``duration_ms`` is wall-clock for the whole walk.
    """

    nodes: list[UIElement]
    truncated: bool
    cap_hit: Optional[str]  # "depth" | "children" | "nodes" | None
    duration_ms: float


async def walk_subtree(
    element: Any,
    pid: int,
    bundle_id: str,
    *,
    max_depth: int = 3,
    max_children: int = 50,
    max_nodes: int = 500,
    bucket: Optional[TokenBucket] = None,
    window_id: int = 0,
    parent_role_path: str = "AXApplication",
) -> WalkResult:
    """Walk the AX subtree rooted at ``element`` with hard caps.

    Iterative BFS. Every read goes through ``bucket`` (Pitfall P2). Every
    cap-hit sets ``truncated=True`` (Pitfall P3 verifier-confidence signal).
    Returns at most ``max_nodes`` ``UIElement`` instances.
    """
    log = structlog.get_logger().bind(pid=pid, bundle_id=bundle_id)
    t_start = time.monotonic()
    bucket = bucket or TokenBucket()
    nodes: list[UIElement] = []
    truncated = False
    cap_hit: Optional[str] = None
    now = datetime.now(timezone.utc)

    # Work queue: (axelem, depth, role_path) — depth=0 is the root.
    queue: list[tuple[Any, int, str]] = [(element, 0, parent_role_path)]

    while queue:
        # Total-nodes cap fires first so we never even start the next read.
        if len(nodes) >= max_nodes:
            truncated = True
            cap_hit = "nodes"
            break

        ax_elem, depth, this_role_path = queue.pop(0)

        # Read this node's attributes — every read gated on the bucket.
        if not await bucket.acquire(pid):
            log.warning("walker.skipped_due_to_rate_limit", role_path=this_role_path)
            continue

        try:
            role = await _read_attr(ax_elem, "AXRole")
            label = (
                await _read_attr(ax_elem, "AXTitle")
                or await _read_attr(ax_elem, "AXLabel")
                or ""
            )
            value = await _read_attr(ax_elem, "AXValue")
            position = await _read_attr(ax_elem, "AXPosition")
            size = await _read_attr(ax_elem, "AXSize")
            ax_id = await _read_attr(ax_elem, "AXIdentifier")
            enabled = await _read_attr(ax_elem, "AXEnabled")
        except AXError as e:
            log.warning("walker.read_error", role_path=this_role_path, code=e.code)
            continue

        bbox = _coords_to_bbox(position, size)
        ui = UIElement(
            role=role or "AXUnknown",
            role_path=this_role_path,
            label=str(label) if label is not None else "",
            ax_identifier=ax_id,
            bbox=bbox,
            value=str(value) if value is not None else None,
            enabled=bool(enabled) if enabled is not None else True,
            source=[Source.AX],
            discovered_at=now,
            last_seen_at=now,
            pid=pid,
            bundle_id=bundle_id,
            window_id=window_id,
        )
        nodes.append(ui)

        # Enqueue children if depth permits. Reading AXChildren also costs a
        # bucket token; if we can't get one, skip enqueuing rather than blocking.
        if depth + 1 <= max_depth:
            if not await bucket.acquire(pid):
                continue
            try:
                children = await _read_attr(ax_elem, "AXChildren") or []
            except AXError as e:
                log.warning("walker.children_read_error", code=e.code)
                continue
            capped_children = list(children[:max_children])
            if len(children) > max_children:
                truncated = True
                if cap_hit is None:
                    cap_hit = "children"
            for i, child in enumerate(capped_children):
                queue.append(
                    (
                        child,
                        depth + 1,
                        f"{this_role_path}/{role or 'AXUnknown'}[{i}]",
                    )
                )
        else:
            # We have at least one node at max_depth; if it has any children we
            # would have descended further, so report depth as the truncating cap.
            # We don't actually probe AXChildren here (saves a token); the
            # presence of nodes at max_depth is sufficient signal.
            truncated = True
            if cap_hit is None:
                cap_hit = "depth"

    duration_ms = (time.monotonic() - t_start) * 1000.0
    log.info(
        "walker.complete",
        node_count=len(nodes),
        truncated=truncated,
        cap_hit=cap_hit,
        duration_ms=duration_ms,
    )
    return WalkResult(
        nodes=nodes,
        truncated=truncated,
        cap_hit=cap_hit,
        duration_ms=duration_ms,
    )


async def _read_attr(ax_elem: Any, attribute: str) -> Any:
    """Read one AX attribute via PyObjC, mapping native errors to typed exceptions.

    Runs the synchronous ``AXUIElementCopyAttributeValue`` call on a thread so
    the asyncio loop never blocks (the C call can sit on the target app's main
    thread for tens of ms in pathological cases).

    Returns ``None`` for "attribute not present" (the AX framework is generous
    about that — many roles simply don't have AXTitle, AXLabel, etc.). Raises
    ``AXError`` only for the codes that signal a real failure: API disabled
    (TCC revoked) or cannot-complete (saturation).
    """
    def _sync() -> Any:
        try:  # pragma: no cover — non-macOS dev hosts skip this branch
            from HIServices import AXUIElementCopyAttributeValue  # type: ignore[import-not-found]
        except ImportError:
            return None
        err, value = AXUIElementCopyAttributeValue(ax_elem, attribute, None)
        if err == 0:
            return value
        if err in (int(kAXErrorCannotComplete), int(kAXErrorAPIDisabled)):
            raise axerror_from_code(err, f"AX read failed: {attribute}")
        # Other errors (attribute unsupported, no value, etc.) → treat as
        # "attribute not present" and let the caller default it.
        return None

    return await asyncio.to_thread(_sync)


def _coords_to_bbox(position: Any, size: Any) -> Bbox:
    """Convert PyObjC AX position/size tuples to our ``Bbox``.

    PyObjC returns ``CGPoint`` / ``CGSize`` as ``(x, y)`` / ``(w, h)`` pairs.
    Returns a zero-rect if either is missing — the caller can detect this via
    ``bbox.w == 0 and bbox.h == 0``.
    """
    if position is None or size is None:
        return Bbox(x=0.0, y=0.0, w=0.0, h=0.0)
    try:
        x, y = float(position[0]), float(position[1])
        w, h = float(size[0]), float(size[1])
    except (TypeError, IndexError, ValueError):
        return Bbox(x=0.0, y=0.0, w=0.0, h=0.0)
    return Bbox(x=x, y=y, w=w, h=h)
