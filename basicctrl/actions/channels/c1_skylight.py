"""C1 SkyLight channel — public CGEventPostToPid in Phase 2.

Per CONTEXT.md D-07: Phase 2 uses public Quartz.CGEventPostToPid; Phase 6
swaps in true SkyLight SLEventPostToPid Swift bridge for SPI-01. The
channel signature stays stable across the swap — Phase 6 only changes
the syscall implementation.

Per CONTEXT.md D-14 default binding: T4 → C1 (background, no cursor warp).
Per CONTEXT.md D-18: pre-syscall cancel_event.is_set() kill-switch.

T-2-05 mitigation: NEVER use CGEvent.post or CGEventPost(kCGSessionEventTap)
— those warp the user's cursor globally. CGEventPostToPid is the only safe
post-mode in Phase 2.
"""
from __future__ import annotations

import asyncio
import time
from typing import Literal

import anyio
import structlog

from basicctrl.actions.channels.base import ChannelOutcome
from basicctrl.actions.idempotency import IdempotencyTokenStore
from basicctrl.state.causal_dag import ActionCanonical
from basicctrl.translators.base import TranslatorTarget


_log = structlog.get_logger()


class C1SkyLightChannel:
    """C1 — public CGEventPostToPid (background, no cursor warp).
    Phase 6 SPI-01 swaps in SLEventPostToPid; signature stays stable."""

    name: Literal["C1", "C2", "C3", "C4", "C5"] = "C1"

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        # 1. Atomic claim.
        claim = await store.try_claim(action.id, "C1")
        if claim is None:
            return ChannelOutcome(
                channel="C1", status="skipped", skipped_reason="idempotency_lost"
            )
        # 2. Pre-syscall kill-switch (~50µs uncancellable window remains; D-18).
        if cancel_event.is_set():
            return ChannelOutcome(channel="C1", status="cancelled")
        if target.grounded_bbox is None:
            return ChannelOutcome(
                channel="C1", status="errored", error="missing grounded_bbox"
            )

        bbox = target.grounded_bbox
        cx = bbox.x + bbox.w / 2
        cy = bbox.y + bbox.h / 2
        pid = target.element.pid

        try:
            await asyncio.to_thread(_post_left_click, pid, cx, cy)
        except Exception as exc:  # noqa: BLE001
            _log.warning("c1.fire_error", action_id=action.id, error=str(exc))
            return ChannelOutcome(channel="C1", status="errored", error=str(exc))
        return ChannelOutcome(
            channel="C1", status="fired", fired_at_ns=time.monotonic_ns()
        )


def _post_left_click(pid: int, cx: float, cy: float) -> None:
    """Post mouseDown + mouseUp via CGEventPostToPid. Sync — call in thread."""
    from Quartz import (  # type: ignore[import-not-found]
        CGEventCreateMouseEvent,
        CGEventPostToPid,
        kCGEventLeftMouseDown,
        kCGEventLeftMouseUp,
        kCGMouseButtonLeft,
    )

    down = CGEventCreateMouseEvent(
        None, kCGEventLeftMouseDown, (cx, cy), kCGMouseButtonLeft
    )
    up = CGEventCreateMouseEvent(
        None, kCGEventLeftMouseUp, (cx, cy), kCGMouseButtonLeft
    )
    CGEventPostToPid(pid, down)
    CGEventPostToPid(pid, up)
