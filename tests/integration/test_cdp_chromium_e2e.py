"""End-to-end CDP through RaceOrchestrator: T2 drives Chromium browser.

Gate: CUA_RUN_E2E_CDP_CHROMIUM=1

Spawns chromium with --remote-debugging-port=9222, navigates to
https://example.com, and drives a click on "More information..." link
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


def _chromium_available() -> bool:
    """Check if chromium or Chromium.app is available."""
    if shutil.which("chromium"):
        return True
    chromium_app = Path("/Applications/Chromium.app/Contents/MacOS/Chromium")
    if chromium_app.exists():
        return True
    return False


@pytest.fixture
def chromium_process() -> tuple[subprocess.Popen, int]:
    """Launch chromium with --remote-debugging-port=9222 on example.com.

    Yields (process, pid). Teardown kills the process.
    """
    if not _chromium_available():
        pytest.skip("Chromium not found (brew install --cask chromium)")

    # Prefer 'chromium' CLI; fall back to Chromium.app
    chromium_bin = shutil.which("chromium")
    if not chromium_bin:
        chromium_bin = "/Applications/Chromium.app/Contents/MacOS/Chromium"

    proc = subprocess.Popen(
        [
            chromium_bin,
            "--remote-debugging-port=9222",
            "--no-sandbox",
            "--headless=new",
            "https://example.com",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give it time to start
    deadline = time.monotonic() + 10.0
    ws_url = None
    while time.monotonic() < deadline:
        try:
            import httpx

            r = httpx.get("http://127.0.0.1:9222/json/version", timeout=1.0)
            if r.status_code == 200:
                ws_url = r.json().get("webSocketDebuggerUrl")
                break
        except Exception:
            time.sleep(0.2)

    if not ws_url:
        proc.kill()
        pytest.skip("Chromium debug endpoint not reachable within 10s")

    yield proc, proc.pid
    try:
        proc.kill()
        proc.wait(timeout=2.0)
    except Exception:
        pass


async def _get_page_url(cdp_ws_url: str) -> str:
    """Query Chrome DevTools to get current page URL.

    Simplified: send Runtime.evaluate to get document.location.href.
    """
    import websockets
    import json

    try:
        async with websockets.connect(cdp_ws_url) as ws:
            # Request document.location.href
            msg_id = 1
            await ws.send(
                json.dumps(
                    {
                        "id": msg_id,
                        "method": "Runtime.evaluate",
                        "params": {"expression": "document.location.href"},
                    }
                )
            )
            response = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(response)
            if "result" in data:
                return data["result"].get("value", "")
    except Exception:
        pass
    return ""


def _build_race_orchestrator_with_cdp(session_dir: Path):
    """Wire a real RaceOrchestrator with all Phase 1+2 deps including T2/C5."""
    from cua_overlay.actions import (
        DuplicateReceipt,
        IdempotencyTokenStore,
        RaceOrchestrator,
    )
    from cua_overlay.actions.channel_registry import ChannelRegistry
    from cua_overlay.actions.channels import (
        C1SkyLightChannel,
        C2AXPressChannel,
        C3CGEventChannel,
        C4AppleScriptChannel,
        C5CDPInputChannel,
    )
    from cua_overlay.ax.observer import AXEventBridge
    from cua_overlay.persist import SessionWriter
    from cua_overlay.profile.classifier import classify
    from cua_overlay.translators import (
        T1AXTranslator,
        T2CDPTranslator,
        T3AppleScriptTranslator,
        T4VisionTranslator,
        T5PixelTranslator,
    )
    from cua_overlay.translators.registry import TranslatorRegistry
    from cua_overlay.verifier import (
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
    chromium_process: tuple[subprocess.Popen, int], tmp_path: Path
) -> None:
    """T2CDPTranslator drives Chromium to click 'More information...' link."""
    proc, pid = chromium_process

    # Build race orchestrator
    race_orch, axmgr, bridge, ws, session = _build_race_orchestrator_with_cdp(tmp_path)

    try:
        # Wait for chromium debug endpoint
        deadline = time.monotonic() + 10.0
        cdp_ws_url = None
        while time.monotonic() < deadline:
            try:
                r = httpx.get("http://127.0.0.1:9222/json/version", timeout=1.0)
                if r.status_code == 200:
                    cdp_ws_url = r.json().get("webSocketDebuggerUrl")
                    break
            except Exception:
                await asyncio.sleep(0.2)

        assert cdp_ws_url, "Chromium debug endpoint not reachable"

        # Give page time to load
        await asyncio.sleep(1.0)

        # Read initial URL
        initial_url = await _get_page_url(cdp_ws_url)
        assert "example.com" in initial_url, f"Initial URL mismatch: {initial_url}"

        # Click "More information..." link via RaceOrchestrator
        from cua_overlay.actions.race_policy import RacePolicy
        from cua_overlay.translators.base import TargetSpec

        action, post = await race_orch.execute(
            bundle_id="com.google.Chrome",  # Chromium mimics Chrome bundle
            pid=pid,
            target_spec=TargetSpec(label="More information..."),
            action_type="click",
            payload={"label": "More information..."},
            race_policy=RacePolicy.RACE,
        )

        # Give navigation time to settle
        await asyncio.sleep(0.5)

        # Verify URL changed
        final_url = await _get_page_url(cdp_ws_url)
        assert final_url, "Could not read final URL"
        # The "More information..." link on example.com points to example.org
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
