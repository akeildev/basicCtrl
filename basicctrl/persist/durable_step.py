"""DurableExecutor — LangGraph PostgresSaver wrapper for crash-resilient steps.

PERSIST-01: every translator call is wrapped as a durable step backed by
``langgraph.checkpoint.postgres.aio.AsyncPostgresSaver``. Phase 1 ships the
SCAFFOLD: ``setup()`` provisions the schema, ``checkpoint(...)`` writes a
single (pre, action, post) tuple keyed by (thread_id=session_id,
checkpoint_id=step_idx), ``latest_checkpoint(...)`` reads the most recent
state back, ``aclose()`` releases the underlying psycopg connection.

Phase 6 hardens this: every translator's race orchestrator wraps its action
in a durable-graph node so a kill -9 mid-task can resume from the last
verified step. Phase 1 demonstrates the contract via the simulated-crash
test in ``tests/integration/test_session_persistence.py``.

Threat model
------------
T-1-02 (LOW, Information Disclosure): The default connection string is
``postgresql://localhost:5432/basicctrl`` — no embedded credentials.
Local Postgres uses peer authentication for the local user. ``_mask_conn()``
defensively redacts ``user:password@host`` shaped strings should a future
caller pass one explicitly, so structlog events can never leak credentials.
"""
from __future__ import annotations

from typing import Any, Optional

import structlog

from basicctrl.state.causal_dag import ActionCanonical, HoarePost, HoarePre

_DEFAULT_CONN = "postgresql://localhost:5432/basicctrl"


class DurableExecutor:
    """Async wrapper around ``AsyncPostgresSaver`` (langgraph-checkpoint-postgres 3.0.5).

    Lifecycle:
        durable = DurableExecutor()
        await durable.setup()              # provisions schema (idempotent)
        await durable.checkpoint(...)      # write one (pre, action, post)
        ctx = await durable.latest_checkpoint(session_id)
        await durable.aclose()             # release the psycopg pool

    The instance is a one-shot — re-running ``setup()`` after ``aclose()`` is
    not supported (the async-context-manager handle is dropped). Construct a
    new ``DurableExecutor`` if a fresh session is needed.
    """

    def __init__(self, conn_string: str = _DEFAULT_CONN) -> None:
        self._conn_string = conn_string
        self._cm: Any = None  # AsyncPostgresSaver async context-manager handle
        self._saver: Any = None  # the saver instance once entered
        self._log = structlog.get_logger()

    async def setup(self) -> None:
        """Open the saver and provision the LangGraph schema. Idempotent."""
        if self._saver is not None:
            return
        # Late import: avoids importing the postgres driver at package init time
        # (Plan 01-01 deps are loaded eagerly; this one stays lazy so unit tests
        # of unrelated subsystems don't pay the cost).
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        self._cm = AsyncPostgresSaver.from_conn_string(self._conn_string)
        self._saver = await self._cm.__aenter__()
        await self._saver.setup()
        self._log.info("durable.setup_complete", conn=self._mask_conn())

    async def aclose(self) -> None:
        """Release the underlying psycopg connection / pool."""
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            finally:
                self._cm = None
                self._saver = None

    async def checkpoint(
        self,
        session_id: str,
        step_idx: int,
        pre: HoarePre,
        action: ActionCanonical,
        post: HoarePost,
    ) -> None:
        """Write a single (pre, action, post) tuple to Postgres.

        Keys are ``(thread_id=session_id, checkpoint_id=str(step_idx))``.
        The checkpoint payload is a LangGraph-shaped dict whose
        ``channel_values`` carries our state (step_idx, pre, action, post).
        Pydantic models are dumped via ``model_dump(mode='json')`` so
        ``datetime`` becomes ISO-8601 strings.
        """
        if self._saver is None:
            raise RuntimeError(
                "DurableExecutor not setup() — call setup() before checkpoint()"
            )
        from langgraph.checkpoint.base import empty_checkpoint
        import hashlib

        config = {
            "configurable": {
                "thread_id": session_id,
                "checkpoint_ns": "",
            }
        }
        # AsyncPostgresSaver only persists channel values whose version is
        # listed in ``new_versions`` (it diffs new vs current to populate the
        # checkpoint_blobs table). We use a SINGLE channel called ``state``
        # carrying our full (step_idx, pre, action, post) dict so every
        # checkpoint round-trips through aget intact.
        version = str(step_idx + 1)
        state_payload = {
            "step_idx": step_idx,
            "pre": pre.model_dump(mode="json"),
            "action": action.model_dump(mode="json"),
            "post": post.model_dump(mode="json"),
        }
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"state": state_payload}
        checkpoint["channel_versions"] = {"state": version}

        # Compute state hash for observability
        import json
        state_hash = hashlib.sha256(
            json.dumps(state_payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]

        self._log.info(
            "ckpt.commit_start",
            session_id=session_id,
            step_idx=step_idx,
        )

        await self._saver.aput(
            config, checkpoint, metadata={}, new_versions={"state": version}
        )

        self._log.info(
            "ckpt.commit_end",
            session_id=session_id,
            step_idx=step_idx,
            state_hash=state_hash,
        )

    async def latest_checkpoint(self, session_id: str) -> Optional[dict[str, Any]]:
        """Return the most recent checkpoint state for ``session_id``, or ``None``.

        Extracts our (step_idx, pre, action, post) dict from the ``state``
        channel inside ``channel_values``. Returns ``None`` for fresh
        sessions with no rows OR for legacy / corrupt rows where the
        ``state`` channel is missing.
        """
        if self._saver is None:
            raise RuntimeError("DurableExecutor not setup()")
        config = {"configurable": {"thread_id": session_id, "checkpoint_ns": ""}}
        cp = await self._saver.aget(config)
        if cp is None:
            return None

        # AsyncPostgresSaver.aget returns a `Checkpoint` TypedDict (a plain dict)
        # whose ``channel_values`` carries everything we wrote. Defensively
        # support older releases that may have returned a typed object.
        if isinstance(cp, dict) and "channel_values" in cp:
            channel_values = cp["channel_values"]
        else:
            channel_values = getattr(cp, "channel_values", None) or {}
        if not isinstance(channel_values, dict):
            return None

        state = channel_values.get("state")
        if not isinstance(state, dict):
            return None

        # Emit resume event
        step_idx = state.get("step_idx", -1)
        self._log.info(
            "ckpt.resume_from_crash",
            session_id=session_id,
            step_idx=step_idx,
        )

        return state

    def _mask_conn(self) -> str:
        """Return a structlog-safe representation of the conn string.

        Redacts ``user:password@host`` shapes; otherwise returns the string
        verbatim (the default conn has no creds and is fine to log).
        """
        if "@" in self._conn_string and ":" in self._conn_string.split("@")[0]:
            return "postgresql://***@***"
        return self._conn_string
