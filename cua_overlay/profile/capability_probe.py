"""Per-capability probes for the AppProfile classifier.

Each probe runs in `asyncio.to_thread` so the asyncio loop is never blocked
by a synchronous PyObjC call. The classifier (Plan 01-02 Task 2) wraps each
probe in `asyncio.wait_for(..., timeout=0.2)` so a single hung probe never
blocks the total budget for >500ms (success criterion).

Probes are fail-open: any exception or timeout returns the safe default
(usually False / None) — never raises out to the classifier.

Hard rules per CLAUDE.md:
- Never poll AX at >20 calls/sec/pid. Probes here run ONCE per session per
  bundle, gated by the disk cache, so we are well under that ceiling. The
  TokenBucket from Plan 01-03 is the runtime guard.
- Never run a full recursive AX walk. We only read AXChildren on the app
  element (depth = 1).
"""

from __future__ import annotations

import asyncio
import plistlib
from pathlib import Path
from typing import Optional


async def probe_bundle_metadata(bundle_id: str) -> dict:
    """Resolve the bundle's filesystem path + version + build via NSWorkspace.

    Returns a dict with keys: bundle_path, bundle_version, bundle_build, info_plist.
    Sync work runs in a thread (~5ms total).
    """

    def _sync() -> dict:
        try:
            from AppKit import NSWorkspace  # type: ignore[import-not-found]
        except ImportError:
            return {
                "bundle_path": None,
                "bundle_version": None,
                "bundle_build": None,
                "info_plist": {},
            }

        url = NSWorkspace.sharedWorkspace().URLForApplicationWithBundleIdentifier_(bundle_id)
        if url is None:
            return {
                "bundle_path": None,
                "bundle_version": None,
                "bundle_build": None,
                "info_plist": {},
            }
        bundle_path = url.path()
        plist_path = Path(bundle_path) / "Contents" / "Info.plist"
        info: dict = {}
        if plist_path.exists():
            try:
                info = plistlib.loads(plist_path.read_bytes())
            except Exception:
                info = {}
        return {
            "bundle_path": bundle_path,
            "bundle_version": info.get("CFBundleShortVersionString"),
            "bundle_build": info.get("CFBundleVersion"),
            "info_plist": info,
        }

    return await asyncio.to_thread(_sync)


async def probe_ax_rich(pid: int) -> bool:
    """Return True iff the app exposes >0 AX children within 200ms.

    Reads exactly one AX attribute (AXChildren) on the application element.
    Depth = 1 — no recursive walk (CLAUDE.md hard rule).
    """

    def _sync() -> bool:
        try:
            from HIServices import (  # type: ignore[import-not-found]
                AXUIElementCopyAttributeValue,
                AXUIElementCreateApplication,
                kAXChildrenAttribute,
            )
        except ImportError:
            return False
        try:
            app = AXUIElementCreateApplication(pid)
            err, children = AXUIElementCopyAttributeValue(app, kAXChildrenAttribute, None)
            if err != 0 or children is None:
                return False
            return len(children) > 0
        except Exception:
            return False

    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=0.2)
    except (asyncio.TimeoutError, Exception):
        return False


async def probe_ax_observer_works(pid: int) -> bool:
    """Return True iff AXObserver subscribes successfully (Pitfall 14 detector).

    Phase 1 minimal probe: attempt to create an observer + add a notification
    subscription on a benign AXFocusedUIElement watch. If the subscribe call
    returns kAXErrorNotificationUnsupported (or any error), the app does not
    surface AX notifications — Pitfall 14. We do NOT wait for an actual fire
    here (that requires a real action and a CFRunLoop) — Plan 01-04 builds
    the full bridge. The "subscribe succeeds" signal is enough for the
    routing decision.

    Capped at 500ms; fail-open False on timeout / any exception.
    """

    def _sync() -> bool:
        try:
            from HIServices import (  # type: ignore[import-not-found]
                AXObserverAddNotification,
                AXObserverCreate,
                AXUIElementCreateApplication,
                kAXFocusedUIElementChangedNotification,
            )
        except ImportError:
            return False

        try:
            app = AXUIElementCreateApplication(pid)
            # AXObserverCreate signature: (pid, callback, &observer)
            # PyObjC returns (error, observer)
            def _noop_callback(observer, element, notification, refcon):  # pragma: no cover
                return None

            err, observer = AXObserverCreate(pid, _noop_callback, None)
            if err != 0 or observer is None:
                return False
            # Try subscribing. kAXErrorNotificationUnsupported (-25204) on web/Electron.
            sub_err = AXObserverAddNotification(
                observer, app, kAXFocusedUIElementChangedNotification, None
            )
            return sub_err == 0
        except Exception:
            return False

    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=0.5)
    except (asyncio.TimeoutError, Exception):
        return False


async def probe_cdp_ports(pid: int) -> Optional[int]:
    """Probe localhost:9222..9230 for a CDP /json/version endpoint.

    Returns the first responding port or None. Each port poll has a 100ms
    timeout. Total budget bounded by 9 ports × 100ms = 900ms WORST case;
    classifier wraps the whole probe in 200ms so a fully-deaf system bails
    fast.
    """
    try:
        import httpx  # type: ignore[import-not-found]
    except ImportError:
        return None

    async with httpx.AsyncClient(timeout=0.1) as client:
        for port in range(9222, 9231):
            try:
                r = await client.get(f"http://localhost:{port}/json/version")
                if r.status_code == 200:
                    return port
            except Exception:
                continue
    return None


def probe_applescript_sdef(info_plist: dict) -> bool:
    """Return True iff the bundle's Info.plist declares AppleScript scripting."""
    if info_plist.get("OSAScriptingDefinition") is not None:
        return True
    if info_plist.get("NSAppleScriptEnabled") is True:
        return True
    return False


def probe_electron(bundle_path: Optional[str]) -> bool:
    """Return True iff the bundle ships Electron Framework.framework."""
    if not bundle_path:
        return False
    return (Path(bundle_path) / "Contents" / "Frameworks" / "Electron Framework.framework").exists()


def probe_tauri_or_wails(bundle_path: Optional[str], info_plist: dict) -> bool:
    """[ASSUMED A2] Heuristic: WebKit.framework linked + no .sdef + not Electron.

    Phase 1 spike. If wrong, mis-classifies Tauri as native AppKit. Mitigation:
    classifier emits a structlog warning when this fires so we can audit on
    real samples.
    """
    if not bundle_path:
        return False
    if probe_electron(bundle_path):
        return False
    if probe_applescript_sdef(info_plist):
        return False
    return (Path(bundle_path) / "Contents" / "Frameworks" / "WebKit.framework").exists()
