"""AppleScript resilience helpers — translation of browser-harness's
"async with timeout + stale retry" daemon pattern.

T3 already does the **compiled-script cache** part of browser-harness's
daemon (module-level `_compiled_cache` in `t3_applescript.py`, Pitfall E).
What was missing is the AppleEvent equivalent of:

  - browser-harness `daemon.start_async`: `asyncio.wait_for(..., timeout=5)`
    so a stalled target app's AppleEvent listener doesn't hang the racing
    budget (T-2-03)
  - browser-harness `daemon.handle`: catch "Session with given id not
    found" and re-attach + retry once. The AppleScript analogue is
    AppleEvent error -1712 ("AppleEvent handler failed" / timeout) or
    -609 ("connection invalid"); the recovery is a re-launch + retry.

`run_with_resilience` wraps any AS executor call with both protections.
T3.execute uses it so every fire is bounded + auto-recovers from one
transient AppleEvent failure.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Optional, Tuple

import structlog


_log = structlog.get_logger(__name__)


# AppleEvent error codes that we treat as "transient — retry once."
# -1712: AppleEvent timeout (target app's handler didn't respond in time)
# -1708: event not handled by recipient (often because app just launched)
# -609:  connection invalid (target restarted between calls)
# -10000: AppleScript general error — sometimes transient on first launch
_TRANSIENT_AE_ERRORS: frozenset[int] = frozenset({-1712, -1708, -609, -10000})

# Default AS-fire budget. Browser-harness uses 5s; AS is slower than CDP
# (especially first-launch warmup) so we go a bit higher.
_DEFAULT_TIMEOUT_SEC: float = 8.0


def _extract_ae_error_code(error_str: str) -> Optional[int]:
    """Pull the integer AppleEvent error code from a py-applescript error string.

    py-applescript surfaces errors in formats like:
      "runtime_error: error number -1712"
      "runtime_error: <NSAppleScriptErrorMessage>...<NSAppleScriptErrorNumber>-1712"

    Returns None if no code can be parsed.
    """
    if not error_str:
        return None
    for marker in ("error number ", "ErrorNumber>", "NSAppleScriptErrorNumber>"):
        idx = error_str.find(marker)
        if idx == -1:
            continue
        tail = error_str[idx + len(marker):]
        # Read the leading integer (with optional sign) from `tail`.
        end = 0
        if end < len(tail) and tail[end] in "+-":
            end += 1
        while end < len(tail) and tail[end].isdigit():
            end += 1
        if end == 0:
            continue
        try:
            return int(tail[:end])
        except ValueError:
            continue
    return None


async def run_with_resilience(
    fn: Callable[[], Awaitable[Tuple[str, Optional[str]]]],
    *,
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    retry_on_transient: bool = True,
) -> Tuple[str, Optional[str]]:
    """Run an AppleScript fire with timeout + one transient retry.

    Args:
      fn: a no-arg coroutine that returns (result_str, error_str_or_None)
          (matches T3AppleScriptTranslator.execute's return shape).
      timeout_sec: per-attempt budget. asyncio.TimeoutError is converted
          to ("", "ae_timeout: <Ns>") so the channel contract holds (no
          raises across the boundary).
      retry_on_transient: if True and the first attempt returned a
          transient AppleEvent error, retry once. Mirrors browser-harness
          daemon.py:184 (one stale-session re-attach + retry).

    Returns the final (result, error) tuple. Never raises.
    """
    # Attempt 1.
    try:
        result = await asyncio.wait_for(fn(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        _log.warning("as_daemon.timeout", attempt=1, budget_sec=timeout_sec)
        result = ("", f"ae_timeout: {timeout_sec}s")

    res, err = result
    if err is None:
        return result

    # Decide whether to retry.
    if not retry_on_transient:
        return result
    code = _extract_ae_error_code(err)
    if code is None or code not in _TRANSIENT_AE_ERRORS:
        return result

    _log.info(
        "as_daemon.retry_on_transient",
        ae_code=code,
        first_error=err[:200],
    )
    # Attempt 2.
    try:
        result = await asyncio.wait_for(fn(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        _log.warning("as_daemon.timeout", attempt=2, budget_sec=timeout_sec)
        return ("", f"ae_timeout: {timeout_sec}s")
    return result
