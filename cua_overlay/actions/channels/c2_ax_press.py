"""C2 AX kAXPress channel — fires AXUIElementPerformAction(target, "AXPress").

Per CONTEXT.md D-14 default binding: T1 → C2.
Per CONTEXT.md D-17: try_claim BEFORE syscall.
Per CONTEXT.md D-18: cancel_event.is_set() check immediately before syscall.

The AXUIElementPerformAction syscall blocks the calling thread because it
sends an AppleEvent to the target app's main thread and waits for the reply.
We wrap it in ``asyncio.to_thread`` so the asyncio loop stays responsive
while the target app processes the event — and so the orchestrator's
cancel_scope can interrupt cleanly between coroutine yields.

Threats mitigated:
    * T-2-01 (race ordering) — try_claim BEFORE syscall; second fire on the
      same action_id returns ChannelOutcome(status='skipped',
      skipped_reason='idempotency_lost').
    * T-2-08 (race-cancel correctness) — cancel_event.is_set() check before
      the syscall. The syscall itself is blocking inside to_thread, but the
      orchestrator can shield=False around the await to_thread call so the
      thread's result is dropped on cancel without leaving an AppleEvent
      mid-flight (the kernel completes the IPC; only the Python coroutine
      cancels).
"""
from __future__ import annotations

import asyncio
import time
from typing import Literal

import anyio
import structlog

from cua_overlay.actions.channels.base import ChannelOutcome
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TranslatorTarget


_log = structlog.get_logger()


class C2AXPressChannel:
    """C2 — AX kAXPress (PyObjC HIServices).

    Default channel for T1 (D-14). Fires ``AXUIElementPerformAction(target,
    "AXPress")`` after atomic claim + cancel-event guard.
    """

    name: Literal["C1", "C2", "C3", "C4", "C5"] = "C2"

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        """Fire AXPress on ``target.ax_element``.

        Order of operations matters and is verified by tests:
            1. ``store.try_claim(action.id, "C2")`` — atomic write to the
               in-memory dict + NDJSON trace. Lose → return skipped.
            2. ``cancel_event.is_set()`` — lock-free peek. Set → return
               cancelled. The claim is held but the syscall is skipped, so
               the action_id stays burned (consistent with race-cancel
               correctness — the orchestrator already chose the winner).
            3. Validate ``target.ax_element`` is non-None.
            4. ``asyncio.to_thread(_press)`` — sync AX syscall on a worker
               thread; the asyncio loop stays responsive.
        """
        # 1. Atomic claim (D-17). If lost, skip.
        claim = await store.try_claim(action.id, "C2")
        if claim is None:
            return ChannelOutcome(
                channel="C2",
                status="skipped",
                skipped_reason="idempotency_lost",
            )

        # 2. Pre-syscall kill-switch (D-18). ~50µs window remains but shrinks.
        if cancel_event.is_set():
            return ChannelOutcome(channel="C2", status="cancelled")

        # 3. Validate ax_element is present (defensive — T1 ensures this when
        # it returns a target, but other translators may leave ax_element=None
        # if the orchestrator routes T4 grounding to C2 by mistake).
        if target.ax_element is None:
            return ChannelOutcome(
                channel="C2", status="errored", error="no_ax_element"
            )

        # 4. Fire AXUIElementPerformAction in a thread (sync syscall).
        def _press() -> int:
            try:
                from HIServices import (  # type: ignore[import-not-found]
                    AXUIElementPerformAction,
                )
            except ImportError:
                from ApplicationServices import (  # type: ignore[import-not-found]
                    AXUIElementPerformAction,
                )
            return int(AXUIElementPerformAction(target.ax_element, "AXPress"))

        try:
            err = await asyncio.to_thread(_press)
        except Exception as exc:  # noqa: BLE001 — never raise across channel boundary
            _log.warning("c2.fire_error", action_id=action.id, error=str(exc))
            return ChannelOutcome(channel="C2", status="errored", error=str(exc))

        if err != 0:
            return ChannelOutcome(
                channel="C2", status="errored", error=f"AXErr={err}"
            )

        return ChannelOutcome(
            channel="C2", status="fired", fired_at_ns=time.monotonic_ns()
        )
