"""Shared pytest fixtures for cua-maximalist.

* ``session_dir`` — an empty per-test session directory under ``tmp_path``
* ``_configure_structlog`` (autouse) — resets structlog test config every test
* ``calculator_pid`` — launches Calculator.app and yields its pid (integration)
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """An empty per-test session directory.

    Mirrors ``~/.cua/sessions/<id>/`` shape used by PERSIST-02 so tests that
    write snapshots / cassettes have a clean target.
    """
    sd = tmp_path / "session"
    sd.mkdir(parents=True, exist_ok=True)
    return sd


@pytest.fixture(autouse=True)
def _configure_structlog() -> Iterator[None]:
    """Reset structlog into testing mode at the start of every test.

    cua_overlay.log.configure(testing=True) installs the LogCapture processor
    so structlog.testing.capture_logs() works inside individual tests. If the
    log module isn't available yet (e.g. during the Task 1 scaffold step
    before Task 2 lands), the fixture is a no-op so tests can still run.
    """
    try:
        from cua_overlay import log as cua_log  # noqa: WPS433
    except ImportError:
        yield
        return
    try:
        cua_log.configure(testing=True)
    except Exception:  # pragma: no cover — defensive: never fail a test on logging
        pass
    yield


@pytest.fixture
def calculator_pid() -> Iterator[int]:
    """Launch /System/Applications/Calculator.app and yield its pid.

    Skipped under SKIP_INTEGRATION=1 (orchestrator parallel mode). Cleans up
    by SIGTERMing the pid on teardown so the test run leaves no Calculator
    window open.
    """
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("integration tests skipped via SKIP_INTEGRATION=1")

    # Lazy import — on a non-macOS dev host pyobjc may not be present and we
    # still want the unit suite to load.
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("AppKit (pyobjc) not available — install dev deps first")

    subprocess.run(["open", "-a", "Calculator"], check=True)

    deadline = time.monotonic() + 5.0
    pid: int | None = None
    while time.monotonic() < deadline:
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if app.bundleIdentifier() == "com.apple.Calculator":
                pid = int(app.processIdentifier())
                break
        if pid is not None:
            break
        time.sleep(0.1)

    if pid is None:
        raise RuntimeError("Calculator.app did not register with NSWorkspace within 5s")

    try:
        yield pid
    finally:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
