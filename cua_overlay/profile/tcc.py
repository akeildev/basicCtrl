"""TCC (Accessibility) revocation monitor — Pitfall 24 mitigation.

`AXIsProcessTrusted()` is the canonical TCC check. macOS treats it as a
runtime-mutable user permission, so we re-check at every classify() entry
point and at every AX wrapper entry point (Plan 01-03).

On revocation: emit a structured `tcc_revoked` event with a System Settings
action URL the user can copy/paste, then SystemExit(2). Phase 5 will swap
the exit for an NSPanel prompt.
"""

from __future__ import annotations

import structlog

# Direct deep link to System Settings → Privacy & Security → Accessibility.
_ACTION_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"


class TCCMonitor:
    """Polled at every classify() call AND at every AX wrapper entry-point."""

    async def check(self) -> bool:
        """Return True iff this process has Accessibility (AX) TCC permission.

        Lazy import of HIServices.AXIsProcessTrusted lets tests monkey-patch
        the symbol via `monkeypatch.setattr("HIServices.AXIsProcessTrusted", ...)`.
        """
        from HIServices import AXIsProcessTrusted

        return bool(AXIsProcessTrusted())

    async def on_revocation(self) -> None:
        """Emit structlog event + raise SystemExit(2).

        Phase 1 hard-exits. Phase 5 will replace this with an NSPanel prompt.
        """
        structlog.get_logger().error("tcc_revoked", action_url=_ACTION_URL)
        raise SystemExit(2)
