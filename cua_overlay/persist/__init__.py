"""Per-session persistence subsystem (PERSIST-01..03).

Modules:
* ``session_writer`` — per-session ``~/.cua/sessions/<uuid>/`` directory tree
  (PERSIST-02). Plan 08 (MCP startup) and Plan 09 (Calculator demo) instantiate
  one at session start.
* ``snapshot_io`` — ``atomic_write_json`` / ``read_json``
  ``tempfile + os.replace`` primitive used by ``SessionWriter.write_snapshot``
  and Plan 02's ``app_profile.cache.dump_profile``.
* ``durable_step`` — ``DurableExecutor`` wraps
  ``langgraph.checkpoint.postgres.aio.AsyncPostgresSaver`` for crash-resilient
  (pre, action, post) checkpoint rows (PERSIST-01). Phase 1 scaffolds;
  Phase 6 hardens for kill -9 mid-task resumption under load.
* ``resume`` — ``resume_from_checkpoint`` / ``ResumeContext`` read-back
  contract for PERSIST-03; Phase 1 demonstrates via simulated-crash test.
"""
from __future__ import annotations

from cua_overlay.persist.session_writer import SessionWriter
from cua_overlay.persist.snapshot_io import atomic_write_json, read_json

__all__ = [
    "SessionWriter",
    "atomic_write_json",
    "read_json",
]


# Deferred imports — durable_step and resume are added in Plan 07 Tasks 2 & 3.
# Once those modules exist they extend __all__ via their own re-exports.
try:
    from cua_overlay.persist.durable_step import DurableExecutor  # noqa: F401
    from cua_overlay.persist.resume import (  # noqa: F401
        ResumeContext,
        resume_from_checkpoint,
    )

    __all__ += ["DurableExecutor", "ResumeContext", "resume_from_checkpoint"]
except ImportError:
    # Tasks 2-3 not landed yet — Task 1 tests still pass.
    pass
