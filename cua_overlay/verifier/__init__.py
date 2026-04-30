"""Push-event verifier subsystem.

Re-exports the public surface that Phase 1 plan 05 (L0+L1 ensemble),
plan 08 (MCP proxy verifier wrap), and ALL of Phase 2/3
racing/recovery import.

Plan 01-04 builds this incrementally:

* Task 1 — exports ``AXObserverManager`` (built atop ``cua_overlay.ax.observer.AXEventBridge``).
* Task 2 — adds ``NSWorkspaceObserver``, ``KqueueProcObserver``, ``DistributedNotificationEvent``.
* Task 3 — Calculator integration smoke test (no new exports).
"""
from __future__ import annotations

from cua_overlay.verifier.axobserver import AXObserverManager

__all__ = [
    "AXObserverManager",
]
