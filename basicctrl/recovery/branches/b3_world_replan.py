"""B3_WORLD_REPLAN — World-model replan recovery branch (Phase 4 D-22).

Per CONTEXT.md D-22: B3 calls WorldModelPredictor.predict() + Planner.replan()
to generate a replanned action when the initial action fails.

B3 respects Phase 3 contracts:
  - try_claim: atomic claim-or-fail before firing
  - cancel_event check: return None if recovery orchestrator cancelled this branch
  - max_cycles gate: orchestrator enforces max 2 cycles (not B3's concern)

Failure modes tracked for RL training + future improvements.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Optional

import structlog

from basicctrl.recovery.branches import BranchBase

if TYPE_CHECKING:
    from basicctrl.actions.channels.base import ChannelOutcome
    from basicctrl.actions.idempotency import IdempotencyTokenStore
    from basicctrl.cognition.planner import Planner, WorldModelPredictor
    from basicctrl.persist.session_writer import SessionWriter
    from basicctrl.recovery.classifier import FailureCtx
    from basicctrl.state.causal_dag import ActionCanonical
    from basicctrl.state.graph import StateGraph

PlannerFactory = Callable[[Optional[Any]], Optional[Any]]


class B3RecoveryBranch(BranchBase):
    """World-model replan branch (D-22).

    Calls WorldModelPredictor.predict() to forecast the post-state before
    action fires. If prediction suggests the action will work, attempts to
    replans via Planner. Used to recover from cognitive/perception errors.
    """

    name: str = "B3_WORLD_REPLAN"

    def __init__(
        self,
        idempotency_store: IdempotencyTokenStore,
        session_writer: SessionWriter,
        world_model_predictor: WorldModelPredictor,
        planner: Optional[Planner] = None,
        planner_factory: Optional[PlannerFactory] = None,
    ):
        """Initialize B3 recovery branch.

        Args:
            idempotency_store: IdempotencyTokenStore for try_claim (T-3-05)
            session_writer: SessionWriter for event emission
            world_model_predictor: WorldModelPredictor instance for prediction
            planner: Default planner instance (legacy path; kept for tests).
            planner_factory: Optional factory `factory(ctx) -> planner | None`.
                Takes precedence over `planner` when set: J1 wiring lets the
                orchestrator pass the live FastMCP `Context` via
                `failure_ctx["ctx"]` so the factory can pick
                MCPSamplingPlanner over the API-key-gated SDK Planner.
                When the factory returns None (no planner available), B3
                emits a `branch_failed` event and returns None.
        """
        super().__init__(
            name=self.name,
            _idempotency=idempotency_store,
            _session_writer=session_writer,
        )
        self._world_model = world_model_predictor
        self._planner = planner
        self._planner_factory = planner_factory
        self._log = structlog.get_logger()
        self._cancel_event = None  # Will be set by recovery orchestrator

    def set_cancel_event(self, event) -> None:
        """Set the cancellation event (called by orchestrator).

        Per Phase 3 contract: branches check cancel_event before firing.
        """
        self._cancel_event = event

    async def attempt(
        self, failure_ctx: FailureCtx
    ) -> Optional[ChannelOutcome]:
        """Attempt world-model replan recovery (D-22).

        D-22 flow:
        1. Check cancel_event (Phase 3 contract) — return None if set
        2. Try to claim action_id (T-3-05 idempotency)
        3. Call world_model.predict() to forecast post-state
        4. Use predicted state to guide planner.replan()
        5. Return replanned ActionCanonical or None on failure

        Args:
            failure_ctx: FailureCtx with failed action, current state, etc.

        Returns:
            None (B3 doesn't fire channels; it returns a replanned action
            for the recovery orchestrator to re-inject into the race).
        """
        bundle_id = failure_ctx["bundle_id"]
        target_key = failure_ctx["target_key"]
        action_id = failure_ctx.get("action_id", target_key)
        failed_action: ActionCanonical = failure_ctx.get("action", None)
        current_state: StateGraph = failure_ctx.get("state", None)

        await self._emit_event(
            {
                "event": "branch_attempt",
                "branch": "B3_WORLD_REPLAN",
                "target_key": target_key,
                "bundle_id": bundle_id,
            }
        )

        # Phase 3 contract: check cancel_event (D-24)
        if self._cancel_event and self._cancel_event.is_set():
            self._log.debug(
                "b3.cancelled",
                action_id=action_id,
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B3_WORLD_REPLAN",
                    "reason": "cancel_event_set",
                    "action_id": action_id,
                }
            )
            return None

        # T-3-05: Try to claim the action
        if not await self._try_claim(action_id, "B3_world_model"):
            self._log.debug(
                "b3.claim_failed",
                action_id=action_id,
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B3_WORLD_REPLAN",
                    "reason": "claim_failed",
                    "action_id": action_id,
                }
            )
            return None

        # Validate context
        if failed_action is None or current_state is None:
            self._log.warning(
                "b3.missing_context",
                action_id=action_id,
                has_action=failed_action is not None,
                has_state=current_state is not None,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B3_WORLD_REPLAN",
                    "reason": "missing_context",
                    "action_id": action_id,
                }
            )
            return None

        # J1: resolve planner per-call. Factory wins over the legacy default
        # so `failure_ctx["ctx"]` (FastMCP Context) can drive the choice
        # between MCPSamplingPlanner and the SDK Planner.
        planner = self._planner
        if self._planner_factory is not None:
            planner = self._planner_factory(failure_ctx.get("ctx"))
        if planner is None:
            self._log.info(
                "b3.no_planner_available",
                action_id=action_id,
                target_key=target_key,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B3_WORLD_REPLAN",
                    "reason": "no_planner_available",
                    "action_id": action_id,
                }
            )
            return None

        try:
            # D-22: Call world_model.predict() to forecast post-state
            self._log.info(
                "b3.predict_start",
                action_id=action_id,
                action_type=failed_action.action_type,
            )
            predicted_state = await self._world_model.predict(
                action=failed_action,
                current_state=current_state,
            )

            # D-22: Use predicted state to guide planner.replan()
            self._log.info(
                "b3.planner_replan_start",
                action_id=action_id,
                predicted_state=predicted_state,
            )

            # Construct a replan request with the failed action as context
            task_description = (
                f"Recover from failed action {failed_action.action_type} "
                f"on target {target_key}. "
                f"Predicted post-state: {predicted_state}"
            )

            # Call planner to generate replanned action(s)
            replanned_candidate = await planner.plan_action(
                task_description=task_description,
                current_state=current_state,
            )

            if not replanned_candidate or not replanned_candidate.steps:
                self._log.debug(
                    "b3.planner_returned_empty",
                    action_id=action_id,
                )
                await self._emit_event(
                    {
                        "event": "branch_failed",
                        "branch": "B3_WORLD_REPLAN",
                        "reason": "planner_returned_empty",
                        "action_id": action_id,
                    }
                )
                return None

            # Extract the first step as the replanned action
            first_step = replanned_candidate.steps[0]

            # Coerce to ActionCanonical if needed (Phase 4 allows dicts)
            if isinstance(first_step, dict):
                from basicctrl.state.causal_dag import ActionCanonical
                import time

                replanned_action = ActionCanonical(
                    id=f"{action_id}_b3_replan",
                    step_idx=0,
                    kind=first_step.get("kind", "READ"),
                    target_key=first_step.get("target_key", target_key),
                    action_type=first_step.get("action_type", "click"),
                    payload=first_step.get("payload", {}),
                    timestamp_ns=int(time.monotonic_ns()),
                    session_id=failure_ctx.get("session_id", "unknown"),
                )
            else:
                replanned_action = first_step

            self._log.info(
                "b3.replanned",
                action_id=action_id,
                replanned_action_id=replanned_action.id,
                replanned_target=replanned_action.target_key,
            )

            await self._emit_event(
                {
                    "event": "branch_success",
                    "branch": "B3_WORLD_REPLAN",
                    "action_id": action_id,
                    "replanned_action_id": replanned_action.id,
                    "predicted_state": predicted_state,
                }
            )

            # Return the replanned action (not a ChannelOutcome)
            # The recovery orchestrator will re-inject this into the race
            return replanned_action  # type: ignore

        except Exception as e:
            self._log.error(
                "b3.replan_error",
                action_id=action_id,
                error=str(e),
                exc_info=True,
            )
            await self._emit_event(
                {
                    "event": "branch_failed",
                    "branch": "B3_WORLD_REPLAN",
                    "reason": "replan_error",
                    "error": str(e),
                    "action_id": action_id,
                }
            )
            return None
