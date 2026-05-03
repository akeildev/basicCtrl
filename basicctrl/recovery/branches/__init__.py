"""Recovery branches: 5 parallel recovery strategies for failed actions.

Per CONTEXT.md D-03: Each branch implements the RecoveryBranch Protocol —
an async attempt() method that tries a different recovery strategy and returns
ChannelOutcome if successful, None if the branch fails.

Branches are dispatched by FailureClassifier based on the failure class
(PERCEPTUAL, COGNITIVE, ACTUATION, ENVIRONMENTAL, RESOURCE, LOOP). They execute
in parallel via RecoveryOrchestrator.race_first_complete(), with the first-
verified branch winning and cancelling the losers.

Pattern:
  - BranchBase: shared helpers (try_claim, emit_event)
  - B1_Rescroll: scroll target into view, retry via T1/C2 (D-04)
  - B2_OCRRegrounding: re-run T4 uitag, fire C3 CGEvent (D-05)
  - B3_WorldReplan: stub emitting phase_3_stub event (D-06)
  - B4_PlannerRequery: stub emitting phase_3_stub event (D-07)
  - B5_AppleScriptFallback: fire T3/C4 with 500ms stagger (D-08)

Threat T-3-05 mitigation: all branches call IdempotencyTokenStore.try_claim
BEFORE any channel.fire to prevent double-actions.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from basicctrl.actions.channels.base import ChannelOutcome
    from basicctrl.actions.idempotency import IdempotencyTokenStore
    from basicctrl.persist.session_writer import SessionWriter
    from basicctrl.recovery.classifier import FailureCtx


@runtime_checkable
class RecoveryBranch(Protocol):
    """Recovery branch Protocol: async attempt with typed return.

    Each branch attempts a different recovery strategy given a FailureCtx.
    Returns ChannelOutcome if successful, None if the branch failed.
    """

    name: str

    async def attempt(
        self, failure_ctx: FailureCtx
    ) -> Optional[ChannelOutcome]:
        """Attempt recovery. Return ChannelOutcome on success, None on failure."""
        ...


class BranchBase:
    """Base class for all recovery branches.

    Provides shared helpers:
      - _try_claim: call IdempotencyTokenStore.try_claim before firing (T-3-05)
      - _emit_event: append structured event to SessionWriter

    Per CONTEXT.md D-03: branches inherit from this to ensure idempotency
    and event logging are wired correctly.
    """

    def __init__(
        self,
        name: str,
        _idempotency: IdempotencyTokenStore,
        _session_writer: SessionWriter,
    ):
        self.name = name
        self._idempotency = _idempotency
        self._session_writer = _session_writer

    async def _try_claim(self, action_id: str, channel: str) -> bool:
        """Attempt to claim the action_id for the given channel.

        Returns True if claim succeeded, False if already claimed by another.
        Implements T-3-05 mitigation against recovery-induced double-actions.
        """
        claim = await self._idempotency.try_claim(action_id, channel)
        return claim is not None

    async def _emit_event(self, event_dict: dict) -> None:
        """Append a structured event to the SessionWriter action log.

        Used to log branch attempts, successes, failures, and other recovery
        lifecycle events for the RL training buffer and session replay.
        """
        self._session_writer.append_action_log(event_dict)


from .b1_rescroll import B1_Rescroll
from .b2_ocr_reground import B2_OCRRegrounding
# Real Phase 4 B3/B4 are wired by main.py when ANTHROPIC_API_KEY is set.
# The stub variants below are retained for the no-key fallback path
# (CognitionDisabledError → main.py substitutes B3_WorldReplan_Stub /
# B4_PlannerRequery_Stub). Both export the same Protocol shape.
from .b3_world_replan import B3RecoveryBranch as B3_WorldReplan
from .b3_world_replan_stub import B3_WorldReplan as B3_WorldReplan_Stub
from .b4_planner_replan import B4RecoveryBranch as B4_PlannerRequery
from .b4_planner_reqry_stub import B4_PlannerRequery as B4_PlannerRequery_Stub
from .b5_applescript import B5_AppleScriptFallback

__all__ = [
    "RecoveryBranch",
    "BranchBase",
    "B1_Rescroll",
    "B2_OCRRegrounding",
    "B3_WorldReplan",
    "B3_WorldReplan_Stub",
    "B4_PlannerRequery",
    "B4_PlannerRequery_Stub",
    "B5_AppleScriptFallback",
]
