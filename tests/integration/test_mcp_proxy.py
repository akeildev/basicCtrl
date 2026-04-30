"""Integration tests for the Python MCP proxy (Plan 01-08).

Per Plan 01-08 Task 3: end-to-end MCP proxy verification.

* ``test_list_tools`` — spawn the proxy as a subprocess; connect via
  stdio_client; ``list_tools`` must include both ``click_with_healing``
  AND at least one upstream tool name.
* ``test_screenshot_passthrough`` — call an upstream non-action tool
  through the proxy; verify it returns content.
* ``test_healing_tool_callable`` — launch Calculator, call
  ``click_with_healing`` on the "5" button via the proxy, verify the
  return shape.
* ``test_action_log_written`` — verify the per-session action_log.ndjson
  has at least one valid JSON line after the click.

Requires ``cua-driver mcp`` on PATH or via ``CUA_DRIVER_BIN`` env var.
Build with::

    cd libs/cua-driver && swift build -c release

Tests skip cleanly with a clear message when ``cua-driver`` is unavailable
(``CUA_DRIVER_BIN`` unset and ``cua-driver`` not on PATH) or when
``SKIP_INTEGRATION=1`` is set.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import AsyncIterator, Optional

import pytest

pytestmark = pytest.mark.integration


# --------------------------------------------------------------------------- helpers


def _resolve_cua_driver() -> Optional[str]:
    """Return the cua-driver binary path, or ``None`` if not found.

    Honours ``CUA_DRIVER_BIN`` first; falls back to ``shutil.which("cua-driver")``.
    Tests skip when ``None``.
    """
    explicit = os.environ.get("CUA_DRIVER_BIN")
    if explicit:
        if Path(explicit).exists():
            return explicit
        return None
    return shutil.which("cua-driver")


def _skip_if_no_cua_driver() -> None:
    """pytest-skip if the cua-driver binary is not available."""
    if _resolve_cua_driver() is None:
        pytest.skip(
            "cua-driver not on PATH and CUA_DRIVER_BIN unset — "
            "build with `cd libs/cua-driver && swift build -c release` "
            "then re-run with that path on PATH or set CUA_DRIVER_BIN."
        )


@pytest.fixture
def cua_driver_available() -> str:
    """Skip the test if cua-driver is unavailable; otherwise return its path.

    Defined as a fixture (not a plain function call) so pytest evaluates it
    BEFORE other fixtures (e.g. ``calculator_pid``) that the test also
    depends on. Tests that combine ``cua_driver_available`` with
    ``calculator_pid`` skip cleanly when the driver is missing rather than
    erroring out trying to launch Calculator.
    """
    path = _resolve_cua_driver()
    if path is None:
        pytest.skip(
            "cua-driver not on PATH and CUA_DRIVER_BIN unset — "
            "build with `cd libs/cua-driver && swift build -c release` "
            "then re-run with that path on PATH or set CUA_DRIVER_BIN."
        )
    return path


async def _spawn_proxy_session() -> AsyncIterator:  # type: ignore[type-arg]
    """Async-generator helper: spawn the proxy + yield an initialised ClientSession.

    Each test gets its own subprocess + session; we never share state between
    tests (each click uses a fresh ``SessionWriter`` UUID).
    """
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cua_overlay.mcp_server"],
        env=None,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


# --------------------------------------------------------------------------- Test 1


@pytest.mark.integration
async def test_list_tools() -> None:
    """``list_tools`` must include click_with_healing AND ≥1 upstream tool."""
    _skip_if_no_cua_driver()

    async for session in _spawn_proxy_session():
        listing = await session.list_tools()
        names = {t.name for t in listing.tools}
        assert "click_with_healing" in names, (
            f"click_with_healing missing from proxy listing; got {sorted(names)}"
        )
        # At least one upstream tool name must appear (the proxy mirrors them all).
        # The exact set depends on the cua-driver build; we assert ≥ 1 non-healing
        # tool exists.
        upstream_names = names - {"click_with_healing"}
        assert len(upstream_names) >= 1, (
            f"no upstream tools mirrored; got only {sorted(names)}"
        )


# --------------------------------------------------------------------------- Test 2


@pytest.mark.integration
async def test_screenshot_passthrough() -> None:
    """A non-action tool (screenshot or list_apps) must passthrough cleanly.

    cua-driver exposes a screenshot tool; we call it via the proxy and assert
    the returned content is non-empty. If the build under test doesn't expose
    one, we fall back to ``list_apps`` (always present per ToolRegistry.swift).
    """
    _skip_if_no_cua_driver()

    async for session in _spawn_proxy_session():
        listing = await session.list_tools()
        names = {t.name for t in listing.tools}

        # Prefer a screenshot tool if one exists; otherwise list_apps.
        screenshot_candidates = [n for n in names if "screenshot" in n.lower()]
        if screenshot_candidates:
            tool_name = screenshot_candidates[0]
        elif "list_apps" in names:
            tool_name = "list_apps"
        else:
            pytest.skip(
                f"no passthrough-friendly tool found in upstream; got {sorted(names)}"
            )

        result = await session.call_tool(tool_name, arguments={})
        assert result is not None, f"{tool_name} returned None"
        # CallToolResult.content is a list of content items; assert at least
        # one item exists OR isError is False (some tools return empty content
        # on success).
        content = getattr(result, "content", None)
        is_error = getattr(result, "isError", False)
        assert (content is not None and len(content) > 0) or not is_error, (
            f"{tool_name} returned empty content AND isError; "
            f"content={content!r} isError={is_error!r}"
        )


# --------------------------------------------------------------------------- Test 3


def _resolve_calculator_5_button(pid: int) -> Optional[tuple[int, int]]:
    """Resolve Calculator's "5" button screen-coordinate centre.

    Uses a depth-limited AX walker. Returns None if the button can't be found
    within a reasonable budget (e.g. window not yet drawn).
    """
    try:
        from cua_overlay.ax.walker import walk_subtree  # noqa: F401
        from HIServices import AXUIElementCreateApplication  # type: ignore[import-not-found]
    except ImportError:
        return None

    # Build the AX root for Calculator.
    app_ref = AXUIElementCreateApplication(pid)
    # Run walk_subtree synchronously via asyncio.
    from cua_overlay.ax.walker import walk_subtree as _walk

    async def _do_walk() -> Optional[tuple[int, int]]:
        result = await _walk(app_ref)
        for node in result.nodes:
            if (
                getattr(node, "role", None) == "AXButton"
                and getattr(node, "label", "") == "5"
            ):
                cx = node.bbox.x + node.bbox.w / 2
                cy = node.bbox.y + node.bbox.h / 2
                return (int(cx), int(cy))
        return None

    try:
        return asyncio.run(_do_walk())
    except Exception:  # noqa: BLE001 — best-effort
        return None


@pytest.mark.integration
async def test_healing_tool_callable(
    cua_driver_available: str, calculator_pid: int
) -> None:
    """``click_with_healing`` must be callable; returns dict with phase=1 + session_id.

    The ``cua_driver_available`` fixture is listed FIRST so pytest evaluates it
    before ``calculator_pid``; without cua-driver the test skips cleanly rather
    than erroring out trying to launch Calculator.
    """
    # Resolve the "5" button center. If we can't find it within a few seconds,
    # use a best-effort default coordinate — the test asserts the wrapper
    # CONTRACT (return shape), not that the click physically registered.
    coords: Optional[tuple[int, int]] = None
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and coords is None:
        coords = _resolve_calculator_5_button(calculator_pid)
        if coords is None:
            await asyncio.sleep(0.3)

    if coords is None:
        # Fallback: use the centre of the screen so the call still goes
        # through. The wrapper-contract assertions don't depend on the click
        # actually mutating Calculator.
        coords = (400, 400)

    cx, cy = coords

    async for session in _spawn_proxy_session():
        result = await session.call_tool(
            "click_with_healing",
            arguments={
                "x": cx,
                "y": cy,
                "bundle_id": "com.apple.calculator",
                "pid": int(calculator_pid),
                "label": "5",
            },
        )

        # CallToolResult.structuredContent (or .content[0].text JSON) carries
        # our return dict. Newer mcp clients populate structuredContent; older
        # ones return the dict serialised inside a TextContent.
        structured = getattr(result, "structuredContent", None)
        if structured is None:
            content = getattr(result, "content", []) or []
            assert content, "click_with_healing returned no content"
            text = getattr(content[0], "text", None)
            assert text is not None, f"unexpected content shape: {content!r}"
            structured = json.loads(text)

        assert structured.get("phase") == 1, (
            f"phase != 1; got {structured!r}"
        )
        session_id = structured.get("session_id")
        assert isinstance(session_id, str) and len(session_id) >= 8, (
            f"session_id missing or too short: {session_id!r}"
        )


# --------------------------------------------------------------------------- Test 4


@pytest.mark.integration
async def test_action_log_written(
    cua_driver_available: str, calculator_pid: int
) -> None:
    """After a click_with_healing call, the action_log.ndjson must have ≥1 valid JSON line.

    The action_log lines come from the WRAPPED upstream ``click`` tool (the
    healing tool delegates to it; the proxy's register_proxied_tool wrap
    appends the line). We trigger the chain via click_with_healing and assert
    the resulting NDJSON file is shaped correctly.

    ``cua_driver_available`` is requested first so pytest evaluates it before
    ``calculator_pid`` and the test skips cleanly when the driver is missing.
    """
    async for session in _spawn_proxy_session():
        result = await session.call_tool(
            "click_with_healing",
            arguments={
                "x": 400,
                "y": 400,
                "bundle_id": "com.apple.calculator",
                "pid": int(calculator_pid),
                "label": "5",
            },
        )
        structured = getattr(result, "structuredContent", None)
        if structured is None:
            content = getattr(result, "content", []) or []
            assert content, "click_with_healing returned no content"
            text = getattr(content[0], "text", None)
            assert text is not None
            structured = json.loads(text)

        session_id = structured["session_id"]

    # Allow filesystem flush before reading the NDJSON.
    await asyncio.sleep(0.2)

    log_path = Path.home() / ".cua" / "sessions" / session_id / "action_log.ndjson"
    assert log_path.exists(), f"action_log.ndjson missing at {log_path}"

    lines = [ln for ln in log_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1, f"action_log.ndjson empty at {log_path}"

    # At least one line must parse as JSON AND carry tool=click + action_type=click.
    found_click = False
    for ln in lines:
        try:
            event = json.loads(ln)
        except json.JSONDecodeError as exc:
            pytest.fail(f"invalid NDJSON line {ln!r}: {exc}")
        if event.get("tool") == "click" and event.get("action_type") == "click":
            found_click = True
            break
    assert found_click, (
        f"no click event found in action_log.ndjson; lines={lines!r}"
    )


# --------------------------------------------------------------------------- helper run


def _run_subprocess_smoke() -> None:
    """Manual smoke-test helper — launches the proxy and lists tools.

    Not invoked by pytest. Provided so ``python -m cua_overlay.mcp_server``
    can be exercised by hand alongside this file::

        python -c "from tests.integration.test_mcp_proxy import _run_subprocess_smoke; _run_subprocess_smoke()"
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "cua_overlay.mcp_server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(2.0)
    proc.terminate()
    proc.wait(timeout=5.0)
