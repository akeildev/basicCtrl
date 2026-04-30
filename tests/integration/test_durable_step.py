"""Integration tests for ``cua_overlay.persist.durable_step.DurableExecutor``.

Covers PERSIST-01:
* setup() provisions LangGraph PostgresSaver tables (checkpoints,
  checkpoint_writes, checkpoint_blobs).
* checkpoint() writes a (pre, action, post) tuple keyed by
  (thread_id=session_id, checkpoint_id=step_idx).
* latest_checkpoint() reads back the most recent (pre, action, post) state.
* aclose() releases the connection cleanly.

Marked ``@pytest.mark.integration`` — Postgres must be running locally with
the ``cua_maximalist`` database created. Run ``bash scripts/init_postgres.sh``
once before the suite. If the connection fails, tests skip with a clear
message instead of failing the run.
"""
from __future__ import annotations

import os
import uuid

import pytest

from cua_overlay.persist.durable_step import DurableExecutor
from cua_overlay.state.causal_dag import ActionCanonical, HoarePost, HoarePre

pytestmark = pytest.mark.integration


# Skip the whole module if the orchestrator forced unit-only mode.
if os.environ.get("SKIP_INTEGRATION") == "1":
    pytest.skip("integration tests skipped via SKIP_INTEGRATION=1", allow_module_level=True)


def _try_connect_or_skip() -> None:
    """Try to open a connection; pytest.skip if Postgres is unreachable.

    Avoids confusing failures on dev machines without ``brew services start
    postgresql@16 && createdb cua_maximalist``.
    """
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


async def test_setup_creates_tables() -> None:
    """After setup(), the LangGraph schema tables exist in Postgres."""
    _try_connect_or_skip()
    import psycopg

    durable = DurableExecutor()
    try:
        await durable.setup()
    finally:
        await durable.aclose()

    # Now query directly.
    with psycopg.connect("postgresql://localhost:5432/cua_maximalist") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            tables = {row[0] for row in cur.fetchall()}
    assert "checkpoints" in tables, f"missing checkpoints table; have {tables}"
    assert "checkpoint_writes" in tables, f"missing checkpoint_writes; have {tables}"
    assert "checkpoint_blobs" in tables, f"missing checkpoint_blobs; have {tables}"


async def test_checkpoint_writes_row() -> None:
    """checkpoint() writes a row to Postgres for this thread_id."""
    _try_connect_or_skip()
    import psycopg

    session_id = f"test-{uuid.uuid4()}"
    durable = DurableExecutor()
    await durable.setup()
    try:
        pre, action, post = _make_triple(0, session_id)
        await durable.checkpoint(session_id, 0, pre, action, post)
    finally:
        await durable.aclose()

    with psycopg.connect("postgresql://localhost:5432/cua_maximalist") as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM checkpoints WHERE thread_id = %s", (session_id,)
            )
            row = cur.fetchone()
    assert row is not None
    assert row[0] >= 1, f"expected ≥1 checkpoint row, got {row[0]}"


async def test_latest_checkpoint_returns_step_idx() -> None:
    """After 3 checkpoints (step_idx=0, 1, 2), latest_checkpoint returns step_idx=2."""
    _try_connect_or_skip()

    session_id = f"test-{uuid.uuid4()}"
    durable = DurableExecutor()
    await durable.setup()
    try:
        for step_idx in (0, 1, 2):
            pre, action, post = _make_triple(step_idx, session_id)
            await durable.checkpoint(session_id, step_idx, pre, action, post)
        latest = await durable.latest_checkpoint(session_id)
    finally:
        await durable.aclose()

    assert latest is not None
    assert int(latest["step_idx"]) == 2


async def test_aclose_releases_connection() -> None:
    """After aclose(), checkpoint() raises (connection closed)."""
    _try_connect_or_skip()

    session_id = f"test-{uuid.uuid4()}"
    durable = DurableExecutor()
    await durable.setup()
    pre, action, post = _make_triple(0, session_id)
    await durable.checkpoint(session_id, 0, pre, action, post)
    await durable.aclose()

    with pytest.raises(RuntimeError, match="not setup"):
        await durable.checkpoint(session_id, 1, pre, action, post)


async def test_setup_is_idempotent() -> None:
    """Calling setup() twice is a no-op; the second call doesn't reopen."""
    _try_connect_or_skip()

    durable = DurableExecutor()
    try:
        await durable.setup()
        # Second call should not raise / re-open
        await durable.setup()
    finally:
        await durable.aclose()


def test_mask_conn_redacts_credentials() -> None:
    """A conn string with embedded credentials is masked when logged.

    Regression test for T-1-02 — even though the default conn string has no
    password (peer auth), a future caller passing one explicitly must still
    have it stripped before any structlog event.
    """
    safe = DurableExecutor("postgresql://localhost:5432/cua_maximalist")
    assert safe._mask_conn() == "postgresql://localhost:5432/cua_maximalist"
    risky = DurableExecutor("postgresql://user:s3cret@localhost:5432/cua_maximalist")
    masked = risky._mask_conn()
    assert "s3cret" not in masked
    assert "user" not in masked
    assert "***" in masked
