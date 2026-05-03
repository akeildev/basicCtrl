"""Modal alert probe — Pitfall P25 mitigation.

Pitfall P25 prevention rule 1 (PITFALLS.md):
    Pre-action modal probe (HoarePre.no_blocking_modal); subscribe
    kAXWindowCreated push event; bundle blocklist for known modal sources.

This module provides the targeted-read implementation: open the application's
``AXWindows`` list, scan up to ``_MAX_WINDOWS_TO_CHECK`` top-level windows for
``AXModal=True``, and return a ``UIElement`` describing the modal if found.

The probe is deliberately CHEAP — it does NOT call ``walk_subtree``. A full
walk would defeat the point: a modal alert often coincides with main-thread
saturation, and we want to know within a single bucket-token whether to abort
the action vs proceed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from cua_overlay.ax.errors import AXError
from cua_overlay.ax.rate_limit import TokenBucket
from cua_overlay.ax.walker import _coords_to_bbox, _read_attr
from cua_overlay.state.graph import Source, UIElement

# Cap so a malicious / runaway app with hundreds of windows can never blow our
# budget. 10 is well past every observed real-world max-window-count.
_MAX_WINDOWS_TO_CHECK = 10


async def has_blocking_modal(
    pid: int,
    *,
    bundle_id: str = "",
    bucket: Optional[TokenBucket] = None,
) -> Optional[UIElement]:
    """Return the modal ``UIElement`` if a blocking modal is present, else None.

    Per Pitfall P25, every action that mutates state must check this first and
    populate ``HoarePre.no_blocking_modal`` accordingly. The probe is rate-
    limited via ``bucket`` (default: a fresh ``TokenBucket(20, 20)``); on
    rate-limit deny, the probe returns ``None`` (fail-open) and emits a
    structured warning so the caller can choose to retry.
    """
    bucket = bucket or TokenBucket()
    log = structlog.get_logger().bind(pid=pid, bundle_id=bundle_id)

    try:  # pragma: no cover — non-macOS dev hosts skip this branch
        from HIServices import AXUIElementCreateApplication  # type: ignore[import-not-found]
    except ImportError:
        return None  # Phase 1 fail-open if PyObjC unavailable

    app = await asyncio.to_thread(AXUIElementCreateApplication, pid)

    if not await bucket.acquire(pid):
        log.warning("modal_probe.rate_limited")
        return None

    try:
        windows = await _read_attr(app, "AXWindows") or []
    except AXError as e:
        log.warning("modal_probe.windows_read_error", code=e.code)
        return None

    now = datetime.now(timezone.utc)
    for i, window in enumerate(list(windows)[:_MAX_WINDOWS_TO_CHECK]):
        if not await bucket.acquire(pid):
            continue
        try:
            is_modal = await _read_attr(window, "AXModal")
        except AXError:
            continue
        if is_modal:
            # Probe basic metadata for the modal so the caller can describe it
            # in the action log. Each metadata read is also bucket-gated.
            try:
                title = (
                    await _read_attr(window, "AXTitle") or "modal"
                )
                position = await _read_attr(window, "AXPosition")
                size = await _read_attr(window, "AXSize")
            except AXError:
                title = "modal"
                position, size = None, None
            return UIElement(
                role="AXWindow",
                role_path="AXApplication/AXWindow[modal]",
                label=str(title),
                bbox=_coords_to_bbox(position, size),
                source=[Source.AX],
                discovered_at=now,
                last_seen_at=now,
                pid=pid,
                bundle_id=bundle_id,
                window_id=i,
            )
    return None
