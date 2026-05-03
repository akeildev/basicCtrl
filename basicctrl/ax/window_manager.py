"""AX window manager — translation of browser-harness's `ensure_real_tab()`.

Browser-harness §3 (deep-study) — `daemon.attach_first_page()` filters
out chrome://omnibox-popup and creates about:blank when no real pages
exist. The cua-maximalist analogue for native macOS apps:

  - Filter out minimized / hidden windows that look attached but won't
    receive AX events
  - Auto-activate the app's main window when the requested PID isn't
    frontmost (else clicks land on whoever IS frontmost)
  - Retry once on `kAXErrorCannotComplete` (the AX equivalent of a
    "Session with given id not found" stale-CDP error) by re-creating
    the AXUIElement handle and asking again

This module is deliberately additive — T1 calls these helpers when it
wants the safety net, but the existing T1 flow keeps working without
them. Skill files (e.g. `skills/com.apple.calculator/arithmetic.md`)
note when an app needs ensure_real_window() pre-action.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Optional, TypeVar

import structlog

from cua_overlay.ax.errors import (
    AXCannotCompleteError,
    AXError,
    kAXErrorCannotComplete,
)


_log = structlog.get_logger(__name__)
_T = TypeVar("_T")

# How long ensure_real_window will wait for the activated app to actually
# become frontmost before giving up. macOS Dock animation + Mission Control
# can briefly hide the activation; 1.5s is browser-harness-style "polling
# bounded by timeout" (SKILL.md §6).
_ACTIVATION_TIMEOUT_SEC: float = 1.5
_ACTIVATION_POLL_INTERVAL_SEC: float = 0.05

# How many times retry_on_stale_ax retries on AXCannotComplete before bubbling.
# browser-harness re-attaches once on stale-session; we mirror that.
_STALE_RETRY_LIMIT: int = 1


def _hi_services_attrs() -> tuple[Any, Any, Any]:
    """Lazy-import (AXUIElementCreateApplication, AXUIElementCopyAttributeValue,
    constants module). Raises ImportError on non-macOS."""
    try:
        from HIServices import (  # type: ignore[import-not-found]
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
        )
    except ImportError:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
        )
    import HIServices  # type: ignore[import-not-found]
    return AXUIElementCreateApplication, AXUIElementCopyAttributeValue, HIServices


def _is_window_attached(window_ref: Any, copy_attr: Any) -> bool:
    """Return True if the AXWindow is visible to the user (not minimized,
    not hidden behind another window). Conservative: any error reading
    the attribute is treated as 'not attached'."""
    try:
        err, minimized = copy_attr(window_ref, "AXMinimized", None)
        if err == 0 and minimized:
            return False
    except Exception:  # noqa: BLE001
        pass
    try:
        err, hidden = copy_attr(window_ref, "AXHidden", None)
        if err == 0 and hidden:
            return False
    except Exception:  # noqa: BLE001
        pass
    return True


async def list_real_windows(pid: int) -> list[Any]:
    """Enumerate visible (not minimized/hidden) AXWindow refs for `pid`.

    Returns [] when AX is unavailable or the app has no windows yet.
    Equivalent of browser-harness `[t for t in targets if is_real_page(t)]`.
    """
    try:
        AXUIElementCreateApplication, AXUIElementCopyAttributeValue, _ = _hi_services_attrs()
    except ImportError:
        return []
    ax_app = await asyncio.to_thread(AXUIElementCreateApplication, pid)
    try:
        err, windows = await asyncio.to_thread(
            AXUIElementCopyAttributeValue, ax_app, "AXWindows", None
        )
    except Exception as exc:  # noqa: BLE001
        _log.debug("window_manager.list_failed", pid=pid, error=str(exc))
        return []
    if err != 0 or windows is None:
        return []
    real: list[Any] = []
    for w in windows:
        if _is_window_attached(w, AXUIElementCopyAttributeValue):
            real.append(w)
    return real


async def ensure_real_window(pid: int, *, activate_if_not_frontmost: bool = True) -> Optional[Any]:
    """Return a usable AXWindow ref for `pid`, activating the app if needed.

    Behavior:
      1. Enumerate real (not minimized / hidden) windows.
      2. If none, return None — caller should treat as "app has no UI yet".
      3. If `activate_if_not_frontmost` and the app isn't frontmost, call
         NSRunningApplication.activateWithOptions_ to bring it forward.
         Poll until activation completes or timeout.
      4. Return the focused window if available, else the first real window.

    Returns None when the app has no real windows (caller falls through
    to whatever the orchestrator does on T1.resolve()=None).
    """
    real = await list_real_windows(pid)
    if not real:
        _log.info("window_manager.no_real_windows", pid=pid)
        return None

    if activate_if_not_frontmost:
        await _activate_if_needed(pid)

    # Prefer focused window when set; falls back to first real window.
    focused = await _get_focused_window(pid)
    if focused is not None:
        return focused
    return real[0]


async def _get_focused_window(pid: int) -> Optional[Any]:
    """Return the AXWindow currently marked AXFocusedWindow, or None."""
    try:
        AXUIElementCreateApplication, AXUIElementCopyAttributeValue, _ = _hi_services_attrs()
    except ImportError:
        return None
    ax_app = await asyncio.to_thread(AXUIElementCreateApplication, pid)
    try:
        err, focused = await asyncio.to_thread(
            AXUIElementCopyAttributeValue, ax_app, "AXFocusedWindow", None
        )
        if err == 0 and focused is not None:
            return focused
    except Exception:  # noqa: BLE001
        pass
    return None


async def _activate_if_needed(pid: int) -> None:
    """Use NSRunningApplication.activateWithOptions_ to make `pid` frontmost.

    Polls NSWorkspace.activeApplication until activation completes or the
    timeout fires. Bounded so the verifier loop never hangs.
    """
    try:
        from AppKit import (  # type: ignore[import-not-found]
            NSRunningApplication,
            NSApplicationActivateAllWindows,
            NSApplicationActivateIgnoringOtherApps,
        )
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
    except ImportError:
        return
    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is None or app.isActive():
        return
    options = (
        NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps
    )
    app.activateWithOptions_(options)
    deadline = time.monotonic() + _ACTIVATION_TIMEOUT_SEC
    workspace = NSWorkspace.sharedWorkspace()
    while time.monotonic() < deadline:
        active = workspace.activeApplication()
        if active and int(active.get("NSApplicationProcessIdentifier", -1)) == pid:
            return
        await asyncio.sleep(_ACTIVATION_POLL_INTERVAL_SEC)
    _log.debug("window_manager.activation_timeout", pid=pid)


async def retry_on_stale_ax(
    fn: Callable[[], Awaitable[_T]],
    *,
    on_retry: Optional[Callable[[], Awaitable[None]]] = None,
    limit: int = _STALE_RETRY_LIMIT,
) -> _T:
    """Run `fn`. On `AXCannotCompleteError` (-25204), invoke optional
    `on_retry` (e.g. re-create AXUIElement) and retry up to `limit` times.

    Equivalent of browser-harness daemon.py:184 — catch stale-session,
    re-attach, retry once. AX -25204 is the AX-equivalent: the underlying
    element handle went stale (window closed, app process restarted, AX
    main-thread saturated).
    """
    attempts = 0
    while True:
        try:
            return await fn()
        except AXCannotCompleteError as exc:
            if attempts >= limit:
                raise
            attempts += 1
            _log.info(
                "window_manager.stale_ax_retry",
                attempt=attempts,
                code=exc.code,
            )
            if on_retry is not None:
                await on_retry()
        except AXError as exc:
            # Other AX errors (-25202 invalid element, -25211 API disabled)
            # are not retry-able — bubble immediately.
            if exc.code == kAXErrorCannotComplete:
                if attempts >= limit:
                    raise
                attempts += 1
                if on_retry is not None:
                    await on_retry()
                continue
            raise
