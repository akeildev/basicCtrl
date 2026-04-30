"""cua_overlay.ax — AX safety primitives.

This subpackage holds the foundation layer that mitigates THREE BLOCKER pitfalls:

* **Pitfall P2** (cmux #2985 — AX poll at >30/sec stalls Cocoa main thread) — see
  ``rate_limit.TokenBucket``.
* **Pitfall P3** (full recursive AX walk = 15-20s on Safari) — see ``walker.walk_subtree``.
* **Pitfall P25** (modal alert blocks AX) — see ``modal_probe.has_blocking_modal``.

Public exports below are the LOCKED contract every Phase 1+ module imports.
"""
from __future__ import annotations

# Public exports are populated as tasks complete in plan 01-03.
# Task 1: errors + rate limit.
# Task 2: walker.
# Task 3: modal_probe + element wrapper.
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
from cua_overlay.ax.rate_limit import TokenBucket

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
]
