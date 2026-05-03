"""Shared pytest fixtures for basicCtrl.

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

    basicctrl.log.configure(testing=True) installs the LogCapture processor
    so structlog.testing.capture_logs() works inside individual tests. If the
    log module isn't available yet (e.g. during the Task 1 scaffold step
    before Task 2 lands), the fixture is a no-op so tests can still run.
    """
    try:
        from basicctrl import log as cua_log  # noqa: WPS433
    except ImportError:
        yield
        return
    try:
        cua_log.configure(testing=True)
    except Exception:  # pragma: no cover — defensive: never fail a test on logging
        pass
    yield


@pytest.fixture(scope="session", autouse=True)
def verify_phase5_pitfalls():
    """Verify Phase 5 pitfall mitigations via grep (runs once per session).

    Checks Swift source files for:
    - P9: SCContentFilter usage in Visualizer.swift
    - P10: No sharingType=.none (macOS 15+ deprecated)
    - P11: CAShapeLayer present in highlight view
    - P12: NSView.draw override present, no CALayer animation in ghost cursor

    These assertions enforce architecture-level constraints that cannot be
    easily tested via unit tests, so we grep-verify at test collection time.
    """
    # Verify pitfall mitigations via grep
    cwd = Path.cwd()

    # P9: SCContentFilter usage
    p9_result = subprocess.run(
        ["grep", "-c", "SCContentFilter", "libs/cua-driver/App/Visualizer.swift"],
        capture_output=True,
        cwd=cwd,
    )
    p9_count = int(p9_result.stdout.decode().strip() or "0")
    assert p9_count >= 1, "P9: SCContentFilter not found in Visualizer.swift"

    # P10: No sharingType=.none
    p10_result = subprocess.run(
        ["grep", "-c", "sharingType.*\\.none", "libs/cua-driver/App/Visualizer.swift"],
        capture_output=True,
        cwd=cwd,
    )
    p10_count = int(p10_result.stdout.decode().strip() or "0")
    assert p10_count == 0, "P10: sharingType=.none found (deprecated on macOS 15+)"

    # P11: CAShapeLayer present in highlight
    p11_result = subprocess.run(
        ["grep", "-c", "CAShapeLayer", "libs/cua-driver/App/HighlightOverlayView.swift"],
        capture_output=True,
        cwd=cwd,
    )
    p11_count = int(p11_result.stdout.decode().strip() or "0")
    assert p11_count >= 1, "P11: CAShapeLayer not found in HighlightOverlayView.swift"

    # P12: NSView.draw present in ghost cursor, no CALayer animation
    p12_draw = subprocess.run(
        ["grep", "-c", "override func draw", "libs/cua-driver/App/GhostCursorView.swift"],
        capture_output=True,
        cwd=cwd,
    )
    p12_anim = subprocess.run(
        ["grep", "-c", "CABasicAnimation\\|CAKeyframeAnimation", "libs/cua-driver/App/GhostCursorView.swift"],
        capture_output=True,
        cwd=cwd,
    )
    p12_draw_count = int(p12_draw.stdout.decode().strip() or "0")
    p12_anim_count = int(p12_anim.stdout.decode().strip() or "0")
    assert p12_draw_count >= 1, "P12: NSView.draw override not found in GhostCursorView.swift"
    assert p12_anim_count == 0, "P12: CALayer animation found in GhostCursorView.swift (performance issue)"

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
            if (app.bundleIdentifier() or "").lower() == "com.apple.calculator":
                pid = int(app.processIdentifier())
                break
        if pid is not None:
            break
        time.sleep(0.1)

    if pid is None:
        raise RuntimeError("Calculator.app did not register with NSWorkspace within 5s")

    # Activate so the keypad paints + wait for AX tree readiness.
    # Without this, tests racing right after `open -a` see an empty AX tree
    # because Calculator launches but hasn't built its UI tree yet.
    # AppleScript `activate` may block under load (Calculator busy with prior
    # test's click events) — TimeoutExpired is recoverable, the AX-readiness
    # probe below is the actual gate.
    try:
        subprocess.run(
            ["osascript", "-e", 'tell application "Calculator" to activate'],
            check=False, timeout=2.0,
        )
    except subprocess.TimeoutExpired:
        pass
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
        )
        ax_app = AXUIElementCreateApplication(pid)
        ready_deadline = time.monotonic() + 5.0
        while time.monotonic() < ready_deadline:
            err, windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
            if err == 0 and windows:
                err2, win_children = AXUIElementCopyAttributeValue(
                    windows[0], "AXChildren", None
                )
                if err2 == 0 and win_children:
                    break
            time.sleep(0.1)
        else:
            pytest.skip(
                f"Calculator pid={pid} AX tree never populated within 5s"
            )
    except ImportError:
        pass  # ApplicationServices not available; best-effort

    # Note: do NOT SIGTERM Calculator on teardown — see .planning/INTEGRATION-DEBUG.md
    # F2. Killing it here races with the next test's `open -a Calculator` and leaves
    # the AX tree half-painted. Leave Calculator running; subsequent tests reuse it.
    yield pid
