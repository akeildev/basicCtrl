"""B4_PLANNER_REQUERY — Phase 3 stub (Phase 4 placeholder).

Per CONTEXT.md D-07: B4 is a placeholder in Phase 3. Phase 4 will implement
the Opus planner requery that re-plans the action from scratch with updated
world state.

For Phase 3, B4 simply emits a branch_skipped event and returns None,
allowing B1/B2/B3/B5 to attempt recovery.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import structlog

from basicctrl.recovery.branches import BranchBase

if TYPE_CHECKING:
    from basicctrl.actions.channels.base import ChannelOutcome
    from basicctrl.actions.idempotency import IdempotencyTokenStore
    from basicctrl.persist.session_writer import SessionWriter
    from basicctrl.recovery.classifier import FailureCtx


class B4_PlannerRequery(BranchBase):
    """Phase 3 stub: Opus planner requery (Phase 4 implementation pending).

    Emits a branch_skipped event with reason "cognition not yet ready" to
    indicate this branch should be implemented in Phase 4.
    """

    name: str = "B4_PLANNER_REQUERY"

    def __init__(
        self,
        idempotency_store: Optional[IdempotencyTokenStore] = None,
        session_writer: Optional[SessionWriter] = None,
    ):
        """Initialize B4 stub.

        Args:
            idempotency_store: Not used in stub; for protocol compatibility
            session_writer: SessionWriter for event emission (optional in Phase 3)
        """
        # Initialize with dummy values if not provided
        if idempotency_store is None:
            from unittest.mock import AsyncMock

            idempotency_store = AsyncMock()
        if session_writer is None:
            from unittest.mock import AsyncMock

            session_writer = AsyncMock()

        super().__init__(
            name=self.name,
            _idempotency=idempotency_store,
            _session_writer=session_writer,
        )
        self._log = structlog.get_logger()

    async def attempt(
        self, failure_ctx: FailureCtx
    ) -> Optional[ChannelOutcome]:
        """Emit branch_skipped event and return None (stub).

        Args:
            failure_ctx: Failure context (unused in stub)

        Returns:
            None (always fails, allowing other branches to attempt)
        """
        target_key = failure_ctx.get("target_key", "unknown")

        await self._emit_event(
            {
                "event": "branch_skipped",
                "branch": "B4_PLANNER_REQUERY",
                "reason": "cognition not yet ready — Phase 4",
                "ts": datetime.utcnow().isoformat(),
                "target_key": target_key,
            }
        )

        self._log.debug(
            "b4.skipped",
            target_key=target_key,
            reason="phase_4_pending",
        )

        return None
