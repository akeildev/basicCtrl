"""CDPDaemon — long-lived CDP client per (pid, ws_url).

Pattern ported from `~/browser-harness/daemon.py:99-187` per
ULTRAPLAN browser-harness integration §F.

Replaces cua-maximalist's per-fire `async with CDPClient(ws_url) as cdp:`
in T2/C5 with one persistent connection per browser. Saves ~10-20ms
socket handshake per action and unlocks:

  1. **Real-tab attach + omnibox-popup filtering** (`attach_real_page`).
     Browser-harness gotcha P2: chrome://omnibox-popup target appears
     in Target.getTargets but is a 1px hidden frame. Default-attaching
     to it makes every subsequent action invisible.

  2. **Stale-session re-attach**. Catch "Session with given id not
     found" and re-attach to a real page, then retry once. Equivalent
     of daemon.py:184.

  3. **Event tap with bounded deque + dialog detection**. Subscribe to
     CDP events into a 500-entry ring buffer; intercept
     Page.javascriptDialogOpening so callers can `pending_dialog()` and
     handle modal blockers before continuing.

D-03 hard rule preserved: no import of the user's *other* CDP tooling.
This module talks to `cdp_use.client.CDPClient` directly.

D-24 workspace filter: kept in T2; the daemon picks the FIRST real
page when no workspace match (Slack/Cursor/Obsidian have their own
target-picking in T2 because they have multiple legitimate page
targets and we want the workspace renderer specifically).
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any, Optional

import structlog

_log = structlog.get_logger(__name__)

# Internal Chrome targets to filter out of "real page" selection.
_INTERNAL_URL_PREFIXES = (
    "chrome://omnibox-popup",
    "chrome://inspect",
    "chrome-extension://",
    "devtools://",
)

# Bounded event buffer per daemon (browser-harness uses 500).
_EVENT_BUFFER_SIZE = 500

# Idle eviction: close daemons unused for this long.
_IDLE_EVICT_SEC = 60.0


def _is_real_page(t: dict[str, Any]) -> bool:
    """A "real" target is type='page' and not an internal Chrome scheme."""
    if t.get("type") != "page":
        return False
    url = t.get("url", "")
    for prefix in _INTERNAL_URL_PREFIXES:
        if url.startswith(prefix):
            return False
    return True


class CDPDaemon:
    """Per-browser long-lived CDP client.

    Owns one CDPClient + one attached page session + one bounded event
    deque. Exposes a `call(method, params, session_id=...)` that wraps
    cdp.send_raw with stale-session retry.

    Lifecycle:
      d = await CDPDaemon.connect(ws_url, bundle_id, pid)
      await d.call("DOM.getDocument", session_id=d.session_id)
      ...
      await d.close()  # or eviction handles it

    Most callers should use `get_or_create(...)` which caches by
    (pid, ws_url) and returns the same daemon across multiple actions.
    """

    def __init__(
        self,
        ws_url: str,
        bundle_id: str,
        pid: int,
        client_factory: Optional[Any] = None,
    ) -> None:
        self.ws_url = ws_url
        self.bundle_id = bundle_id
        self.pid = pid
        self._client_factory = client_factory
        self._cdp: Any = None
        self.session_id: Optional[str] = None
        self.events: deque[dict[str, Any]] = deque(maxlen=_EVENT_BUFFER_SIZE)
        self.dialog: Optional[dict[str, Any]] = None
        self.last_call_ns: int = time.monotonic_ns()
        self._closed: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    async def connect(
        cls,
        ws_url: str,
        bundle_id: str,
        pid: int,
        client_factory: Optional[Any] = None,
    ) -> "CDPDaemon":
        """Open the CDP socket and attach to a real page. May raise."""
        d = cls(ws_url, bundle_id, pid, client_factory=client_factory)
        await d._open()
        await d._attach_real_page()
        d._install_event_tap()
        return d

    async def _open(self) -> None:
        factory = self._client_factory
        if factory is None:
            from cdp_use.client import CDPClient  # type: ignore[import-not-found]
            factory = CDPClient
        self._cdp = factory(self.ws_url)
        await self._cdp.start()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._cdp is not None:
                await self._cdp.stop()
        except Exception as exc:  # noqa: BLE001
            _log.debug("cdp_daemon.close_error", error=str(exc), pid=self.pid)

    # ------------------------------------------------------------------
    # Page attach (browser-harness daemon.py:111)
    # ------------------------------------------------------------------

    async def _attach_real_page(self, *, target_id: Optional[str] = None) -> bool:
        """Attach to a real page; create about:blank if none exist.

        If `target_id` is provided (e.g. T2's workspace filter picked a
        specific Slack/Cursor target), attach to that exact target
        instead of selecting a real-page candidate.
        """
        if target_id is None:
            res = await self._cdp.send_raw("Target.getTargets")
            targets = res.get("targetInfos", [])
            real = [t for t in targets if _is_real_page(t)]
            if not real:
                created = await self._cdp.send_raw(
                    "Target.createTarget", {"url": "about:blank"}
                )
                target_id = created["targetId"]
                _log.info(
                    "cdp_daemon.created_blank",
                    pid=self.pid,
                    target_id=target_id,
                )
            else:
                target_id = real[0]["targetId"]
        attach = await self._cdp.send_raw(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},  # Pitfall B: flatten mandatory
        )
        self.session_id = attach.get("sessionId")
        if self.session_id is None:
            _log.warning("cdp_daemon.attach_no_session", pid=self.pid, target_id=target_id)
            return False
        # Best-effort domain enables; failures are non-fatal.
        for domain in ("Page", "DOM", "Runtime", "Network"):
            try:
                await asyncio.wait_for(
                    self._cdp.send_raw(f"{domain}.enable", session_id=self.session_id),
                    timeout=3.0,
                )
            except Exception as exc:  # noqa: BLE001
                _log.debug(
                    "cdp_daemon.enable_skip",
                    domain=domain,
                    error=str(exc),
                    pid=self.pid,
                )
        _log.info(
            "cdp_daemon.attached",
            pid=self.pid,
            target_id=target_id,
            session_id=self.session_id,
        )
        return True

    async def reattach_to(self, target_id: str) -> bool:
        """T2 workspace filter calls this when it has picked a specific
        target ID (e.g. the Slack workspace renderer)."""
        return await self._attach_real_page(target_id=target_id)

    # ------------------------------------------------------------------
    # Event tap (browser-harness daemon.py:144)
    # ------------------------------------------------------------------

    def _install_event_tap(self) -> None:
        """Wrap CDPClient's event registry to mirror events into our deque
        and intercept JavaScript dialog open/close."""
        registry = getattr(self._cdp, "_event_registry", None)
        if registry is None or not hasattr(registry, "handle_event"):
            _log.debug("cdp_daemon.no_event_registry", ws_url=self.ws_url)
            return
        orig = registry.handle_event

        async def tap(method: str, params: dict, session_id: Optional[str] = None):
            # ts_ns lets L1Cheap.run filter events that arrived AFTER its
            # pre-snapshot baseline (browser-harness §I1 verifier signal).
            self.events.append(
                {
                    "method": method,
                    "params": params,
                    "session_id": session_id,
                    "ts_ns": time.monotonic_ns(),
                }
            )
            if method == "Page.javascriptDialogOpening":
                self.dialog = params
            elif method == "Page.javascriptDialogClosed":
                self.dialog = None
            return await orig(method, params, session_id)

        registry.handle_event = tap

    def drain_events(self) -> list[dict[str, Any]]:
        """Pop and return all buffered events (browser-harness pattern)."""
        out = list(self.events)
        self.events.clear()
        return out

    def pending_dialog(self) -> Optional[dict[str, Any]]:
        """Return the open JS dialog (alert/confirm/prompt/beforeunload) or None."""
        return self.dialog

    # ------------------------------------------------------------------
    # Call wrapper with stale-session retry (browser-harness daemon.py:179)
    # ------------------------------------------------------------------

    async def call(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
        retry_stale: bool = True,
    ) -> dict[str, Any]:
        """Wrap cdp.send_raw with browser-level vs session routing + stale retry.

        Browser-level Target.* calls don't use a session. Other calls use
        the explicit session_id arg, falling back to self.session_id.
        On 'Session with given id not found', re-attach to a real page
        and retry once.
        """
        self.last_call_ns = time.monotonic_ns()
        sid = None if method.startswith("Target.") else (session_id or self.session_id)
        try:
            return await self._cdp.send_raw(method, params, session_id=sid)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if (
                retry_stale
                and "Session with given id not found" in msg
                and sid == self.session_id
                and sid is not None
            ):
                _log.info(
                    "cdp_daemon.stale_session_reattach",
                    pid=self.pid,
                    stale_session=sid,
                )
                if await self._attach_real_page():
                    return await self._cdp.send_raw(
                        method, params, session_id=self.session_id
                    )
            raise


# ----------------------------------------------------------------------
# Module-level cache: one daemon per (pid, ws_url)
# ----------------------------------------------------------------------

_DAEMONS: dict[tuple[int, str], CDPDaemon] = {}
_LOCK = asyncio.Lock()
_EVICTION_TASK: Optional[asyncio.Task] = None


async def get_or_create(
    pid: int,
    ws_url: str,
    bundle_id: str,
    *,
    client_factory: Optional[Any] = None,
) -> CDPDaemon:
    """Return cached daemon for (pid, ws_url) or open a new one.

    Thread-/coroutine-safe under asyncio: holds a module lock during
    creation so concurrent callers share a single daemon.
    """
    key = (pid, ws_url)
    async with _LOCK:
        existing = _DAEMONS.get(key)
        if existing is not None and not existing._closed:
            existing.last_call_ns = time.monotonic_ns()
            return existing
        d = await CDPDaemon.connect(
            ws_url=ws_url, bundle_id=bundle_id, pid=pid, client_factory=client_factory
        )
        _DAEMONS[key] = d
        _start_idle_eviction()
        return d


def _start_idle_eviction() -> None:
    """Background loop that closes daemons idle for >_IDLE_EVICT_SEC."""
    global _EVICTION_TASK
    if _EVICTION_TASK is not None and not _EVICTION_TASK.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _EVICTION_TASK = loop.create_task(_eviction_loop())


async def _eviction_loop() -> None:
    while True:
        await asyncio.sleep(30.0)
        now_ns = time.monotonic_ns()
        threshold_ns = now_ns - int(_IDLE_EVICT_SEC * 1e9)
        async with _LOCK:
            stale = [
                key for key, d in _DAEMONS.items()
                if d.last_call_ns < threshold_ns
            ]
            for key in stale:
                d = _DAEMONS.pop(key, None)
                if d is not None:
                    try:
                        await d.close()
                    except Exception as exc:  # noqa: BLE001
                        _log.debug("cdp_daemon.evict_close_error", error=str(exc))
                    _log.debug("cdp_daemon.evicted_idle", pid=key[0])


async def close_all() -> None:
    """Test/teardown helper: close every cached daemon."""
    async with _LOCK:
        daemons = list(_DAEMONS.values())
        _DAEMONS.clear()
    for d in daemons:
        try:
            await d.close()
        except Exception:  # noqa: BLE001
            pass


def find_for_pid(pid: int) -> Optional[CDPDaemon]:
    """Lookup helper for verifiers that need to peek at CDP events.

    Returns the first cached daemon attached to `pid`, or None. Used by
    L1Cheap's `l1.cdp_event_changed` sub-check (browser-harness §I1):
    when an action fired against a CDP-controlled app, the verifier can
    check the daemon's event buffer for Page.frameNavigated /
    Page.loadEventFired / DOM mutations as a *second* deterministic
    success signal beyond AX push events (which Chrome doesn't fire).
    """
    for (cached_pid, _ws), daemon in _DAEMONS.items():
        if cached_pid == pid and not daemon._closed:
            return daemon
    return None
