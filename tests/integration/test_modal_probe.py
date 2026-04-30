"""Integration + mock-driven tests for modal probe + AXUIElementWrapper.

Pitfall P25 (modal alert blocks AX) mitigation tests.

Tests 1, 4 are real-macOS integration tests (require Calculator + TCC). Tests
2, 3, 5, 6, 7 use mocks so they run on any host.
"""
from __future__ import annotations

import time
from typing import Any

import pytest

from cua_overlay.ax import element as element_module
from cua_overlay.ax import modal_probe as modal_probe_module
from cua_overlay.ax.element import AXUIElementWrapper, _CACHE_TTL_SECONDS
from cua_overlay.ax.modal_probe import _MAX_WINDOWS_TO_CHECK, has_blocking_modal
from cua_overlay.ax.rate_limit import TokenBucket


# ---------------------------------------------------------------------------
# Mock AX hierarchy for unit-style modal_probe tests.
# ---------------------------------------------------------------------------


class MockWindow:
    """In-memory stand-in for a top-level AX window."""

    def __init__(self, title: str = "win", is_modal: bool = False) -> None:
        self.title = title
        self.is_modal = is_modal

    def attr(self, name: str) -> Any:
        if name == "AXModal":
            return self.is_modal
        if name == "AXTitle":
            return self.title
        if name == "AXPosition":
            return (0.0, 0.0)
        if name == "AXSize":
            return (100.0, 100.0)
        return None


class MockApp:
    """In-memory stand-in for an AXApplication root."""

    def __init__(self, windows: list[MockWindow]) -> None:
        self.windows = windows

    def attr(self, name: str) -> Any:
        if name == "AXWindows":
            return self.windows
        return None


@pytest.fixture
def mock_app_factory(monkeypatch: pytest.MonkeyPatch):
    """Patch HIServices + walker._read_attr so modal_probe runs on a MockApp."""

    def factory(windows: list[MockWindow]) -> MockApp:
        app = MockApp(windows)

        # Make `from HIServices import AXUIElementCreateApplication` return a
        # callable that yields our MockApp. Patching the local import inside
        # has_blocking_modal is brittle; instead, monkey-patch
        # asyncio.to_thread to short-circuit the AXUIElementCreateApplication
        # call and return our MockApp.
        import asyncio as _asyncio

        original_to_thread = _asyncio.to_thread

        async def fake_to_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
            # If the caller is invoking AXUIElementCreateApplication, return
            # our MockApp. Otherwise defer to the real implementation.
            name = getattr(func, "__name__", "")
            if name == "AXUIElementCreateApplication":
                return app
            return await original_to_thread(func, *args, **kwargs)

        monkeypatch.setattr(_asyncio, "to_thread", fake_to_thread)

        # Patch _read_attr inside modal_probe module so reads against our mock
        # objects come from .attr().
        async def fake_read(ax_elem: Any, attribute: str) -> Any:
            if isinstance(ax_elem, (MockApp, MockWindow)):
                return ax_elem.attr(attribute)
            return None

        monkeypatch.setattr(modal_probe_module, "_read_attr", fake_read)
        return app

    return factory


# ---------------------------------------------------------------------------
# Modal probe tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_returns_none_for_calculator_no_modal(calculator_pid: int) -> None:
    """With Calculator running and no modal up, has_blocking_modal returns None.

    This requires real macOS Calculator + Accessibility TCC granted to the
    Python interpreter. SKIP_INTEGRATION=1 short-circuits via the fixture.
    """
    result = await has_blocking_modal(calculator_pid, bundle_id="com.apple.Calculator")
    assert result is None


@pytest.mark.asyncio
async def test_caps_window_check_at_10(mock_app_factory) -> None:  # type: ignore[no-untyped-def]
    """A mocked app with 50 windows still only checks the first 10."""
    windows = [MockWindow(title=f"w{i}", is_modal=False) for i in range(50)]
    mock_app_factory(windows)
    # Track AXModal reads to confirm exactly 10 windows were probed.
    modal_reads: list[int] = []
    original_attr = MockWindow.attr

    def counting_attr(self: MockWindow, name: str) -> Any:
        if name == "AXModal":
            modal_reads.append(id(self))
        return original_attr(self, name)

    MockWindow.attr = counting_attr  # type: ignore[method-assign]
    try:
        result = await has_blocking_modal(
            pid=12345,
            bundle_id="test",
            bucket=TokenBucket(rate_per_sec=1000.0, capacity=1000),
        )
    finally:
        MockWindow.attr = original_attr  # type: ignore[method-assign]
    assert result is None
    assert len(modal_reads) <= _MAX_WINDOWS_TO_CHECK
    # We probed at least 10 (caller capped at 10, walker doesn't short-circuit).
    assert len(modal_reads) == _MAX_WINDOWS_TO_CHECK


