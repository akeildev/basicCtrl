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


@pytest.fixture
def calculator_pid():
    """Launch Calculator.app and yield its PID. Skip if SKIP_INTEGRATION=1.

    Plan 01-01 owns the canonical version; this minimal copy lets Plan 01-02's
    integration test run if 01-01's conftest has not landed yet.
    """
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("SKIP_INTEGRATION=1; Calculator integration test skipped")

    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("AppKit not available (pyobjc not installed)")

    subprocess.run(["open", "-a", "Calculator"], check=True)

    pid = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.bundleIdentifier() == "com.apple.Calculator":
                pid = int(app.processIdentifier())
                break
        if pid is not None:
            break
        time.sleep(0.1)
    if pid is None:
        pytest.skip("Calculator.app failed to launch within 5s")

    yield pid

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
