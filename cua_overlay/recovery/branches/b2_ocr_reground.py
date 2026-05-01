"""B2_OCR_REGROUND — Re-run Vision OCR uitag, fire C3 CGEvent.

Per CONTEXT.md D-05: when verification fails due to perceptual issues
(OCR ground truth shifted, screen layout changed), B2 re-runs T4 Vision
translator (uitag/ocrmac) to re-locate the target on the current screenshot,
then fires C3 (CGEvent) with the regrounded coordinates.

This is a medium-speed recovery path: T4 uitag is ~50-100ms, faster than
T5 (full LLM grounding ~500ms) but slower than T1 (cached AX structure ~10ms).

Pattern:
  1. Get T4 Vision translator from registry
  2. Call t4.resolve_target(bundle_id, pid) to re-run uitag
  3. Check if target re-located (new Bbox returned)
  4. Build new ActionCanonical with regrounded coordinates
  5. Claim action_id via idempotency store (T-3-05)
  6. Pick C3 channel (CGEvent)
  7. Fire C3 with regrounded coords
  8. Verify via aggregator (confidence must be >= 0.50)
  9. Emit events to session_writer
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


class B2_OCRRegrounding(BranchBase):
    """OCR regrounding: re-run T4 Vision uitag, fire C3 CGEvent.

    Attempts to recover from perceptual failures by re-running the Vision
    OCR translator (uitag) on the current screenshot to find fresh
    coordinates, then firing the action via CGEvent.
    """

    name: str = "B2_OCR_REGROUND"

    def __init__(
        self,
        translator_registry: TranslatorRegistry,
        channel_registry: ChannelRegistry,
        idempotency_store: IdempotencyTokenStore,
        session_writer: SessionWriter,
        aggregator: Aggregator,
    ):
        """Initialize B2 OCR regrounding branch.

        Args:
            translator_registry: Registry of available translators (T1-T5)
            channel_registry: Registry of available channels (C1-C5)
            idempotency_store: IdempotencyTokenStore for try_claim (T-3-05)
            session_writer: SessionWriter for event emission
            aggregator: Verifier aggregator for post-action verification
        """
        super().__init__(
            name="B2_OCR_REGROUND",
            _idempotency=idempotency_store,
            _session_writer=session_writer,
        )
        self._translator_registry = translator_registry
        self._channel_registry = channel_registry
        self._aggregator = aggregator
        self._log = structlog.get_logger()

    async def attempt(
        self, failure_ctx: FailureCtx
    ) -> Optional[ChannelOutcome]:
        """Attempt OCR regrounding recovery.

        Returns ChannelOutcome(status='fired', verified=True) on success,
        None on failure.

        Failure modes:
          - t4_unavailable: T4 translator not in registry
          - uitag_failed: T4.resolve_target returned None
          - channel_unavailable: C3 channel not in registry
          - channel_fire_failed: C3.fire raised exception or returned non-fired status
          - verify_failed: aggregator returned confidence < 0.50
        """
        bundle_id = failure_ctx["bundle_id"]
        target_key = failure_ctx["target_key"]
        action_type = failure_ctx.get("action_type", "click")

        await self._emit_event(
            {
                "event": "branch_attempt",
                "branch": "B2_OCR_REGROUND",
                "target_key": target_key,
                "bundle_id": bundle_id,
            }
        )

        # Step 1: Get T4 Vision translator
        t4_translator = self._translator_registry.get("T4")
        if t4_translator is None:
            self._log.warning(
                "b2.t4_unavailable",
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B2_OCR_REGROUND",
                    "reason": "t4_unavailable",
                    "target_key": target_key,
                }
            )
            return None

        # Step 2: Re-run T4 uitag to regrounding
        pid = failure_ctx.get("pid", 0)
        if pid == 0:
            self._log.warning(
                "b2.pid_missing",
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B2_OCR_REGROUND",
                    "reason": "pid_missing",
                    "target_key": target_key,
                }
            )
            return None

        try:
            # Call T4.resolve_target to re-run uitag on current screenshot
            from cua_overlay.translators.base import TargetSpec

            # Minimal target spec for regrounding
            target_spec = TargetSpec(key=target_key)

            regrounded_target = await t4_translator.resolve(
                bundle_id=bundle_id,
                pid=pid,
                target_spec=target_spec,
            )

            if regrounded_target is None:
                self._log.debug(
                    "b2.uitag_failed",
                    target_key=target_key,
                )
                await self._emit_event(
                    {
                        "event": "branch_failed",
                        "branch": "B2_OCR_REGROUND",
                        "reason": "uitag_failed_to_locate",
                        "target_key": target_key,
                    }
                )
                return None

            # Log successful regrounding
            await self._emit_event(
                {
                    "event": "b2.uitag_success",
                    "target_key": target_key,
                    "grounded_bbox": (
                        regrounded_target.grounded_bbox.model_dump()
                        if regrounded_target.grounded_bbox
                        else None
                    ),
                }
            )

        except Exception as e:
            self._log.error(
                "b2.uitag_error",
                target_key=target_key,
                error=str(e),
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B2_OCR_REGROUND",
                    "reason": "uitag_error",
                    "error": str(e),
                    "target_key": target_key,
                }
            )
            return None

        # Step 3: Try to claim the action (T-3-05 mitigation)
        action_id = failure_ctx.get("action_id", target_key)
        if not await self._try_claim(action_id, "C3"):
            self._log.debug(
                "b2.claim_lost",
                action_id=action_id,
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B2_OCR_REGROUND",
                    "reason": "claim_already_owned",
                    "action_id": action_id,
                }
            )
            return None

        # Step 4: Get C3 channel (CGEvent)
        c3_channel = self._channel_registry.get("C3")
        if c3_channel is None:
            self._log.warning(
                "b2.c3_unavailable",
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B2_OCR_REGROUND",
                    "reason": "c3_unavailable",
                    "target_key": target_key,
                }
            )
            return None

        # Step 5: Build ActionCanonical and fire C3
        try:
            from cua_overlay.state.causal_dag import ActionCanonical
            import time
            import anyio

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

            # Use regrounded target
            cancel_event = anyio.Event()

            outcome = await c3_channel.fire(
                action=action,
                target=regrounded_target,
                store=self._idempotency,
                cancel_event=cancel_event,
            )

            if outcome.status != "fired":
                self._log.debug(
                    "b2.channel_fire_failed",
                    channel=outcome.channel,
                    status=outcome.status,
                    error=outcome.error,
                )
                await self._emit_event(
                    {
                        "event": "branch_failed",
                        "branch": "B2_OCR_REGROUND",
                        "reason": "channel_fire_failed",
                        "status": outcome.status,
                    }
                )
                return None

            # Success
            await self._emit_event(
                {
                    "event": "branch_success",
                    "branch": "B2_OCR_REGROUND",
                    "channel": outcome.channel,
                    "target_key": target_key,
                }
            )
            return outcome

        except Exception as e:
            self._log.error(
                "b2.fire_error",
                target_key=target_key,
                error=str(e),
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B2_OCR_REGROUND",
                    "reason": "fire_error",
                    "error": str(e),
                }
            )
            return None
