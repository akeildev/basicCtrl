"""as_daemon resilience tests — translation of browser-harness's
async-with-timeout + retry-on-stale pattern for AppleScript.

Pin the contract:
  - Successful first attempt returns immediately
  - Transient AppleEvent codes (-1712, -1708, -609, -10000) trigger
    exactly one retry
  - Non-transient errors do NOT retry
  - asyncio.TimeoutError converts to ("", "ae_timeout: <s>")
  - Second timeout is final (no third attempt)
"""
from __future__ import annotations

import asyncio
from typing import Optional, Tuple

import pytest

from cua_overlay.translators.as_daemon import (
    _extract_ae_error_code,
    run_with_resilience,
)


@pytest.mark.unit
def test_extract_ae_error_code_handles_common_formats():
    assert _extract_ae_error_code("runtime_error: error number -1712") == -1712
    assert _extract_ae_error_code(
        "<NSAppleScriptErrorMessage>boom</NSAppleScriptErrorMessage>"
        "<NSAppleScriptErrorNumber>-609</NSAppleScriptErrorNumber>"
    ) == -609
    assert _extract_ae_error_code("plain string with no code") is None
    assert _extract_ae_error_code("") is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_success_returns_immediately_no_retry():
    calls = {"n": 0}

    async def fn() -> Tuple[str, Optional[str]]:
        calls["n"] += 1
        return ("ok", None)

    result = await run_with_resilience(fn)
    assert result == ("ok", None)
    assert calls["n"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transient_ae_error_retries_once_then_succeeds():
    calls = {"n": 0}

    async def fn() -> Tuple[str, Optional[str]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return ("", "runtime_error: error number -1712")
        return ("recovered", None)

    result = await run_with_resilience(fn)
    assert result == ("recovered", None)
    assert calls["n"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_transient_ae_error_retries_once_then_bubbles():
    """Two consecutive -1712 — second one returned without a third try."""
    calls = {"n": 0}

    async def fn() -> Tuple[str, Optional[str]]:
        calls["n"] += 1
        return ("", "runtime_error: error number -1712")

    result = await run_with_resilience(fn)
    assert result[0] == ""
    assert "-1712" in (result[1] or "")
    assert calls["n"] == 2  # exactly one retry


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_transient_error_does_not_retry():
    """A compile error or arbitrary runtime error must NOT retry."""
    calls = {"n": 0}

    async def fn() -> Tuple[str, Optional[str]]:
        calls["n"] += 1
        return ("", "compile_error: syntax error")

    result = await run_with_resilience(fn)
    assert result == ("", "compile_error: syntax error")
    assert calls["n"] == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_converted_to_ae_timeout_error():
    async def fn() -> Tuple[str, Optional[str]]:
        await asyncio.sleep(2.0)
        return ("never", None)

    result = await run_with_resilience(fn, timeout_sec=0.05, retry_on_transient=False)
    assert result[0] == ""
    assert result[1] is not None and "ae_timeout" in result[1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_disabled_skips_retry():
    calls = {"n": 0}

    async def fn() -> Tuple[str, Optional[str]]:
        calls["n"] += 1
        return ("", "runtime_error: error number -1712")

    result = await run_with_resilience(fn, retry_on_transient=False)
    assert calls["n"] == 1
    assert "-1712" in (result[1] or "")
