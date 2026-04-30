"""Push-event verifier subsystem.

Re-exports the public surface that Phase 1 plan 05 (L0+L1 ensemble),
plan 08 (MCP proxy verifier wrap), and ALL of Phase 2/3
racing/recovery import.
"""
from __future__ import annotations

from cua_overlay.verifier.axobserver import AXObserverManager
from cua_overlay.verifier.distnotif import (
    DistributedNotificationEvent,
    DistributedNotificationObserver,
)
from cua_overlay.verifier.kqueue_proc import KqueueProcObserver
from cua_overlay.verifier.nsworkspace import NSWorkspaceObserver

__all__ = [
    "AXObserverManager",
    "DistributedNotificationEvent",
    "DistributedNotificationObserver",
    "KqueueProcObserver",
    "NSWorkspaceObserver",
]
