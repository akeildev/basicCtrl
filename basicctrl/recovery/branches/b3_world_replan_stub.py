"""B3_WORLD_REPLAN — Phase 3 stub (Phase 4 placeholder).

Per CONTEXT.md D-06: B3 is a placeholder in Phase 3. Phase 4 will implement
the world-model predictor (CUWM-style) that re-plans based on observed
world state deltas.

For Phase 3, B3 simply emits a branch_skipped event and returns None,
allowing B1/B2/B4/B5 to attempt recovery.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import structlog

from cua_overlay.recovery.branches import BranchBase

if TYPE_CHECKING:
    from cua_overlay.actions.channels.base import ChannelOutcome
    from cua_overlay.actions.idempotency import IdempotencyTokenStore
    from cua_overlay.persist.session_writer import SessionWriter
    from cua_overlay.recovery.classifier import FailureCtx


class B3_WorldReplan(BranchBase):
    """Phase 3 stub: world-model replan (Phase 4 implementation pending).

    Emits a branch_skipped event with reason "cognition not yet ready" to
    indicate this branch should be implemented in Phase 4.
    """

    name: str = "B3_WORLD_REPLAN"

    def __init__(
        self,
        idempotency_store: Optional[IdempotencyTokenStore] = None,
        session_writer: Optional[SessionWriter] = None,
    ):
        """Initialize B3 stub.

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
                "branch": "B3_WORLD_REPLAN",
                "reason": "cognition not yet ready — Phase 4",
                "ts": datetime.utcnow().isoformat(),
                "target_key": target_key,
            }
        )

        self._log.debug(
            "b3.skipped",
            target_key=target_key,
            reason="phase_4_pending",
        )

        return None
