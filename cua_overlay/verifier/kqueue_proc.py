"""KqueueProcObserver — pure asyncio EVFILT_PROC + NOTE_EXIT observer.

Unlike the AX bridge (which needs a dedicated CFRunLoop thread), kqueue is a
plain BSD file descriptor. asyncio's ``loop.add_reader(fd, callback)`` already
provides everything we need — no thread bridging.

This is the "did Calculator quit mid-test?" signal for Phase 1's verifier ladder
and Phase 3's recovery loop. Per VERIFY-02, kqueue + NSWorkspace are the second
push-event tier (after AXObserver).

Why not psutil polling? Polling at 1Hz misses fast-quit races; polling at 10Hz
churns CPU for an event that fires once. EVFILT_PROC + NOTE_EXIT is the right
shape — kernel-event delivery, zero polling.

Threat T-1-06 (LOW) — kqueue fd leak on long sessions. Mitigation:
``__aenter__/__aexit__`` and explicit ``stop()`` close the kqueue fd
deterministically. Tests verify the fd count stays stable across 100
start/stop cycles.
"""
from __future__ import annotations

import asyncio
import select
from typing import Any, Callable, Optional

import structlog


class KqueueProcObserver:
    """Pure-asyncio EVFILT_PROC + NOTE_EXIT observer.

    Lifecycle:
        async with KqueueProcObserver(loop) as kq:
            kq.watch_pid(calculator_pid, on_exit=lambda pid: print(f"{pid} died"))
            # ... do work ...
        # __aexit__ closes the kqueue fd cleanly (T-1-06)

    Or manually:
        kq = KqueueProcObserver(loop)
        kq.start()
        kq.watch_pid(...)
        # ... eventually ...
        kq.stop()
    """

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.loop = loop or asyncio.get_event_loop()
        self._kq: Optional[select.kqueue] = None
        self.kq_fd: Optional[int] = None
        self.callbacks: dict[int, Callable[[int], None]] = {}
        self._log = structlog.get_logger()

    # ---------------------------------------------------------------- context

    async def __aenter__(self) -> "KqueueProcObserver":
        self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.stop()

    # ---------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Open the kqueue fd and register it with the asyncio loop reader."""
        if self._kq is not None:
            return
        self._kq = select.kqueue()
        self.kq_fd = self._kq.fileno()
        self.loop.add_reader(self.kq_fd, self._on_readable)

    def stop(self) -> None:
        """Remove the loop reader and close the kqueue fd (T-1-06 mitigation).

        Idempotent — calling stop() on an already-stopped observer is a no-op.
        """
        if self._kq is None:
            return
        if self.kq_fd is not None:
            try:
                self.loop.remove_reader(self.kq_fd)
            except (RuntimeError, ValueError):
                # Loop already closed — fall through to fd close.
                pass
        self._kq.close()
        self._kq = None
        self.kq_fd = None
        self.callbacks.clear()

    # ---------------------------------------------------------------- watch

    def watch_pid(self, pid: int, on_exit: Callable[[int], None]) -> None:
        """Subscribe NOTE_EXIT for a pid. Callback fires once when pid exits."""
        if self._kq is None:
            raise RuntimeError("KqueueProcObserver not started — call start() or use async with")
        ev = select.kevent(
            ident=pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_ADD | select.KQ_EV_ENABLE,
            fflags=select.KQ_NOTE_EXIT,
        )
        self._kq.control([ev], 0, 0)
        self.callbacks[pid] = on_exit

    def unwatch_pid(self, pid: int) -> None:
        """Stop watching a pid. Safe to call after the pid has already exited."""
        if self._kq is None:
            return
        ev = select.kevent(
            ident=pid,
            filter=select.KQ_FILTER_PROC,
            flags=select.KQ_EV_DELETE,
        )
        try:
            self._kq.control([ev], 0, 0)
        except OSError:
            # Pid already gone (kernel cleaned up the kevent for us). Fine.
            pass
        self.callbacks.pop(pid, None)

    # ---------------------------------------------------------------- internals

    def _on_readable(self) -> None:
        """asyncio reader callback — drain the kqueue and dispatch NOTE_EXIT."""
        if self._kq is None:
            return
        # Non-blocking read up to 16 events. timeout=0 means "what's ready now".
        events = self._kq.control(None, 16, 0)
        for e in events:
            if e.fflags & select.KQ_NOTE_EXIT:
                pid = int(e.ident)
                cb = self.callbacks.pop(pid, None)
                if cb is not None:
                    try:
                        cb(pid)
                    except Exception:  # pragma: no cover — defensive
                        self._log.exception("kqueue.callback_error", pid=pid)
