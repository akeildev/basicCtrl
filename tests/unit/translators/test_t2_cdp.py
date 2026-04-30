"""TRANS-02 / D-24 — T2 CDP translator unit tests with mocked CDP.

Wave-2 plan 02-06: T2CDPTranslator uses cdp-use 1.4.5 (D-02), MUST NOT
import browser-harness (D-03), implements D-24 workspace-renderer filter
(Pitfall D), and uses Pitfall B's mandatory ``flatten=True`` on attach.

These tests use mocks for the CDP surface so they run on any host (no
Slack relaunch, no port 9222 dependency). Real Slack integration lives
in tests/integration/test_slack_t2_wins.py (Plan 02-12).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cua_overlay.translators.t2_cdp import T2CDPTranslator


def test_tier_is_T2() -> None:
    assert T2CDPTranslator().tier == "T2"


def test_pick_slack_workspace_skips_gpu_helper() -> None:
    """D-24 / Pitfall D — Slack workspace renderer is `type=page` AND
    url contains `.slack.com`. GPU/utility helpers must be skipped."""
    t = T2CDPTranslator()
    targets = [
        {"type": "page", "url": "chrome://gpu", "targetId": "gpu-1"},
        {"type": "other", "url": "", "targetId": "util-1"},
        {"type": "page", "url": "https://app.slack.com/client/T123/D456", "targetId": "ws-1"},
    ]
    chosen = t._pick_workspace_target(targets, "com.tinyspeck.slackmacgap")
    assert chosen is not None
    assert chosen["targetId"] == "ws-1"


def test_pick_slack_returns_none_when_no_workspace() -> None:
    """P8 mitigation — if Slack hasn't been relaunched with --remote-debugging-port
    OR the workspace renderer hasn't loaded yet, no target matches; return None."""
    t = T2CDPTranslator()
    targets = [
        {"type": "page", "url": "chrome://gpu", "targetId": "gpu-1"},
        {"type": "other", "url": "", "targetId": "util-1"},
    ]
    assert t._pick_workspace_target(targets, "com.tinyspeck.slackmacgap") is None


def test_pick_cursor_workspace_by_vscode_prefix() -> None:
    t = T2CDPTranslator()
    targets = [
        {"type": "page", "url": "chrome://gpu", "targetId": "gpu-1"},
        {"type": "page", "url": "vscode-webview://abc/index.html", "targetId": "ws-1"},
    ]
    chosen = t._pick_workspace_target(targets, "com.todesktop.230313mzl4w4u92")
    assert chosen is not None
    assert chosen["targetId"] == "ws-1"


def test_pick_obsidian_workspace_by_url_substring() -> None:
    t = T2CDPTranslator()
    targets = [
        {"type": "page", "url": "app://obsidian.md/index.html", "targetId": "ws-1"},
    ]
    chosen = t._pick_workspace_target(targets, "md.obsidian")
    assert chosen is not None
    assert chosen["targetId"] == "ws-1"


def test_pick_default_picks_first_page() -> None:
    """Bundle-id-unknown apps fall through to first `type=page` target."""
    t = T2CDPTranslator()
    targets = [
        {"type": "other", "url": "", "targetId": "util-1"},
        {"type": "page", "url": "https://example.com/", "targetId": "page-1"},
    ]
    chosen = t._pick_workspace_target(targets, "com.unknown.app")
    assert chosen is not None
    assert chosen["targetId"] == "page-1"


def test_no_browser_harness_import() -> None:
    """D-03 hard rule — module source contains no browser_harness reference.

    cua-maximalist must coexist with browser-harness (Akeil uses both daily);
    neither owns the other; both call cdp-use directly.
    """
    src_path = Path(__file__).parents[3] / "cua_overlay" / "translators" / "t2_cdp.py"
    src = src_path.read_text()
    assert "browser_harness" not in src, "D-03: cua-maximalist must not import browser_harness"
    assert "import browser_harness" not in src
    assert "from browser_harness" not in src


@pytest.mark.asyncio
async def test_discover_ws_url_returns_none_on_all_ports_unreachable(monkeypatch) -> None:
    """When localhost:9222..9225 all refuse, _discover_ws_url returns None
    (P8 mitigation — caller's resolve() returns None and orchestrator falls
    through to T1/T4/T5)."""
    t = T2CDPTranslator()

    class _BadClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise OSError("connect refused")

    monkeypatch.setattr("cua_overlay.translators.t2_cdp.httpx.AsyncClient", _BadClient)
    assert await t._discover_ws_url(1234) is None


@pytest.mark.asyncio
async def test_discover_ws_url_returns_first_reachable(monkeypatch) -> None:
    """200 OK on /json/version → return webSocketDebuggerUrl."""
    t = T2CDPTranslator()

    class _Resp:
        status_code = 200
        def json(self): return {"webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/abc"}

    class _GoodClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _Resp()

    monkeypatch.setattr("cua_overlay.translators.t2_cdp.httpx.AsyncClient", _GoodClient)
    url = await t._discover_ws_url(1234)
    assert url == "ws://localhost:9222/devtools/browser/abc"
