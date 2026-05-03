"""TRANS-03 / T-2-03 — T3 AppleScript translator unit tests.

Per CONTEXT.md D-04: T3 uses py-applescript 1.0.3 (in-process NSAppleScript via
PyObjC OSAKit) on a dedicated `concurrent.futures.ThreadPoolExecutor(
max_workers=2, thread_name_prefix='cua-as')`. NEVER osascript subprocess.

Per RESEARCH.md §"Pattern 6" + Pitfall E (compiled-script cache mandatory —
recompile costs 50-200ms, defeats the racing budget).

T-2-03 mitigation: NSAppleScript on a detached background thread can hang
waiting for AppleEvent reply (`macOS26-Agent/Conversation.swift:245-248`).
The dedicated ThreadPoolExecutor isolates AS calls from the main asyncio
loop AND caps concurrency at 2.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from basicctrl.translators.base import TargetSpec
from basicctrl.translators.t3_applescript import (
    T3AppleScriptTranslator,
    _compiled_cache,
)


def test_tier_is_T3() -> None:
    """T3AppleScriptTranslator declares tier='T3' (Translator Protocol contract)."""
    t = T3AppleScriptTranslator()
    try:
        assert t.tier == "T3"
    finally:
        t.shutdown()


def test_executor_is_dedicated_pool() -> None:
    """T-2-03: dedicated ThreadPoolExecutor with max_workers=2 + thread_name_prefix='cua-as'."""
    t = T3AppleScriptTranslator()
    try:
        # ThreadPoolExecutor exposes _max_workers (private but stable API).
        assert t._exec._max_workers == 2  # noqa: SLF001
        # Submit a no-op task; check thread name carries prefix.
        captured: dict[str, str] = {}

        def _capture() -> None:
            captured["name"] = threading.current_thread().name

        fut = t._exec.submit(_capture)
        fut.result(timeout=2.0)
        assert "cua-as" in captured["name"], (
            f"thread name missing 'cua-as' prefix: {captured['name']}"
        )
    finally:
        t.shutdown()


def test_build_target_spec_pages_d26_verb() -> None:
    """_build_target_spec wraps as_verb in 'tell application "Pages" to ...' for iWork bundle."""
    t = T3AppleScriptTranslator()
    try:
        spec = TargetSpec(
            as_verb='make new paragraph style with properties {name:"BoldTest"}'
        )
        wrapped = t._build_target_spec("com.apple.iWork.Pages", spec)
        assert wrapped == (
            'tell application "Pages" to '
            'make new paragraph style with properties {name:"BoldTest"}'
        )
    finally:
        t.shutdown()


@pytest.mark.asyncio
async def test_resolve_returns_synthetic_target_with_as_spec() -> None:
    """resolve() returns synthetic TranslatorTarget with as_target_spec set;
    element fields are placeholder (T3 doesn't resolve via AX tree walk)."""
    t = T3AppleScriptTranslator()
    try:
        target = await t.resolve(
            "com.apple.iWork.Pages",
            1234,
            TargetSpec(as_verb="activate", label="Pages"),
        )
        assert target is not None
        assert target.as_target_spec is not None
        assert "Pages" in target.as_target_spec
        assert "activate" in target.as_target_spec
    finally:
        t.shutdown()


@pytest.mark.asyncio
async def test_execute_caches_compiled_script() -> None:
    """Pitfall E: second execute() call with same source does NOT recompile."""
    _compiled_cache.clear()
    t = T3AppleScriptTranslator()
    construct_count = 0

    class _FakeScript:
        def __init__(self, source: str) -> None:
            nonlocal construct_count
            construct_count += 1

        def run(self, *args, **kwargs):
            return "ok"

    fake_module = SimpleNamespace(AppleScript=_FakeScript, ScriptError=Exception)
    try:
        with patch.dict("sys.modules", {"applescript": fake_module}):
            r1 = await t.execute('tell application "Pages" to activate')
            r2 = await t.execute('tell application "Pages" to activate')
        assert r1 == ("ok", None)
        assert r2 == ("ok", None)
        assert construct_count == 1, (
            f"expected single compile, got {construct_count}"
        )
    finally:
        t.shutdown()
        _compiled_cache.clear()


@pytest.mark.asyncio
async def test_execute_catches_runtime_error() -> None:
    """Errors caught and returned as (empty, msg) tuple — never escape."""
    _compiled_cache.clear()
    t = T3AppleScriptTranslator()

    class _BadScript:
        def __init__(self, source: str) -> None:  # noqa: D401
            ...

        def run(self, *args, **kwargs):
            raise RuntimeError("AppleEvent timeout")

    fake_module = SimpleNamespace(AppleScript=_BadScript, ScriptError=Exception)
    try:
        with patch.dict("sys.modules", {"applescript": fake_module}):
            result, err = await t.execute('tell application "Pages" to crash')
        assert result == ""
        assert err is not None
        assert "AppleEvent timeout" in err
    finally:
        t.shutdown()
        _compiled_cache.clear()


@pytest.mark.asyncio
async def test_execute_runs_on_dedicated_executor() -> None:
    """T-2-03: AS execute thread name carries 'cua-as' prefix
    (proves NOT default asyncio thread pool)."""
    _compiled_cache.clear()
    t = T3AppleScriptTranslator()

    captured_thread: dict[str, str] = {}

    class _ThreadCaptureScript:
        def __init__(self, source: str) -> None:  # noqa: D401
            ...

        def run(self, *args, **kwargs):
            captured_thread["name"] = threading.current_thread().name
            return "ok"

    fake_module = SimpleNamespace(
        AppleScript=_ThreadCaptureScript, ScriptError=Exception
    )
    try:
        with patch.dict("sys.modules", {"applescript": fake_module}):
            await t.execute('tell application "Pages" to activate')
        assert "cua-as" in captured_thread.get("name", ""), (
            f"AS ran on wrong thread: {captured_thread.get('name')!r} "
            f"— should be on dedicated cua-as pool, not asyncio default executor"
        )
    finally:
        t.shutdown()
        _compiled_cache.clear()