@pytest.mark.asyncio
async def test_returns_uielement_when_modal_present(mock_app_factory) -> None:  # type: ignore[no-untyped-def]
    """With AXModal=True on window[2], has_blocking_modal returns a UIElement."""
    windows = [
        MockWindow(title="main", is_modal=False),
        MockWindow(title="palette", is_modal=False),
        MockWindow(title="alert", is_modal=True),
    ]
    mock_app_factory(windows)
    result = await has_blocking_modal(
        pid=12345,
        bundle_id="test",
        bucket=TokenBucket(rate_per_sec=1000.0, capacity=1000),
    )
    assert result is not None
    assert "AXWindow[modal]" in result.role_path
    assert result.role == "AXWindow"
    assert result.label == "alert"


@pytest.mark.manual
@pytest.mark.skip(reason="manual-only — see 01-VALIDATION.md")
def test_marked_manual_for_real_modal() -> None:
    """Manual: open System Settings password prompt, confirm probe sees modal.

    Run instructions:
      1. Launch System Settings → Privacy & Security → Touch ID & Password.
      2. Click "Change Password..." (a modal sheet appears).
      3. Get the Settings pid: `pgrep -f "System Settings"`.
      4. ``await has_blocking_modal(pid)`` should return a UIElement with
         role_path containing "AXWindow[modal]".
    """
    raise AssertionError("manual run only")


@pytest.mark.asyncio
async def test_uses_rate_limit_bucket(mock_app_factory) -> None:  # type: ignore[no-untyped-def]
    """Probe gates each window-attribute read on TokenBucket.acquire."""
    windows = [MockWindow(title=f"w{i}", is_modal=False) for i in range(5)]
    mock_app_factory(windows)

    bucket = TokenBucket(rate_per_sec=1000.0, capacity=1000)
    call_count = [0]
    real_acquire = bucket.acquire

    async def counting_acquire(pid: int) -> bool:
        call_count[0] += 1
        return await real_acquire(pid)

    bucket.acquire = counting_acquire  # type: ignore[method-assign]
    await has_blocking_modal(pid=12345, bundle_id="test", bucket=bucket)
    # At least: 1 for AXWindows + 5 for AXModal reads = 6 acquires.
    assert call_count[0] >= 6


# ---------------------------------------------------------------------------
# AXUIElementWrapper cache tests (no real AX needed — patch the sync read).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_axuielementwrapper_caches_reads_100ms(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calling read_attribute twice within 100ms = only 1 underlying AX call."""
    real_read_count = [0]

    async def fake_to_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_read_count[0] += 1
        return "the-value"

    monkeypatch.setattr(element_module.asyncio, "to_thread", fake_to_thread)

    wrapper = AXUIElementWrapper(
        ax_element=object(),
        pid=42,
        bundle_id="test",
        bucket=TokenBucket(rate_per_sec=1000.0, capacity=1000),
    )

    v1 = await wrapper.read_attribute("AXValue")
    v2 = await wrapper.read_attribute("AXValue")
    assert v1 == v2 == "the-value"
    assert real_read_count[0] == 1


@pytest.mark.asyncio
async def test_axuielementwrapper_re_reads_after_100ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After the cache TTL expires, the next read makes a fresh AX call."""
    real_read_count = [0]

    async def fake_to_thread(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        real_read_count[0] += 1
        return f"value-{real_read_count[0]}"

    monkeypatch.setattr(element_module.asyncio, "to_thread", fake_to_thread)

    # Freeze the wrapper's clock so we control TTL deterministically.
    frozen = [10000.0]
    monkeypatch.setattr(element_module.time, "monotonic", lambda: frozen[0])

    wrapper = AXUIElementWrapper(
        ax_element=object(),
        pid=42,
        bundle_id="test",
        bucket=TokenBucket(rate_per_sec=1000.0, capacity=1000),
    )

    v1 = await wrapper.read_attribute("AXValue")
    # Advance past the cache TTL.
    frozen[0] += _CACHE_TTL_SECONDS + 0.01
    v2 = await wrapper.read_attribute("AXValue")
    assert v1 == "value-1"
    assert v2 == "value-2"
    assert real_read_count[0] == 2
