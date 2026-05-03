"""Integration tests for KqueueProcObserver.

These tests need a real macOS kernel + Calculator.app + the asyncio loop.
They're marked ``@pytest.mark.integration`` and skipped under
``SKIP_INTEGRATION=1`` (orchestrator parallel mode) via the ``calculator_pid``
fixture's environment check.

Test 3 (no fd leak) verifies T-1-06 mitigation — 100 start/stop cycles must
not grow the process's open-file count.
"""
from __future__ import annotations

import asyncio
import os
import resource
import signal

import pytest

from basicctrl.verifier.kqueue_proc import KqueueProcObserver


@pytest.mark.integration
@pytest.mark.asyncio
async def test_app_exit(calculator_pid: int) -> None:
    """NOTE_EXIT fires within 2s when Calculator quits."""
    loop = asyncio.get_running_loop()
    fired_pid: list[int] = []
    done = asyncio.Event()

    def _on_exit(pid: int) -> None:
        fired_pid.append(pid)
        loop.call_soon_threadsafe(done.set)

    async with KqueueProcObserver(loop) as kq:
        kq.watch_pid(calculator_pid, on_exit=_on_exit)

        # Quit Calculator. Use SIGTERM (graceful) — fixture's teardown also
        # SIGTERMs, but kqueue NOTE_EXIT fires for any exit reason.
        os.kill(calculator_pid, signal.SIGTERM)

        try:
            await asyncio.wait_for(done.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pytest.fail("kqueue NOTE_EXIT did not fire within 2s of SIGTERM")

    assert fired_pid == [calculator_pid]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_fd_leak() -> None:
    """T-1-06: 100 start/stop cycles must not leak fds.

    We measure soft-rlimit headroom indirectly: open + close 100 kqueues, then
    open one more — if we leaked, eventually we'd hit EMFILE. Stronger check:
    count open fds before/after via /dev/fd listing on macOS.
    """
    loop = asyncio.get_running_loop()

    def _count_fds() -> int:
        # On macOS /dev/fd lists open file descriptors of the calling process.
        try:
            return len(os.listdir("/dev/fd"))
        except OSError:
            return -1

    before = _count_fds()
    if before < 0:
        pytest.skip("/dev/fd not readable on this system")

    for _ in range(100):
        kq = KqueueProcObserver(loop)
        kq.start()
        kq.stop()

    after = _count_fds()
    # Allow up to 2 fds of slack (test framework, asyncio internals may grow
    # slightly). Anything bigger means we're leaking.
    assert (after - before) <= 2, f"fd leak: before={before}, after={after}"

    # Sanity: rlimit nofile didn't shrink.
    rlim = resource.getrlimit(resource.RLIMIT_NOFILE)
    assert rlim[0] >= 256


@pytest.mark.integration
@pytest.mark.asyncio
async def test_unwatch_pid_does_not_leak() -> None:
    """watch_pid + unwatch_pid in a tight loop must not grow fd count."""
    loop = asyncio.get_running_loop()

    def _count_fds() -> int:
        try:
            return len(os.listdir("/dev/fd"))
        except OSError:
            return -1

    async with KqueueProcObserver(loop) as kq:
        before = _count_fds()
        if before < 0:
            pytest.skip("/dev/fd not readable on this system")
        # Use our own pid — we never exit, so NOTE_EXIT never fires.
        my_pid = os.getpid()
        for _ in range(100):
            kq.watch_pid(my_pid, on_exit=lambda _p: None)
            kq.unwatch_pid(my_pid)
        after = _count_fds()
        assert (after - before) <= 1, f"fd leak: before={before}, after={after}"
