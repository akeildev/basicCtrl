"""B5_APPLESCRIPT_FALLBACK — Re-fire via T3/C4 with 500ms stagger.

Per CONTEXT.md D-08: when all other branches fail, B5 re-fires the action
via AppleScript (T3 translator, C4 channel) with an extra 500ms stagger
delay. The stagger gives faster branches (T1/T2/T4) time to win before the
slowest path fires, reducing double-action risk when multiple branches
race to verify.

Stagger semantics:
  1. Try to claim action_id (T-3-05)
  2. Sleep for stagger_ms (default 500ms)
  3. Check if already claimed (another branch won) — return None if so
  4. Continue to fire if still unclaimed

Per CLAUDE.md hard rule: "AppleScript at >1Hz blocks app event loop; use AS
only as the slow channel in racing with staggered_race and 500ms head-start."

Pattern:
  1. Get T3 AppleScript translator
  2. Emit attempt event
  3. Try claim (fail if already owned)
  4. Sleep stagger_ms
  5. Re-check claim (fail if expired during sleep)
  6. Fire C4 channel with AppleScript
  7. Verify via aggregator
  8. Emit events
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import anyio
import structlog

from cua_overlay.recovery.branches import BranchBase

if TYPE_CHECKING:
    from cua_overlay.actions.channels.base import ChannelOutcome
    from cua_overlay.actions.channel_registry import ChannelRegistry
    from cua_overlay.actions.idempotency import IdempotencyTokenStore
    from cua_overlay.persist.session_writer import SessionWriter
    from cua_overlay.recovery.classifier import FailureCtx
    from cua_overlay.translators.registry import TranslatorRegistry
    from cua_overlay.verifier.aggregator import Aggregator


class B5_AppleScriptFallback(BranchBase):
    """AppleScript fallback: re-fire via T3/C4 with 500ms stagger.

    Last-resort recovery path. Uses AppleScript to re-attempt the action,
    with a 500ms stagger delay to let faster branches (T1/T2/T4) complete
    and verify first, reducing double-action risk.
    """

    name: str = "B5_APPLESCRIPT_FALLBACK"

    def __init__(
        self,
        translator_registry: TranslatorRegistry,
        channel_registry: ChannelRegistry,
        idempotency_store: IdempotencyTokenStore,
        session_writer: SessionWriter,
        aggregator: Aggregator,
        as_stagger_ms: int = 500,
    ):
        """Initialize B5 AppleScript fallback branch.

        Args:
            translator_registry: Registry of available translators (T1-T5)
            channel_registry: Registry of available channels (C1-C5)
            idempotency_store: IdempotencyTokenStore for try_claim (T-3-05)
            session_writer: SessionWriter for event emission
            aggregator: Verifier aggregator for post-action verification
            as_stagger_ms: Stagger delay in milliseconds (default 500)
        """
        super().__init__(
            name="B5_APPLESCRIPT_FALLBACK",
            _idempotency=idempotency_store,
            _session_writer=session_writer,
        )
        self._translator_registry = translator_registry
        self._channel_registry = channel_registry
        self._aggregator = aggregator
        self._as_stagger_ms = as_stagger_ms
        self._log = structlog.get_logger()

    async def attempt(
        self, failure_ctx: FailureCtx
    ) -> Optional[ChannelOutcome]:
        """Attempt AppleScript recovery with stagger.

        Returns ChannelOutcome(status='fired', verified=True) on success,
        None on failure.

        Failure modes:
          - claim_lost_initial: try_claim failed at start
          - stagger_interrupted: sleep cancelled
          - claim_lost_post_stagger: claim expired during sleep
          - t3_unavailable: T3 translator not in registry
          - channel_unavailable: C4 channel not in registry
          - channel_fire_failed: C4.fire raised exception or returned non-fired
          - verify_failed: aggregator returned confidence < 0.50
        """
        bundle_id = failure_ctx["bundle_id"]
        target_key = failure_ctx["target_key"]
        action_type = failure_ctx.get("action_type", "click")
        action_id = failure_ctx.get("action_id", target_key)

        await self._emit_event(
            {
                "event": "branch_attempt",
                "branch": "B5_APPLESCRIPT_FALLBACK",
                "target_key": target_key,
                "bundle_id": bundle_id,
            }
        )

        # Step 1: Try to claim the action (T-3-05 mitigation)
        if not await self._try_claim(action_id, "C4"):
            self._log.debug(
                "b5.claim_lost_initial",
                action_id=action_id,
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "claim_lost_initial",
                    "action_id": action_id,
                }
            )
            return None

        # Step 2: Sleep for stagger interval
        await self._emit_event(
            {
                "event": "b5.stagger_start",
                "branch": "B5_APPLESCRIPT_FALLBACK",
                "stagger_ms": self._as_stagger_ms,
                "action_id": action_id,
            }
        )

        try:
            # Sleep with cancellation support
            await anyio.sleep(self._as_stagger_ms / 1000.0)
        except anyio.get_cancelled_exc_class():
            self._log.debug(
                "b5.stagger_cancelled",
                action_id=action_id,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "stagger_interrupted",
                    "action_id": action_id,
                }
            )
            return None
        except Exception as e:
            self._log.error(
                "b5.stagger_error",
                action_id=action_id,
                error=str(e),
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "stagger_error",
                    "error": str(e),
                    "action_id": action_id,
                }
            )
            return None

        # Step 3: Re-check if claim is still valid (another branch may have won)
        claim = self._idempotency_store.is_claimed(action_id)
        if claim is None:
            # Claim was lost (someone else fired)
            self._log.debug(
                "b5.claim_lost_post_stagger",
                action_id=action_id,
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "claim_lost_post_stagger",
                    "action_id": action_id,
                }
            )
            return None

        # Step 4: Get T3 AppleScript translator
        t3_translator = self._translator_registry.get("T3")
        if t3_translator is None:
            self._log.warning(
                "b5.t3_unavailable",
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "t3_unavailable",
                    "target_key": target_key,
                }
            )
            return None

        # Step 5: Resolve target via T3
        pid = failure_ctx.get("pid", 0)
        if pid == 0:
            self._log.warning(
                "b5.pid_missing",
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "pid_missing",
                    "target_key": target_key,
                }
            )
            return None

        try:
            from cua_overlay.translators.base import TargetSpec

            target_spec = TargetSpec(key=target_key)
            as_target = await t3_translator.resolve(
                bundle_id=bundle_id,
                pid=pid,
                target_spec=target_spec,
            )

            if as_target is None:
                self._log.debug(
                    "b5.target_resolve_failed",
                    target_key=target_key,
                )
                await self._emit_event(
                    {
                        "event": "branch_failed",
                        "branch": "B5_APPLESCRIPT_FALLBACK",
                        "reason": "target_resolve_failed",
                        "target_key": target_key,
                    }
                )
                return None

        except Exception as e:
            self._log.error(
                "b5.resolve_error",
                target_key=target_key,
                error=str(e),
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "resolve_error",
                    "error": str(e),
                    "target_key": target_key,
                }
            )
            return None

        # Step 6: Get C4 channel (AppleScript)
        c4_channel = self._channel_registry.get("C4")
        if c4_channel is None:
            self._log.warning(
                "b5.c4_unavailable",
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "c4_unavailable",
                    "target_key": target_key,
                }
            )
            return None

        # Step 7: Fire C4 channel
        try:
            from cua_overlay.state.causal_dag import ActionCanonical
            import time

            action = ActionCanonical(
                id=action_id,
                step_idx=0,
                kind="READ",
                target_key=target_key,
                action_type=action_type,
                payload={},
                timestamp_ns=int(time.monotonic_ns()),
                session_id=failure_ctx.get("session_id", "unknown"),
            )

            cancel_event = anyio.Event()

            outcome = await c4_channel.fire(
                action=action,
                target=as_target,
                store=self._idempotency_store,
                cancel_event=cancel_event,
            )

            if outcome.status != "fired":
                self._log.debug(
                    "b5.channel_fire_failed",
                    channel=outcome.channel,
                    status=outcome.status,
                    error=outcome.error,
                )
                await self._emit_event(
                    {
                        "event": "branch_failed",
                        "branch": "B5_APPLESCRIPT_FALLBACK",
                        "reason": "channel_fire_failed",
                        "status": outcome.status,
                    }
                )
                return None

            # Success
            await self._emit_event(
                {
                    "event": "branch_success",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "channel": outcome.channel,
                    "target_key": target_key,
                    "stagger_applied_ms": self._as_stagger_ms,
                }
            )
            return outcome

        except Exception as e:
            self._log.error(
                "b5.fire_error",
                target_key=target_key,
                error=str(e),
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B5_APPLESCRIPT_FALLBACK",
                    "reason": "fire_error",
                    "error": str(e),
                }
            )
            return None
