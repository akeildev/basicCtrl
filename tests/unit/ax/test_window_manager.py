"""window_manager unit tests — translation of browser-harness ensure_real_tab.

Pin the contract:
  - list_real_windows filters minimized + hidden
  - ensure_real_window returns focused window when present, else first real
  - retry_on_stale_ax retries once on AXCannotCompleteError, then bubbles
  - retry_on_stale_ax does NOT retry on other AX errors (e.g. invalid element)
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cua_overlay.ax.errors import (
    AXCannotCompleteError,
    AXError,
    kAXErrorCannotComplete,
    kAXErrorInvalidUIElement,
)
from cua_overlay.ax import window_manager


# ─── helpers: stub out the HIServices module ────────────────────────────────


def _stub_hi_services(windows_response, focused_response=None, attr_responses=None):
    """Patch _hi_services_attrs to return controllable callables.

    `windows_response` is what AXUIElementCopyAttributeValue returns when
    asked for "AXWindows": (err, value).
    `attr_responses`: dict mapping attribute name -> (err, value) for
    per-window attribute reads (AXMinimized, AXHidden).
    """
    attr_responses = attr_responses or {}

    def fake_create(pid):
        return SimpleNamespace(pid=pid, kind="ax_app")

    def fake_copy_attr(elem, attr, _placeholder):
        if attr == "AXWindows":
            return windows_response
        if attr == "AXFocusedWindow":
            return focused_response if focused_response is not None else (0, None)
        return attr_responses.get(attr, (0, None))

    fake_module = MagicMock()
    return patch.object(
        window_manager,
        "_hi_services_attrs",
        return_value=(fake_create, fake_copy_attr, fake_module),
    )


# ─── list_real_windows ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_real_windows_filters_minimized():
    """A window with AXMinimized=True must be excluded."""
    w_normal = SimpleNamespace(name="normal")
    w_min = SimpleNamespace(name="minimized")
    attrs = {}

    def fake_copy_attr(elem, attr, _):
        if attr == "AXWindows":
            return (0, [w_normal, w_min])
        if attr == "AXMinimized":
            return (0, elem is w_min)
        if attr == "AXHidden":
            return (0, False)
        return (0, None)

    with patch.object(
        window_manager,
        "_hi_services_attrs",
        return_value=(lambda pid: object(), fake_copy_attr, MagicMock()),
    ):
        real = await window_manager.list_real_windows(123)
    assert w_normal in real
    assert w_min not in real


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_real_windows_filters_hidden():
    w_normal = SimpleNamespace(name="normal")
    w_hidden = SimpleNamespace(name="hidden")

    def fake_copy_attr(elem, attr, _):
        if attr == "AXWindows":
            return (0, [w_normal, w_hidden])
        if attr == "AXMinimized":
            return (0, False)
        if attr == "AXHidden":
            return (0, elem is w_hidden)
        return (0, None)

    with patch.object(
        window_manager,
        "_hi_services_attrs",
        return_value=(lambda pid: object(), fake_copy_attr, MagicMock()),
    ):
        real = await window_manager.list_real_windows(123)
    assert real == [w_normal]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_real_windows_empty_on_no_windows():
    """No windows yet → empty list, no exception."""

    def fake_copy_attr(elem, attr, _):
        if attr == "AXWindows":
            return (0, None)
        return (0, None)

    with patch.object(
        window_manager,
        "_hi_services_attrs",
        return_value=(lambda pid: object(), fake_copy_attr, MagicMock()),
    ):
        real = await window_manager.list_real_windows(999)
    assert real == []


# ─── ensure_real_window ─────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_real_window_returns_focused_when_present():
    """When AXFocusedWindow is set, prefer it over arbitrary first real window."""
    w_first = SimpleNamespace(name="first")
    w_focused = SimpleNamespace(name="focused")

    def fake_copy_attr(elem, attr, _):
        if attr == "AXWindows":
            return (0, [w_first, w_focused])
        if attr == "AXFocusedWindow":
            return (0, w_focused)
        if attr == "AXMinimized":
            return (0, False)
        if attr == "AXHidden":
            return (0, False)
        return (0, None)

    with patch.object(
        window_manager,
        "_hi_services_attrs",
        return_value=(lambda pid: object(), fake_copy_attr, MagicMock()),
    ), patch.object(window_manager, "_activate_if_needed", new=AsyncMock()):
        win = await window_manager.ensure_real_window(123)
    assert win is w_focused


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_real_window_falls_back_to_first_when_no_focus():
    w_first = SimpleNamespace(name="first")
    w_other = SimpleNamespace(name="other")

    def fake_copy_attr(elem, attr, _):
        if attr == "AXWindows":
            return (0, [w_first, w_other])
        if attr == "AXFocusedWindow":
            return (0, None)
        if attr == "AXMinimized":
            return (0, False)
        if attr == "AXHidden":
            return (0, False)
        return (0, None)

    with patch.object(
        window_manager,
        "_hi_services_attrs",
        return_value=(lambda pid: object(), fake_copy_attr, MagicMock()),
    ), patch.object(window_manager, "_activate_if_needed", new=AsyncMock()):
        win = await window_manager.ensure_real_window(123)
    assert win is w_first


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ensure_real_window_returns_none_when_no_real_windows():
    def fake_copy_attr(elem, attr, _):
        if attr == "AXWindows":
            return (0, [])
        return (0, None)

    with patch.object(
        window_manager,
        "_hi_services_attrs",
        return_value=(lambda pid: object(), fake_copy_attr, MagicMock()),
    ):
        win = await window_manager.ensure_real_window(123, activate_if_not_frontmost=False)
    assert win is None


# ─── retry_on_stale_ax ──────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_on_stale_ax_retries_once_then_succeeds():
    calls = {"n": 0}

    async def fn():
        calls["n"] += 1
        if calls["n"] == 1:
            raise AXCannotCompleteError("stale", code=kAXErrorCannotComplete)
        return "ok"

    on_retry = AsyncMock()
    result = await window_manager.retry_on_stale_ax(fn, on_retry=on_retry)
    assert result == "ok"
    assert calls["n"] == 2
    on_retry.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_on_stale_ax_bubbles_after_limit():
    """Two consecutive AXCannotComplete with limit=1 → second one bubbles."""

    async def fn():
        raise AXCannotCompleteError("still stale", code=kAXErrorCannotComplete)

    with pytest.raises(AXCannotCompleteError):
        await window_manager.retry_on_stale_ax(fn, limit=1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_on_stale_ax_does_not_retry_on_invalid_element():
    """Other AX errors must NOT trigger retry — they're hard failures."""

    async def fn():
        raise AXError("invalid handle", code=kAXErrorInvalidUIElement)

    on_retry = AsyncMock()
    with pytest.raises(AXError):
        await window_manager.retry_on_stale_ax(fn, on_retry=on_retry)
    on_retry.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_on_stale_ax_no_retry_on_clean_call():
    async def fn():
        return 42

    on_retry = AsyncMock()
    result = await window_manager.retry_on_stale_ax(fn, on_retry=on_retry)
    assert result == 42
    on_retry.assert_not_awaited()
