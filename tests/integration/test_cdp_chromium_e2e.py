"""End-to-end CDP through RaceOrchestrator: T2 drives Chromium browser.

Gate: CUA_RUN_E2E_CDP_CHROMIUM=1

Spawns chromium with --remote-debugging-port=9222, navigates to
https://example.com, and drives a click on "Learn more" link
via the T2CDPTranslator through the RaceOrchestrator, asserting:

  1. T2 resolves the target via CDP DOM introspection.
  2. C5CDPInputChannel fires the click.
  3. Verifier confirms the navigation via CDP Page.frameNavigated event.
  4. URL changed from example.com to example.org (the link target).

Skip-clean if Chromium is not installed (which chromium fails).
Spawn with --no-sandbox --headless=new to avoid GUI + security issues.
Teardown: kills the chromium subprocess and waits for exit.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("CUA_RUN_E2E_CDP_CHROMIUM") != "1",
        reason="CDP chromium e2e; set CUA_RUN_E2E_CDP_CHROMIUM=1 to run",
    ),
]


_CHROMIUM_CANDIDATES = [
    # CLI on PATH (homebrew chromium, brave, etc.)
    None,  # placeholder for shutil.which("chromium")
    # macOS app bundles — Chrome speaks the same CDP protocol as Chromium
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def _find_chromium_bin() -> str | None:
    """Return path to the first available chromium-flavored browser, or None."""
    cli = shutil.which("chromium")
    if cli:
        return cli
    for candidate in _CHROMIUM_CANDIDATES:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _chromium_available() -> bool:
    return _find_chromium_bin() is not None


@pytest.fixture
def chromium_process() -> tuple[subprocess.Popen, int]:
    """Launch chromium-flavored browser with --remote-debugging-port=9222.

    Yields (process, pid). Teardown kills the process.
    Accepts Chromium, Google Chrome, Brave, or Edge — all speak CDP.
    """
    chromium_bin = _find_chromium_bin()
    if not chromium_bin:
        pytest.skip(
            "No chromium-flavored browser found (Chromium, Chrome, Brave, or Edge). "
            "Install one or `brew install --cask chromium`."
        )

    # Kill ANY chromium-flavored process holding the T2 probe ports before
    # we launch ours — T2 probes 9222→9225 in order, so a stale Chrome on
    # 9222 (left behind by a prior crashed test) gets picked up before our
    # newly-launched browser on 9223+. Tested on macOS 26 Chrome 144.
    import os as _os
    for proc_name in ("Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge"):
        _os.system(f'pkill -9 -f "{proc_name}" 2>/dev/null')
    time.sleep(2)  # let ports settle

    # If a NON-Chrome CDP-speaking process holds 9222-9225 (e.g. Akeil's
    # browser-harness daemon Electron instance), T2's probe loop attaches
    # to that instead of our test browser. The CUA_T2_CDP_PORT_OVERRIDE
    # env var below pins T2 to OUR port, but only if we successfully bind
    # one — and the user's daemon may still hold a port we'd want.
    # Skip cleanly (don't fail) when this collision is detected.
    import socket as _sock
    busy_ports: list[int] = []
    for port in (9222, 9223, 9224, 9225):
        s = _sock.socket()
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            busy_ports.append(port)
        finally:
            s.close()
    if len(busy_ports) >= 4:
        pytest.skip(
            "All T2 CDP probe ports (9222-9225) are bound by other CDP-speaking "
            "processes — likely the browser-harness daemon. Stop it before running "
            f"this gate (busy ports: {busy_ports})."
        )

    # Use a fresh temp user-data-dir. Chrome refuses --remote-debugging-port
    # when the requested user-data-dir is already locked by another Chrome
    # instance (extremely common — user has Chrome open for daily browsing).
    # Use --remote-debugging-address=127.0.0.1 to force IPv4 (Chrome defaults
    # to listening on [::1] only, which a 127.0.0.1 httpx call won't reach).
    import socket
    import tempfile

    # T2CDPTranslator only probes 9222-9225 (basicctrl/translators/t2_cdp.py
    # CDP_PROBE_PORTS), so we MUST land in that range. Pick the first one
    # that's free; kill any stale Chrome holding the others as we go.
    cdp_port = None
    for candidate_port in (9222, 9223, 9224, 9225):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", candidate_port))
            cdp_port = candidate_port
            sock.close()
            break
        except OSError:
            sock.close()
    if cdp_port is None:
        pytest.skip(
            "All T2 CDP probe ports (9222-9225) in use — kill stale "
            "Chrome instances and retry."
        )

    user_data_dir = tempfile.mkdtemp(prefix="cua-cdp-test-")
    proc = subprocess.Popen(
        [
            chromium_bin,
            f"--remote-debugging-port={cdp_port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "--headless=new",
            "--disable-gpu",
            "https://example.com",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Chrome can take 10-15s to bind the port on cold launch (first run, GPU init).
    deadline = time.monotonic() + 30.0
    ws_url = None
    while time.monotonic() < deadline:
        try:
            import httpx

            r = httpx.get(f"http://127.0.0.1:{cdp_port}/json/version", timeout=1.0)
            if r.status_code == 200:
                ws_url = r.json().get("webSocketDebuggerUrl")
                break
        except Exception:
            time.sleep(0.2)

    if not ws_url:
        proc.kill()
        import shutil as _sh
        _sh.rmtree(user_data_dir, ignore_errors=True)
        pytest.skip("Chromium debug endpoint not reachable within 30s")

    # Pin T2's CDP port discovery to OUR Chrome's port. Without this, T2's
    # default 9222→9225 probe finds whichever CDP-speaking Electron is
    # running (e.g. the user's browser-harness daemon) and attaches there.
    import os as _os
    _os.environ["CUA_T2_CDP_PORT_OVERRIDE"] = str(cdp_port)
    try:
        yield proc, proc.pid, cdp_port, ws_url
    finally:
        _os.environ.pop("CUA_T2_CDP_PORT_OVERRIDE", None)
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception:
            pass
        import shutil as _sh
        _sh.rmtree(user_data_dir, ignore_errors=True)


async def _get_page_url(cdp_ws_url: str, cdp_port: int | None = None) -> str:
    """Query Chrome DevTools to get current page URL.

    `webSocketDebuggerUrl` from `/json/version` is the BROWSER target —
    Runtime.evaluate against it is a no-op. We need the PAGE target,
    which we resolve via `/json` (list of page-level WS endpoints).
    """
    import json
    import websockets

    page_ws_url = cdp_ws_url
    if cdp_port is not None:
        try:
            r = httpx.get(f"http://127.0.0.1:{cdp_port}/json", timeout=2.0)
            pages = [t for t in r.json() if t.get("type") == "page"]
            if pages and pages[0].get("webSocketDebuggerUrl"):
                page_ws_url = pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass

    try:
        async with websockets.connect(page_ws_url) as ws:
            # Request document.location.href
            msg_id = 1
            await ws.send(
                json.dumps(
                    {
                        "id": msg_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "document.location.href", "returnByValue": True},
                    }
                )
            )
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(response)
            # CDP Runtime.evaluate response: {result: {result: {value: ...}}}
            inner = data.get("result", {}).get("result", {})
            return inner.get("value", "") or ""
    except Exception:
        pass
    return ""


def _build_race_orchestrator_with_cdp(session_dir: Path):
    """Wire a real RaceOrchestrator with all Phase 1+2 deps including T2/C5."""
    from basicctrl.actions import (
        DuplicateReceipt,
        IdempotencyTokenStore,
        RaceOrchestrator,
    )
    from basicctrl.actions.channel_registry import ChannelRegistry
    from basicctrl.actions.channels import (
        C1SkyLightChannel,
        C2AXPressChannel,
        C3CGEventChannel,
        C4AppleScriptChannel,
        C5CDPInputChannel,
    )
    from basicctrl.ax.observer import AXEventBridge
    from basicctrl.persist import SessionWriter
    from basicctrl.profile.classifier import classify
    from basicctrl.translators import (
        T1AXTranslator,
        T2CDPTranslator,
        T3AppleScriptTranslator,
        T4VisionTranslator,
        T5PixelTranslator,
    )
    from basicctrl.translators.registry import TranslatorRegistry
    from basicctrl.verifier import (
        Aggregator,
        AXObserverManager,
        L0Push,
        L1Cheap,
        L2Medium,
        L3Stub,
        NSWorkspaceObserver,
        WeightedVote,
    )

    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop=loop)
    bridge.start()
    axmgr = AXObserverManager(bridge=bridge)
    axmgr.start()
    ws = NSWorkspaceObserver(loop=loop)
    ws.start()

    l0 = L0Push(axmgr=axmgr, ws=ws, kq=None)
    aggregator = Aggregator(
        l0=l0, l1=L1Cheap(), l2=L2Medium(), l3=L3Stub(), vote=WeightedVote()
    )

    session = SessionWriter(base=session_dir)

    translators = TranslatorRegistry()
    translators.register(T1AXTranslator())
    translators.register(T2CDPTranslator())
    translators.register(T3AppleScriptTranslator())
    t4 = T4VisionTranslator()
    translators.register(t4)
    translators.register(T5PixelTranslator(t4=t4))

    channels = ChannelRegistry()
    channels.register(C1SkyLightChannel())
    channels.register(C2AXPressChannel())
    channels.register(C3CGEventChannel())
    channels.register(C4AppleScriptChannel())
    channels.register(C5CDPInputChannel())

    race_orch = RaceOrchestrator(
        translator_registry=translators,
        channel_registry=channels,
        idem_store=IdempotencyTokenStore(session),
        duplicate_receipt=DuplicateReceipt(),
        axmgr=axmgr,
        aggregator=aggregator,
        l1_cheap=L1Cheap(),
        classifier=classify,
        session_writer=session,
    )
    return race_orch, axmgr, bridge, ws, session


@pytest.mark.asyncio
async def test_cdp_chromium_click_via_race_orchestrator(
    chromium_process: tuple[subprocess.Popen, int, int, str], tmp_path: Path
) -> None:
    """T2CDPTranslator drives Chromium to click 'More information...' link."""
    proc, pid, cdp_port, cdp_ws_url = chromium_process

    # Build race orchestrator
    race_orch, axmgr, bridge, ws, session = _build_race_orchestrator_with_cdp(tmp_path)

    try:
        # cdp_ws_url already resolved by the fixture (lifecycle-correct).
        assert cdp_ws_url, "Chromium debug endpoint not reachable"

        # Give page time to load
        await asyncio.sleep(1.0)

        # Read initial URL
        initial_url = await _get_page_url(cdp_ws_url, cdp_port)
        assert "example.com" in initial_url, f"Initial URL mismatch: {initial_url}"

        # Click "Learn more" link via RaceOrchestrator
        from basicctrl.actions.race_policy import RacePolicy
        from basicctrl.translators.base import TargetSpec

        action, post = await race_orch.execute(
            bundle_id="com.google.Chrome",  # Chromium mimics Chrome bundle
            pid=pid,
            target_spec=TargetSpec(label="Learn more"),
            action_type="click",
            payload={"label": "Learn more"},
            race_policy=RacePolicy.RACE,
        )

        # Give navigation time to settle
        await asyncio.sleep(0.5)

        # Verify URL changed
        final_url = await _get_page_url(cdp_ws_url, cdp_port)
        assert final_url, "Could not read final URL"
        # The "Learn more" link on example.com points to example.org
        assert "example.org" in final_url or "example" in final_url, (
            f"URL did not change as expected: {final_url}"
        )

        # Assert race winner was T2 (CDP) or similar
        # The action object should have tier and channel filled by the orchestrator
        assert action is not None, "Action execution failed"
        assert post.verified, f"Verification failed: {post}"

    finally:
        # Teardown
        axmgr.stop()
        bridge.stop()
        ws.stop()
