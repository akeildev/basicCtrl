"""Resume-from-crash durability — Phase D acceptance for G4.

Gate: CUA_RUN_E2E_DURABILITY=1

Verifies that DurableExecutor can resume from the last committed checkpoint
after a crash. We simulate "crash" by aclose()-ing the executor mid-sequence
(no graceful flush), then re-instantiating a fresh DurableExecutor with the
SAME session_id and reading `latest_checkpoint`. This proves the on-disk
state is the source of truth, not in-process memory.

We avoid spawning a Calculator-driven subprocess because that adds many
unrelated failure modes (TCC grants, AX bridge, race orchestrator). The
existing `tests/integration/test_durable_step.py` covers the primitive;
this file specifically pins resume-after-loss-of-process-state.

Acceptance:
  - Write 5 checkpoints (steps 0-4)
  - Drop the executor reference + new executor with same session_id
  - latest_checkpoint returns step_idx=4
  - Resume budget < 2s wall

Cleanup deletes test rows from Postgres so reruns are deterministic.
"""
from __future__ import annotations

import os
import time
import uuid

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_E2E_DURABILITY") != "1",
        reason="set CUA_RUN_E2E_DURABILITY=1 to enable",
    ),
]


def _try_connect_or_skip() -> None:
    """Skip cleanly if Postgres unreachable."""
    import psycopg

    try:
        with psycopg.connect(
            "postgresql://localhost:5432/basicctrl", connect_timeout=2
        ):
            pass
    except Exception as e:
        pytest.skip(f"Postgres unreachable: {type(e).__name__}: {e}")


def _make_triple(step_idx: int, session_id: str):
    from basicctrl.state.causal_dag import ActionCanonical, HoarePost, HoarePre

    pre = HoarePre(
        target_key=f"axid:com.test:{step_idx}",
        target_exists=True,
        target_enabled=True,
        target_role="AXButton",
        role_compatible=True,
        frontmost_app="com.test",
        no_blocking_modal=True,
        timestamp_ns=1000 + step_idx,
    )
    action = ActionCanonical(
        id=f"action-{step_idx}-{uuid.uuid4()}",
        step_idx=step_idx,
        kind="MUTATE",
        target_key=pre.target_key,
        action_type="click",
        payload={"button": "left"},
        tier="T1",
        channel="C2",
        timestamp_ns=2000 + step_idx,
        session_id=session_id,
    )
    post = HoarePost(
        target_key=pre.target_key,
        confidence=0.9,
        tier_signals={"L0": 0.9, "L1": 0.5, "L2": None, "L3": None},
        verified=True,
        healed_to=None,
        timestamp_ns=3000 + step_idx,
    )
    return pre, action, post


async def _cleanup(session_id: str) -> None:
    import psycopg

    try:
        with psycopg.connect("postgresql://localhost:5432/basicctrl") as conn:
            with conn.cursor() as cur:
                # LangGraph tables — delete by thread_id
                for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
                    cur.execute(
                        f"DELETE FROM {table} WHERE thread_id = %s", (session_id,)
                    )
            conn.commit()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_resume_from_simulated_crash_returns_latest_step() -> None:
    """Write 5 checkpoints, drop executor, re-instantiate, assert latest_step_idx=4."""
    _try_connect_or_skip()
    from basicctrl.persist import DurableExecutor

    session_id = f"durtest-{uuid.uuid4()}"

    # Phase 1: write 5 checkpoints
    durable_a = DurableExecutor()
    await durable_a.setup()
    try:
        for step_idx in range(5):
            pre, action, post = _make_triple(step_idx, session_id)
            await durable_a.checkpoint(session_id, step_idx, pre, action, post)
    finally:
        # Simulate crash: drop the executor without graceful flush.
        # aclose closes the connection pool; in a real crash the connection
        # would just go away. Either way, on-disk state is what we read next.
        await durable_a.aclose()

    # Phase 2: simulate restart — fresh executor, same session_id
    start = time.monotonic()
    durable_b = DurableExecutor()
    await durable_b.setup()
    try:
        latest = await durable_b.latest_checkpoint(session_id)
        elapsed = time.monotonic() - start

        assert latest is not None, f"no checkpoint surfaced for {session_id}"
        # latest_checkpoint may return either the raw row dict (with step_idx) or
        # a LangGraph ChannelValues dict; accept either as long as we recover step 4.
        step_idx = latest.get("step_idx")
        if step_idx is None:
            step_idx = latest.get("channel_values", {}).get("step_idx")
        assert step_idx == 4, f"expected step_idx=4, got {step_idx} from {latest!r}"
        assert elapsed < 2.0, f"resume budget exceeded: {elapsed:.3f}s > 2.0s"
    finally:
        await durable_b.aclose()
        await _cleanup(session_id)
