"""C3 CGEvent.postToPid channel (D-14 T5 default binding).

Per CONTEXT.md D-14: T5 → C3.
Per CONTEXT.md D-18: pre-syscall kill-switch.

In Phase 2, C3 and C1 are functionally identical (both wrap public
CGEventPostToPid). The semantic distinction:
    - C1 = "background no-cursor-warp tier" (Phase 6 SkyLight upgrade)
    - C3 = "foreground with cursor tier" — stays public CGEventPostToPid forever

Both rely on CGEventPostToPid which does NOT warp the cursor (T-2-05
mitigation — never use CGEvent.post or CGEventPost(kCGSessionEventTap)).

Pitfall G: community reports mouse events to PID don't always deliver to
backgrounded apps. C3 is documented as a fallback channel; primary action
paths use C2 (AX) or C5 (CDP). Test on Chess.app at integration time
(Plan 02-12).
"""
from __future__ import annotations

import asyncio
import time
from typing import Literal

import anyio
import structlog

from cua_overlay.actions.channels.base import ChannelOutcome
from cua_overlay.actions.channels.c1_skylight import _post_left_click
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TranslatorTarget


_log = structlog.get_logger()


class C3CGEventChannel:
    """C3 — public CGEventPostToPid (foreground, with cursor)."""

    name: Literal["C1", "C2", "C3", "C4", "C5"] = "C3"

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        # 1. Atomic claim.
        claim = await store.try_claim(action.id, "C3")
        if claim is None:
            return ChannelOutcome(
                channel="C3", status="skipped", skipped_reason="idempotency_lost"
            )
        # 2. Pre-syscall kill-switch.
        if cancel_event.is_set():
            return ChannelOutcome(channel="C3", status="cancelled")
        if target.grounded_bbox is None:
            return ChannelOutcome(
                channel="C3", status="errored", error="missing grounded_bbox"
            )
        bbox = target.grounded_bbox
        cx = bbox.x + bbox.w / 2
        cy = bbox.y + bbox.h / 2
        pid = target.element.pid

        try:
            await asyncio.to_thread(_post_left_click, pid, cx, cy)
        except Exception as exc:  # noqa: BLE001
            _log.warning("c3.fire_error", action_id=action.id, error=str(exc))
            return ChannelOutcome(channel="C3", status="errored", error=str(exc))
        return ChannelOutcome(
            channel="C3", status="fired", fired_at_ns=time.monotonic_ns()
        )
