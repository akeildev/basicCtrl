"""CDPDaemon unit tests — browser-harness §F port.

Pin the contract that browser-harness's daemon.py upholds:
  - One client per (pid, ws_url) — `get_or_create` is idempotent
  - `attach_real_page` filters chrome://omnibox-popup + creates about:blank
    when no real pages exist
  - `Target.*` calls bypass the session_id (browser-level)
  - Stale-session error triggers re-attach + retry once
  - Event tap appends to bounded deque + intercepts dialog open/close
"""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any
from unittest.mock import MagicMock

import pytest

from basicctrl.translators import cdp_daemon
from basicctrl.translators.cdp_daemon import CDPDaemon, get_or_create


# ─── fake CDPClient ─────────────────────────────────────────────────────────


class FakeRegistry:
    def __init__(self):
        async def handle_event(method, params, session_id=None):
            return None
        self.handle_event = handle_event


class FakeCDP:
    """Records method+params per send_raw call. Programmable per-method response."""

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self.calls: list[tuple[str, dict, str | None]] = []
        self._event_registry = FakeRegistry()
        # Default canned responses that get_or_create needs at attach time.
        self.responses: dict[str, Any] = {
            "Target.getTargets": {
                "targetInfos": [
                    {"type": "page", "url": "https://example.com", "targetId": "real-1"},
                    {"type": "page", "url": "chrome://omnibox-popup/", "targetId": "popup"},
                ]
            },
            "Target.attachToTarget": {"sessionId": "sess-1"},
            "Target.createTarget": {"targetId": "blank-1"},
        }
        self.fail_next: list[tuple[str, str]] = []  # [(method, error_msg), ...]
        self.start_called = 0
        self.stop_called = 0

    async def start(self):
        self.start_called += 1

    async def stop(self):
        self.stop_called += 1

    async def send_raw(self, method, params=None, session_id=None):
        self.calls.append((method, params or {}, session_id))
        for i, (m, msg) in enumerate(self.fail_next):
            if m == method:
                self.fail_next.pop(i)
                raise RuntimeError(msg)
        if method in self.responses:
            return self.responses[method]
        if method.endswith(".enable"):
            return {}
        return {}


@pytest.fixture(autouse=True)
async def _reset_cache():
    yield
    await cdp_daemon.close_all()


# ─── tests ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_or_create_returns_same_daemon_per_key():
    """One daemon per (pid, ws_url). Concurrent callers share."""
    a = await get_or_create(pid=1, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    b = await get_or_create(pid=1, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    c = await get_or_create(pid=2, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    assert a is b, "same key must reuse the daemon"
    assert a is not c, "different pid must yield a new daemon"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attach_filters_omnibox_popup_and_picks_real_page():
    """Default attach must skip chrome://omnibox-popup and land on a real page."""
    d = await get_or_create(pid=1, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    # Look at attach call params — should be the real targetId, not the popup
    attach_calls = [c for c in d._cdp.calls if c[0] == "Target.attachToTarget"]
    assert attach_calls, "expected an attach call during connect()"
    assert attach_calls[0][1]["targetId"] == "real-1"
    assert attach_calls[0][1]["flatten"] is True  # Pitfall B mandatory
    assert d.session_id == "sess-1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_attach_creates_about_blank_when_no_real_pages():
    """If only internal targets exist, daemon creates about:blank."""

    class NoRealPages(FakeCDP):
        def __init__(self, ws_url):
            super().__init__(ws_url)
            self.responses["Target.getTargets"] = {
                "targetInfos": [
                    {"type": "page", "url": "chrome://omnibox-popup/", "targetId": "popup"},
                    {"type": "page", "url": "devtools://devtools/x", "targetId": "dt"},
                ]
            }

    d = await get_or_create(pid=10, ws_url="ws://x", bundle_id="b", client_factory=NoRealPages)
    create = [c for c in d._cdp.calls if c[0] == "Target.createTarget"]
    assert create, "expected Target.createTarget when no real pages"
    assert create[0][1]["url"] == "about:blank"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_routes_target_calls_with_no_session():
    """Target.* must NOT carry a session_id — they are browser-level."""
    d = await get_or_create(pid=20, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    d._cdp.calls.clear()
    await d.call("Target.getTargets")
    assert d._cdp.calls[0] == ("Target.getTargets", {}, None)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_routes_session_calls_with_default_session():
    """Non-Target calls inherit the daemon's attached session."""
    d = await get_or_create(pid=30, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    d._cdp.calls.clear()
    await d.call("DOM.getDocument")
    assert d._cdp.calls[0] == ("DOM.getDocument", {}, "sess-1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stale_session_triggers_reattach_and_retry():
    """browser-harness daemon.py:184 — on stale-session error, re-attach + retry."""
    d = await get_or_create(pid=40, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    d._cdp.calls.clear()
    # First DOM.getDocument fails as stale; second succeeds.
    d._cdp.fail_next.append(("DOM.getDocument", "Session with given id not found: sess-1"))
    result = await d.call("DOM.getDocument")
    # Expect: 1 failed call + Target.getTargets + Target.attachToTarget (re-attach)
    # + .enable calls + 1 successful retry of DOM.getDocument.
    methods = [c[0] for c in d._cdp.calls]
    assert "DOM.getDocument" in methods
    assert "Target.attachToTarget" in methods
    assert methods.count("DOM.getDocument") == 2  # initial fail + successful retry
    assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_call_propagates_non_stale_errors():
    """Errors that aren't stale-session must NOT trigger re-attach."""
    d = await get_or_create(pid=50, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    d._cdp.calls.clear()
    d._cdp.fail_next.append(("DOM.getDocument", "Cannot find DOM root"))
    with pytest.raises(RuntimeError, match="Cannot find DOM root"):
        await d.call("DOM.getDocument")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_event_tap_appends_to_deque_and_tracks_dialog():
    """Event tap mirrors CDP events into the bounded deque + intercepts dialogs."""
    d = await get_or_create(pid=60, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    # Simulate an event arrival via the wrapped registry handler.
    handler = d._cdp._event_registry.handle_event
    await handler("Page.loadEventFired", {}, "sess-1")
    await handler(
        "Page.javascriptDialogOpening", {"type": "alert", "message": "Hi"}, "sess-1"
    )
    assert any(e["method"] == "Page.loadEventFired" for e in d.events)
    assert d.pending_dialog() == {"type": "alert", "message": "Hi"}
    await handler("Page.javascriptDialogClosed", {}, "sess-1")
    assert d.pending_dialog() is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_close_all_evicts_cached_daemons():
    a = await get_or_create(pid=70, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    assert a._cdp.start_called == 1
    await cdp_daemon.close_all()
    assert a._cdp.stop_called == 1
    # Subsequent get_or_create returns a fresh daemon instance.
    b = await get_or_create(pid=70, ws_url="ws://x", bundle_id="b", client_factory=FakeCDP)
    assert b is not a
