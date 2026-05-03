"""Integration tests for NSWorkspaceObserver.

These tests need a real macOS desktop session + AppKit (PyObjC). They're
marked ``@pytest.mark.integration`` and skipped under ``SKIP_INTEGRATION=1``.
"""
from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from basicctrl.verifier.nsworkspace import NSWorkspaceObserver


@pytest.mark.integration
@pytest.mark.asyncio
async def test_frontmost_change(calculator_pid: int) -> None:
    """NSWorkspaceObserver fires within 2s when Calculator becomes frontmost.

    The fixture launches Calculator (which usually activates it), but we also
    explicitly re-activate via ``open -a Calculator`` to provoke a fresh
    notification.
    """
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("SKIP_INTEGRATION=1")

    loop = asyncio.get_running_loop()
    seen: list[tuple[str, int]] = []
    activated = asyncio.Event()

    def _on_change(bundle_id: str, pid: int) -> None:
        seen.append((bundle_id, pid))
        if bundle_id == "com.apple.Calculator":
            activated.set()

    obs = NSWorkspaceObserver(loop)
    obs.on_frontmost_change(_on_change)
    obs.start()

    try:
        # Activate Calculator (it may already be frontmost from the fixture).
        subprocess.run(["open", "-a", "Calculator"], check=True)
        # Some Macs need a follow-up activation to fire the notification reliably.
        await asyncio.sleep(0.2)
        subprocess.run(["open", "-a", "Calculator"], check=True)

        try:
            await asyncio.wait_for(activated.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pytest.fail(
                f"NSWorkspaceDidActivateApplicationNotification never fired for "
                f"com.apple.Calculator — saw {seen}"
            )
    finally:
        obs.stop()

    assert any(bundle == "com.apple.Calculator" for bundle, _pid in seen)
