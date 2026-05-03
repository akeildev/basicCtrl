"""Resume contract — read the last checkpoint for a session, or ``None``.

PERSIST-03: after a crash, the next process must be able to read the last
verified step's (pre, action, post) tuple from Postgres and decide whether
to retry, advance, or escalate. Phase 1 ships the contract; Phase 6 wraps
every translator's race orchestrator so a kill -9 mid-task resumes
deterministically from the last verified step.

Usage::

    durable = DurableExecutor()
    await durable.setup()
    ctx = await resume_from_checkpoint(session_id, durable)
    if ctx is None:
        # Fresh session — start from step 0.
        ...
    else:
        # Resume from after ctx.last_step_idx using ctx.last_verified_action
        # and the on-disk snapshot at ctx.snapshot_path.
        ...
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import structlog

from cua_overlay.persist.durable_step import DurableExecutor
from cua_overlay.state.causal_dag import ActionCanonical


@dataclass
class ResumeContext:
    """Read-back of the last verified step for a crashed session.

    Attributes:
        session_id: The thread_id originally used by ``DurableExecutor.checkpoint``.
        last_step_idx: The step_idx of the last successfully checkpointed action.
        last_verified_action: The full ``ActionCanonical`` from that step,
            re-validated through Pydantic so the contract is invariant.
        snapshot_path: Where the on-disk StateGraph snapshot SHOULD live
            (``~/.cua/sessions/<id>/snapshot.json``). The caller should
            check ``snapshot_path.exists()`` — a recently-crashed session
            may have a stale or missing snapshot, in which case the
            resumer should rebuild from scratch.
    """

    session_id: str
    last_step_idx: int
    last_verified_action: ActionCanonical
    snapshot_path: Path


async def resume_from_checkpoint(
    session_id: str,
    durable: DurableExecutor,
    base: Optional[Path] = None,
) -> Optional[ResumeContext]:
    """Restore state from the last Postgres checkpoint, or ``None`` if fresh.

    Args:
        session_id: The thread_id used during the original session's
            ``DurableExecutor.checkpoint`` calls.
        durable: An already-``setup()``-ed ``DurableExecutor`` connected to
            the same Postgres instance the original session wrote to.
        base: The session-tree root. Defaults to ``~/.cua/sessions``; tests
            override to ``tmp_path``.

    Returns:
        ``None`` if no checkpoint row exists for ``session_id`` (a fresh
        session that never wrote one). Otherwise a ``ResumeContext`` with
        the last verified step.

    The action dict in the checkpoint is round-tripped through
    ``ActionCanonical.model_validate`` — if the schema has drifted since
    the row was written, the function logs and returns ``None`` (treated
    as a corrupt/incompatible resume; caller should start fresh).
    """
    log = structlog.get_logger().bind(session_id=session_id)
    checkpoint = await durable.latest_checkpoint(session_id)
    if not checkpoint:
        log.info("resume.no_checkpoint")
        return None

    step_idx_raw = checkpoint.get("step_idx")
    action_dump = checkpoint.get("action")
    if step_idx_raw is None or action_dump is None:
        log.error(
            "resume.incomplete_checkpoint",
            has_step_idx=step_idx_raw is not None,
            has_action=action_dump is not None,
        )
        return None

    try:
        action = ActionCanonical.model_validate(action_dump)
    except Exception as e:
        log.error("resume.invalid_action_dump", error=str(e))
        return None

    sessions_base = base if base is not None else Path.home() / ".cua" / "sessions"
    snapshot_path = sessions_base / session_id / "snapshot.json"

    ctx = ResumeContext(
        session_id=session_id,
        last_step_idx=int(step_idx_raw),
        last_verified_action=action,
        snapshot_path=snapshot_path,
    )
    log.info(
        "resume.restored",
        last_step_idx=ctx.last_step_idx,
        snapshot_exists=snapshot_path.exists(),
    )
    return ctx
