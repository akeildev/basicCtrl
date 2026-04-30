"""cua_overlay.ax — AX safety primitives.

This subpackage holds the foundation layer that mitigates THREE BLOCKER pitfalls:

* **Pitfall P2** (cmux #2985 — AX poll at >30/sec stalls Cocoa main thread) — see
  ``rate_limit.TokenBucket``.
* **Pitfall P3** (full recursive AX walk = 15-20s on Safari) — see ``walker.walk_subtree``.
* **Pitfall P25** (modal alert blocks AX) — see ``modal_probe.has_blocking_modal``.

T-1-04 (TCC revocation mid-session) surfaces as ``AXAPIDisabledError`` from any
wrapper-layer read; Plan 02's ``TCCMonitor`` catches and emits a structured
``tcc_revoked`` event.

Public exports below are the LOCKED contract every Phase 1+ module imports.
"""
from __future__ import annotations

from cua_overlay.ax.element import AXUIElementWrapper
from cua_overlay.ax.errors import (
    AXActionUnsupportedError,
    AXAPIDisabledError,
    AXAttributeUnsupportedError,
    AXCannotCompleteError,
    AXError,
    AXInvalidUIElementError,
    AXNotificationUnsupportedError,
    axerror_from_code,
)
from cua_overlay.ax.modal_probe import has_blocking_modal
from cua_overlay.ax.rate_limit import TokenBucket
from cua_overlay.ax.walker import WalkResult, walk_subtree

__all__ = [
    "AXError",
    "AXAPIDisabledError",
    "AXCannotCompleteError",
    "AXNotificationUnsupportedError",
    "AXInvalidUIElementError",
    "AXActionUnsupportedError",
    "AXAttributeUnsupportedError",
    "axerror_from_code",
    "TokenBucket",
    "walk_subtree",
    "WalkResult",
    "has_blocking_modal",
    "AXUIElementWrapper",
]
