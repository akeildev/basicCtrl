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

from basicctrl.persist.session_writer import SessionWriter
from basicctrl.persist.snapshot_io import atomic_write_json, read_json

__all__ = [
    "SessionWriter",
    "atomic_write_json",
    "read_json",
]


# Deferred imports — durable_step (Task 2) and resume (Task 3) land separately.
# Each is wrapped independently so partial state during plan execution is OK.
try:
    from basicctrl.persist.durable_step import DurableExecutor  # noqa: F401

    __all__.append("DurableExecutor")
except ImportError:
    pass

try:
    from basicctrl.persist.resume import (  # noqa: F401
        ResumeContext,
        resume_from_checkpoint,
    )

    __all__ += ["ResumeContext", "resume_from_checkpoint"]
except ImportError:
    pass
