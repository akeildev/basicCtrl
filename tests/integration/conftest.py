"""Phase 2 integration fixtures (D-25, D-26, D-27).

Adds the Wave-0 fixtures the integration tests in Phase 2 will consume:

* ``slack_cdp_ws`` — session-scoped probe for a Slack workspace renderer
  launched with ``--remote-debugging-port=9222`` (D-25).
* ``pages_running`` — launches Pages.app and yields its pid (D-26).
* ``chess_launcher`` — launches Apple Chess.app and yields its pid (D-27).
* ``fake_idempotency_store`` — in-memory IdempotencyTokenStore wired to a
  tmp SessionWriter (skips with ``importorskip`` until Wave 1 lands).

Each fixture is skip-if-missing so the suite stays green on machines that
don't have the prerequisites available (CI without GUI, no Slack relaunch,
etc.).
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Iterator, Optional

import pytest


def _skip_if_integration_disabled() -> None:
    if os.environ.get("SKIP_INTEGRATION") == "1":
        pytest.skip("integration tests skipped via SKIP_INTEGRATION=1")


@pytest.fixture(scope="session")
async def slack_cdp_ws() -> Optional[str]:
    """Returns ws URL for Slack workspace renderer with --remote-debugging-port=9222.

    Skip-if-missing fixture (D-25). User must manually relaunch:
        pkill -9 Slack; sleep 1; open -a "Slack" --args --remote-debugging-port=9222
    """
    _skip_if_integration_disabled()
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not installed")
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=1.0) as c:
                r = await c.get("http://localhost:9222/json/version")
                if r.status_code == 200:
                    return r.json()["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.5)
    pytest.skip(
        "Slack not running with --remote-debugging-port=9222; "
        "run: pkill -9 Slack; sleep 1; open -a Slack --args --remote-debugging-port=9222"
    )


@pytest.fixture
def pages_running() -> Iterator[int]:
    """Pages.app launched (D-26). Yields pid. Cleanup leaves Pages running
    to avoid document-loss prompts."""
    _skip_if_integration_disabled()
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("AppKit (pyobjc) not available")
    subprocess.run(["open", "-a", "Pages"], check=True)
    deadline = time.monotonic() + 5.0
    pid: Optional[int] = None
    while time.monotonic() < deadline:
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if (app.bundleIdentifier() or "") == "com.apple.iWork.Pages":
                pid = int(app.processIdentifier())
                break
        if pid is not None:
            break
        time.sleep(0.1)
    if pid is None:
        pytest.skip("Pages.app failed to launch within 5s")
    yield pid
    # No teardown — leave Pages running.


@pytest.fixture
def chess_launcher() -> Iterator[int]:
    """Launches /System/Applications/Chess.app (D-27). Yields pid.
    Cleanup terminates Chess process."""
    _skip_if_integration_disabled()
    import os as _os
    import signal as _signal
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except ImportError:
        pytest.skip("AppKit (pyobjc) not available")
    subprocess.run(["open", "-a", "Chess"], check=True)
    deadline = time.monotonic() + 5.0
    pid: Optional[int] = None
    while time.monotonic() < deadline:
        ws = NSWorkspace.sharedWorkspace()
        for app in ws.runningApplications():
            if (app.bundleIdentifier() or "") == "com.apple.Chess":
                pid = int(app.processIdentifier())
                break
        if pid is not None:
            break
        time.sleep(0.1)
    if pid is None:
        pytest.skip("Chess.app failed to launch within 5s")
    try:
        yield pid
    finally:
        try:
            _os.kill(pid, _signal.SIGTERM)
        except ProcessLookupError:
            pass


@pytest.fixture
def fake_idempotency_store(tmp_path: Path):
    """In-memory IdempotencyTokenStore wired to a tmp SessionWriter for unit tests.

    Skips with importorskip if Wave-1 idempotency module not yet built."""
    pytest.importorskip("basicctrl.actions.idempotency")
    from basicctrl.actions.idempotency import IdempotencyTokenStore
    from basicctrl.persist.session_writer import SessionWriter
    sw = SessionWriter(base=tmp_path)
    return IdempotencyTokenStore(sw)
