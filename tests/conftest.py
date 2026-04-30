"""Shared test fixtures for cua-maximalist.

Phase 1 Plan 02 minimal version. Plan 01-01 (sibling, Wave 1) provides the
richer version with structlog config + calculator_pid fixture.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """A throwaway session directory for tests."""
    d = tmp_path / "session"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture(scope="session")
def calculator_pid():
    """Launch Calculator.app once per session and yield its PID.

    Session-scoped so we don't kill+relaunch between tests (relaunch is racy
    on macOS — NSWorkspace caches the dying pid for 1-2s and `open -a` can
    re-attach to it). The teardown quits Calculator at session end via
    AppleScript (clean shutdown vs SIGTERM, which leaves zombie pids).

    Skip via SKIP_INTEGRATION=1.

    Plan 01-01 owns the canonical version; this minimal copy lets Plan 01-02's
    integration test run if 01-01's conftest has not landed yet.
    """
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("SKIP_INTEGRATION=1; Calculator integration test skipped")

    def _find_calculator_pid() -> int | None:
        """Return the PID of the running Calculator process, if any.

        We use `pgrep` directly instead of NSWorkspace because NSWorkspace's
        `runningApplications` cache only refreshes when the CFRunLoop ticks
        — and we have no run loop in the asyncio test thread, so it never
        sees apps launched during the test session.
        """
        try:
            out = subprocess.check_output(
                ["pgrep", "-x", "Calculator"], text=True
            ).strip()
        except subprocess.CalledProcessError:
            return None
        if not out:
            return None
        # pgrep can list multiple matching pids; take the first that's alive.
        for line in out.splitlines():
            try:
                pid_ = int(line.strip())
            except ValueError:
                continue
            try:
                os.kill(pid_, 0)
            except (ProcessLookupError, PermissionError):
                continue
            return pid_
        return None

    # If an existing Calculator is already running (from a previous test in
    # the same session), terminate it cleanly and wait for it to fully exit.
    # This prevents `open -a` from racing with a dying process — NSWorkspace
    # otherwise still reports the dying pid for ~1-2s.
    existing = _find_calculator_pid()
    if existing is not None:
        try:
            os.kill(existing, signal.SIGTERM)
        except ProcessLookupError:
            pass
        kill_deadline = time.monotonic() + 8.0
        while time.monotonic() < kill_deadline:
            if _find_calculator_pid() is None:
                # Also confirm the OS-level pid is gone.
                try:
                    os.kill(existing, 0)
                except (ProcessLookupError, PermissionError):
                    break
            time.sleep(0.1)

    subprocess.run(["open", "-a", "Calculator"], check=True)

    # macOS uses bundle id "com.apple.calculator" (lowercase) at runtime.
    pid = None
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        pid = _find_calculator_pid()
        if pid is not None:
            break
        time.sleep(0.1)
    if pid is None:
        pytest.skip("Calculator.app failed to launch within 15s")

    # Wait until Calculator's AX tree is actually populated. NSWorkspace
    # reports the process before AppKit has finished bringing the window up,
    # so AXChildren can return [] for ~0.5-1.5s. Poll until we see >0 children
    # (or timeout — caller will surface a meaningful test failure if AX never
    # comes up).
    try:
        from HIServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXChildrenAttribute,
        )

        ax_deadline = time.monotonic() + 15.0
        while time.monotonic() < ax_deadline:
            app_ref = AXUIElementCreateApplication(pid)
            err, children = AXUIElementCopyAttributeValue(
                app_ref, kAXChildrenAttribute, None
            )
            if err == 0 and children is not None and len(children) > 0:
                break
            time.sleep(0.2)
    except ImportError:
        # No HIServices available — let the test surface the issue.
        pass

    yield pid

    # Clean session-end quit via AppleScript. Avoid SIGTERM — it leaves
    # NSWorkspace caching the dying pid, which races with subsequent runs.
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Calculator" to quit'],
            check=False,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
