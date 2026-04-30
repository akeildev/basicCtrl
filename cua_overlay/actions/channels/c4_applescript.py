"""C4 AppleScript channel — runs AS on T3 translator's dedicated executor.

Per CONTEXT.md D-14: T3 → C4 default tier-channel binding.
Per CONTEXT.md D-04: in-process NSAppleScript via py-applescript only —
NEVER the fork+exec CLI tool path (50-200ms cost; blocks racing budget).
Per CONTEXT.md D-15: AppleScript stagger 500ms is enforced at the race
orchestrator (Plan 02-10), NOT inside this channel — fire() returns
immediately when called.

T-2-03 thread-isolation property: this channel does NOT spin up its own
ThreadPoolExecutor — it delegates to ``translator.execute`` which runs on
T3's dedicated cua-as pool. That keeps the "AS calls never run on the main
asyncio loop thread" property uniformly enforced across the project.

T-2-08 race-cancel correctness: the AppleEvent itself is uncancellable
mid-flight. We do a pre-call ``cancel_event.is_set()`` check (~50µs window
remains, but the surface shrinks); D-15 stagger pushes execution past most
race windows so a faster channel (C2/C5) typically wins first.

Threats mitigated:
    * T-2-01 (race ordering) — try_claim BEFORE submitting to executor.
      Second fire on same action_id returns ChannelOutcome(status='skipped').
    * T-2-08 (race-cancel correctness) — cancel_event pre-call check.
    * T-2-03 (AS thread isolation) — reuses T3's dedicated executor; never
      spins its own pool.
"""
from __future__ import annotations

import time
from typing import Literal, Optional, Protocol

import anyio
import structlog

from cua_overlay.actions.channels.base import ChannelOutcome
from cua_overlay.actions.idempotency import IdempotencyTokenStore
from cua_overlay.state.causal_dag import ActionCanonical
from cua_overlay.translators.base import TranslatorTarget
from cua_overlay.translators.t3_applescript import T3AppleScriptTranslator


_log = structlog.get_logger()


class _T3Like(Protocol):
    """Minimal protocol for the translator C4 calls (T3AppleScriptTranslator
    in production; a fake test-double in unit tests)."""

    async def execute(
        self, source: str, args: tuple = ()
    ) -> tuple[str, Optional[str]]: ...


class C4AppleScriptChannel:
    """C4 — AppleScript fire via T3's dedicated executor.

    Default channel for T3 (D-14). Reads ``target.as_target_spec`` (a wrapped
    ``tell application "..." to ...`` block built by T3.resolve()) and runs
    it through ``T3AppleScriptTranslator.execute``, which submits to the
    dedicated cua-as ThreadPoolExecutor.
    """

    name: Literal["C1", "C2", "C3", "C4", "C5"] = "C4"

    def __init__(self, translator: Optional[_T3Like] = None) -> None:
        """Args:
            translator: a T3-like object whose ``execute`` runs AS on the
                dedicated cua-as pool. If None, instantiates a local
                T3AppleScriptTranslator. In production the race orchestrator
                (Plan 02-10) passes the shared T3 instance from the registry
                so the executor is shared with target resolution.
        """
        self._t3: _T3Like = (
            translator if translator is not None else T3AppleScriptTranslator()
        )

    async def fire(
        self,
        action: ActionCanonical,
        target: TranslatorTarget,
        store: IdempotencyTokenStore,
        cancel_event: anyio.Event,
    ) -> ChannelOutcome:
        """Fire AppleScript via the T3 translator's dedicated executor.

        Order of operations (verified by tests):
            1. ``store.try_claim(action.id, "C4")`` — atomic claim.
               Lose → ``ChannelOutcome(status='skipped',
               skipped_reason='idempotency_lost')``. The translator is NOT
               called when the claim is lost (verified via fake_translator.calls).
            2. ``cancel_event.is_set()`` — pre-call kill-switch.
               Set → ``ChannelOutcome(status='cancelled')`` with NO AS dispatch.
               The claim is HELD so the orchestrator's race winner stays
               canonical (T-2-08).
            3. Validate ``target.as_target_spec`` is non-empty. Missing →
               ``ChannelOutcome(status='errored', error='missing as_target_spec')``.
            4. ``await self._t3.execute(spec)`` → returns (result, err).
               err is not None → ``ChannelOutcome(status='errored',
               error=err)``.
            5. Return ``ChannelOutcome(status='fired',
               fired_at_ns=time.monotonic_ns())``.

        Any unexpected exception from ``translator.execute`` is caught and
        converted to ``ChannelOutcome(status='errored', error=str(exc))`` —
        the channel contract forbids raising across the boundary (Channel
        Protocol from base.py).
        """
        # 1. Atomic claim (D-17). If lost, skip — translator NOT called.
        claim = await store.try_claim(action.id, "C4")
        if claim is None:
            return ChannelOutcome(
                channel="C4",
                status="skipped",
                skipped_reason="idempotency_lost",
            )

        # 2. Pre-call kill-switch (D-18). The AppleEvent IS uncancellable
        # mid-flight; this check is the only opportunity to skip the dispatch
        # before it commits. D-15 stagger (Plan 02-10) makes this check
        # likely to fire when a faster channel has already won.
        if cancel_event.is_set():
            return ChannelOutcome(channel="C4", status="cancelled")

        # 3. Validate spec — defensive against orchestrator routing bugs.
        if not target.as_target_spec:
            return ChannelOutcome(
                channel="C4",
                status="errored",
                error="missing as_target_spec",
            )

        # 4. Run via T3's dedicated cua-as ThreadPoolExecutor (T-2-03).
        # T3.execute() returns (result, error_or_None) — never raises by
        # contract, but we still wrap defensively because the channel boundary
        # MUST NOT propagate exceptions to the orchestrator.
        try:
            result, err = await self._t3.execute(target.as_target_spec)
        except Exception as exc:  # noqa: BLE001 — translator should not raise
            _log.warning(
                "c4.fire_unexpected_error",
                action_id=action.id,
                error=str(exc),
            )
            return ChannelOutcome(channel="C4", status="errored", error=str(exc))

        if err is not None:
            return ChannelOutcome(channel="C4", status="errored", error=err)

        return ChannelOutcome(
            channel="C4",
            status="fired",
            fired_at_ns=time.monotonic_ns(),
        )
