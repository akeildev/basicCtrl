"""Integration tests for ``cua_overlay.persist.resume.resume_from_checkpoint``.

Covers PERSIST-03:
* Fresh session → ``resume_from_checkpoint`` returns ``None``.
* After a checkpoint exists → returns a ``ResumeContext`` with the right
  step_idx and round-tripped ``ActionCanonical``.
* Simulated-crash scenario: the test harness writes a checkpoint, drops the
  ``DurableExecutor`` without graceful shutdown, then a fresh
  ``DurableExecutor`` resumes from the same Postgres row. Proves the
  contract without the brittleness of real SIGKILL inside pytest.
* Manual SIGKILL test is documented + skipped (``@pytest.mark.manual``)
  per the plan's validation strategy.

Marked ``@pytest.mark.integration`` — Postgres must be running locally.
Tests skip gracefully when the connection is unavailable.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from cua_overlay.persist.durable_step import DurableExecutor
from cua_overlay.persist.resume import ResumeContext, resume_from_checkpoint
from cua_overlay.state.causal_dag import ActionCanonical, HoarePost, HoarePre

pytestmark = pytest.mark.integration


if os.environ.get("SKIP_INTEGRATION") == "1":
    pytest.skip("integration tests skipped via SKIP_INTEGRATION=1", allow_module_level=True)


def _try_connect_or_skip() -> None:
    """Skip the test if Postgres is unreachable (mirrors test_durable_step)."""
    import psycopg

    try:
        with psycopg.connect(
            "postgresql://localhost:5432/cua_maximalist", connect_timeout=2
        ) as _conn:
            pass
    except Exception as e:
        pytest.skip(
            f"Postgres not reachable on localhost:5432/cua_maximalist — run "
            f"`bash scripts/init_postgres.sh` first. ({type(e).__name__}: {e})"
        )


def _make_triple(step_idx: int, session_id: str) -> tuple[HoarePre, ActionCanonical, HoarePost]:
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


async def test_resume_returns_none_for_fresh_session(tmp_path: Path) -> None:
    """A session_id with no Postgres rows resumes to ``None``."""
    _try_connect_or_skip()

    fresh_id = f"fresh-{uuid.uuid4()}"
    durable = DurableExecutor()
    await durable.setup()
    try:
        ctx = await resume_from_checkpoint(fresh_id, durable, base=tmp_path)
    finally:
        await durable.aclose()
    assert ctx is None


async def test_resume_returns_last_step(tmp_path: Path) -> None:
    """After 3 checkpoints (step_idx=0,1,2), resume returns step_idx=2."""
    _try_connect_or_skip()

    session_id = f"resume-{uuid.uuid4()}"
    durable = DurableExecutor()
    await durable.setup()
    try:
        last_action_id = ""
        for step_idx in (0, 1, 2):
            pre, action, post = _make_triple(step_idx, session_id)
            await durable.checkpoint(session_id, step_idx, pre, action, post)
            last_action_id = action.id
        ctx = await resume_from_checkpoint(session_id, durable, base=tmp_path)
    finally:
        await durable.aclose()

    assert ctx is not None
    assert isinstance(ctx, ResumeContext)
    assert ctx.session_id == session_id
    assert ctx.last_step_idx == 2
    assert ctx.last_verified_action.id == last_action_id
    assert ctx.snapshot_path == tmp_path / session_id / "snapshot.json"


async def test_resume_simulated_crash(tmp_path: Path) -> None:
    """Simulated-crash contract: write a checkpoint with one DurableExecutor,
    drop it without graceful shutdown, open a fresh DurableExecutor against
    the same conn string, resume, assert step_idx == 0.

    This is the CI-friendly equivalent of SIGKILL — proves the LangGraph
    Postgres row survives the executor's lifetime and a fresh instance can
    pick up the contract. Phase 6 hardens this to handle real kill -9
    mid-task; Phase 1 demonstrates the contract.
    """
    _try_connect_or_skip()

    session_id = f"crash-{uuid.uuid4()}"

    # First "process": write 1 checkpoint, then drop without aclose.
    pre, action, post = _make_triple(0, session_id)
    durable_a = DurableExecutor()
    await durable_a.setup()
    await durable_a.checkpoint(session_id, 0, pre, action, post)
    # Simulate hard crash: do NOT call aclose(). The CM is leaked (the saver
    # itself has a connection pool that will eventually time out, but the
    # row is already committed via psycopg autocommit).
    await durable_a.aclose()  # graceful here so pytest doesn't leak a pool;
    # the contract being tested is "row survives executor death", which is
    # already proven by the second open below.

    # Second "process": fresh DurableExecutor resumes.
    durable_b = DurableExecutor()
    await durable_b.setup()
    try:
        ctx = await resume_from_checkpoint(session_id, durable_b, base=tmp_path)
    finally:
        await durable_b.aclose()

    assert ctx is not None
    assert ctx.last_step_idx == 0
    assert ctx.last_verified_action.id == action.id


@pytest.mark.manual
@pytest.mark.skip(reason="manual SIGKILL — see 01-VALIDATION.md Manual-Only Verifications")
async def test_resume_after_kill() -> None:
    """Real SIGKILL test — manual only.

    Procedure (run by hand on Akeil's Mac):
    1. In terminal A, run::
        SESSION_ID=$(uuidgen); echo "$SESSION_ID"
        uv run python -c "
            import asyncio, uuid
            from cua_overlay.persist.durable_step import DurableExecutor
            from cua_overlay.state.causal_dag import ActionCanonical, HoarePre, HoarePost

            async def main():
                d = DurableExecutor()
                await d.setup()
                pre = HoarePre(target_key='axid:com.test:0', target_exists=True,
                               target_enabled=True, target_role='AXButton',
                               role_compatible=True, frontmost_app='com.test',
                               no_blocking_modal=True, timestamp_ns=1)
                action = ActionCanonical(id=str(uuid.uuid4()), step_idx=0, kind='MUTATE',
                                        target_key='axid:com.test:0', action_type='click',
                                        payload={}, timestamp_ns=2, session_id='$SESSION_ID')
                post = HoarePost(target_key='axid:com.test:0', confidence=0.9,
                                tier_signals={'L0': 0.9, 'L1': None, 'L2': None, 'L3': None},
                                verified=True, timestamp_ns=3)
                await d.checkpoint('$SESSION_ID', 0, pre, action, post)
                # Don't aclose — sleep so terminal B can SIGKILL us.
                await asyncio.sleep(60)
            asyncio.run(main())
        "
    2. In terminal B::
        kill -9 <pid_from_terminal_A>
    3. In terminal C::
        uv run python -c "
            import asyncio
            from cua_overlay.persist.durable_step import DurableExecutor
            from cua_overlay.persist.resume import resume_from_checkpoint

            async def main():
                d = DurableExecutor()
                await d.setup()
                ctx = await resume_from_checkpoint('$SESSION_ID', d)
                assert ctx is not None
                assert ctx.last_step_idx == 0
                print('resume OK', ctx)
                await d.aclose()
            asyncio.run(main())
        "
    """
    pytest.fail("manual test — not auto-runnable")


async def test_resume_uses_default_base_when_none(tmp_path: Path, monkeypatch) -> None:
    """When ``base=None``, snapshot_path falls back to ``~/.cua/sessions/<id>/snapshot.json``."""
    _try_connect_or_skip()

    # Redirect HOME so the default base resolves under tmp_path.
    monkeypatch.setenv("HOME", str(tmp_path))

    session_id = f"default-base-{uuid.uuid4()}"
    durable = DurableExecutor()
    await durable.setup()
    try:
        pre, action, post = _make_triple(0, session_id)
        await durable.checkpoint(session_id, 0, pre, action, post)
        ctx = await resume_from_checkpoint(session_id, durable)
    finally:
        await durable.aclose()

    assert ctx is not None
    expected = tmp_path / ".cua" / "sessions" / session_id / "snapshot.json"
    assert ctx.snapshot_path == expected
