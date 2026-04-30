"""Bootstrap — FastMCP proxy that spawns ``cua-driver mcp`` and adds healing tools.

Lifecycle (per Plan 01-08 Task 1):

1. ``configure_logging()`` — install structlog NDJSON pipeline.
2. ``AXEventBridge`` + ``AXObserverManager`` — start the CFRunLoop thread + dispatcher.
3. ``NSWorkspaceObserver`` + ``KqueueProcObserver`` — start auxiliary push observers.
4. Build verifier ensemble: ``L0Push`` + ``L1Cheap`` + ``L2Medium`` + ``L3Stub`` +
   ``WeightedVote`` + ``Aggregator``.
5. ``SessionWriter`` (per-session ``~/.cua/sessions/<uuid>/``) +
   ``DurableExecutor`` (Postgres-backed; setup() failures degrade gracefully —
   Plan 07's ``init_postgres.sh`` is the recovery path).
6. Spawn ``cua-driver mcp`` as a stdio subprocess via ``mcp.client.stdio.stdio_client``.
7. ``await upstream.list_tools()`` and mirror every tool into the proxy via
   ``register_proxied_tool`` (action-class tools get the PRE/FIRE/POST wrap;
   non-action tools are passthrough).
8. Register healing tools via ``register_healing_tools``.
9. ``await proxy_server.run_stdio_async()`` blocks until the host disconnects.

T-1-01 mitigation: only ``run_stdio_async()`` is invoked. Never ``socket``,
never ``listen``, never ``bind``. Acceptance criteria asserts the source
contains zero TCP markers.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import structlog
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp import FastMCP

from cua_overlay.ax.observer import AXEventBridge
from cua_overlay.log import configure as configure_logging
from cua_overlay.persist import DurableExecutor, SessionWriter
from cua_overlay.verifier import (
    Aggregator,
    AXObserverManager,
    KqueueProcObserver,
    L0Push,
    L1Cheap,
    L2Medium,
    L3Stub,
    NSWorkspaceObserver,
    WeightedVote,
)


@dataclass
class ProxyDeps:
    """Bag of shared dependencies threaded through every proxied tool call.

    Built once in ``main()`` and passed to ``register_proxied_tool`` /
    ``register_healing_tools``. Each registered tool closes over this so it has
    O(1) access to the AX manager, verifier aggregator, session writer, and
    durable executor without globals.
    """

    axmgr: AXObserverManager
    aggregator: Aggregator
    session: SessionWriter
    durable: DurableExecutor


async def main() -> None:
    """Bootstrap the proxy. Blocks on ``run_stdio_async`` until the host disconnects.

    Stages:
        1. Logging.
        2. AX bridge + manager + auxiliary push observers.
        3. Verifier ensemble (L0+L1+L2+L3Stub + WeightedVote + Aggregator).
        4. Persistence (SessionWriter + DurableExecutor).
        5. Upstream cua-driver subprocess spawn + tool list + mirror.
        6. Register healing tools.
        7. ``await proxy_server.run_stdio_async()``.

    Cleanup is in ``finally``: stop AX manager, stop bridge, stop NSWorkspace,
    aclose DurableExecutor. KqueueProcObserver is owned by an ``async with`` so
    its __aexit__ handles cleanup deterministically.

    Raises:
        FileNotFoundError: if the ``cua-driver`` binary is not on PATH and
            ``CUA_DRIVER_BIN`` is not set. Logged with a build hint and re-raised
            so callers can act on it.
    """
    # 1. Logging.
    configure_logging()
    log = structlog.get_logger()

    # 2. AX bridge + manager. The bridge spawns a CFRunLoop thread; the manager
    # spawns an asyncio dispatcher task that drains bridge.queue → waiters.
    import asyncio

    loop = asyncio.get_running_loop()
    bridge = AXEventBridge(loop=loop)
    bridge.start()
    axmgr = AXObserverManager(bridge=bridge)
    axmgr.start()

    # 3. Auxiliary push observers (NSWorkspace frontmost-app + kqueue NOTE_EXIT).
    ws = NSWorkspaceObserver(loop=loop)
    ws.start()

    # KqueueProcObserver is an async context manager so we must hold it open for
    # the lifetime of the proxy. Use try/finally for explicit teardown rather
    # than nesting the entire main body inside another `async with`.
    kq = KqueueProcObserver(loop=loop)
    await kq.__aenter__()

    # Hold the upstream stdio_client + ClientSession context managers so they
    # stay open for the lifetime of run_stdio_async. We enter them inside the
    # outer try so the matching __aexit__ in the finally block can release the
    # subprocess + session even on early failure.
    upstream_stdio_cm: Any = None
    upstream_session_cm: Any = None
    durable: DurableExecutor | None = None

    try:
        # 4. Verifier ensemble.
        l0 = L0Push(axmgr=axmgr, ws=ws, kq=kq)
        l1 = L1Cheap()
        l2 = L2Medium()
        l3 = L3Stub()
        vote = WeightedVote()
        aggregator = Aggregator(l0=l0, l1=l1, l2=l2, l3=l3, vote=vote)

        # 5. Persistence — SessionWriter is local-only, DurableExecutor is
        # Postgres-backed. If Postgres is not running, log a warning and
        # continue; checkpoint() calls will then raise but the proxy still
        # serves reads/passthrough tools.
        session = SessionWriter()
        durable = DurableExecutor()
        try:
            await durable.setup()
        except Exception as exc:  # noqa: BLE001 — Postgres setup failures are
            # never fatal at proxy startup; init_postgres.sh is the recovery
            # path.
            log.warning(
                "durable.setup_failed_continuing_without_postgres",
                error=str(exc),
                hint=(
                    "Run `bash scripts/init_postgres.sh` to provision the LangGraph "
                    "schema. Phase 1 proxy still serves passthrough + read tools "
                    "without the durable checkpoint layer."
                ),
            )

        deps = ProxyDeps(
            axmgr=axmgr,
            aggregator=aggregator,
            session=session,
            durable=durable,
        )

        # 6. Spawn upstream `cua-driver mcp` subprocess. Allow override via
        # CUA_DRIVER_BIN so dev machines that built cua-driver out-of-tree
        # can point at the binary explicitly.
        cua_driver_bin = os.environ.get("CUA_DRIVER_BIN", "cua-driver")
        upstream_params = StdioServerParameters(
            command=cua_driver_bin,
            args=["mcp"],
            env=None,
        )

        # Top-level FastMCP that the host (Claude Code / Cursor / Codex) talks to.
        proxy_server = FastMCP(name="cua-maximalist")

        try:
            upstream_stdio_cm = stdio_client(upstream_params)
            read, write = await upstream_stdio_cm.__aenter__()
            upstream_session_cm = ClientSession(read, write)
            upstream = await upstream_session_cm.__aenter__()
            await upstream.initialize()
            upstream_tools = await upstream.list_tools()
            log.info(
                "upstream.connected",
                tool_count=len(upstream_tools.tools),
                bin=cua_driver_bin,
            )
        except FileNotFoundError as exc:
            log.error(
                "upstream.cua_driver_not_found",
                bin=cua_driver_bin,
                hint=(
                    "Build cua-driver: `cd libs/cua-driver && swift build -c release` "
                    "then add `libs/cua-driver/.build/release` to PATH or set "
                    "CUA_DRIVER_BIN to the absolute binary path."
                ),
                error=str(exc),
            )
            raise

        # 7. Mirror every upstream tool into the proxy. Action-class tools get
        # the PRE-subscribe/FIRE/POST-aggregate wrap; non-action tools are
        # straight passthroughs. Late import to avoid circular dependency
        # between main.py and proxy.py.
        from cua_overlay.mcp_server.proxy import register_proxied_tool

        for tool in upstream_tools.tools:
            await register_proxied_tool(proxy_server, upstream, tool, deps)

        # 8. Register healing tools (Phase 1: click_with_healing only; Phase 3
        # adds the 5-branch recovery variants).
        from cua_overlay.mcp_server.healing_tools import register_healing_tools

        await register_healing_tools(proxy_server, upstream, deps)

        log.info(
            "proxy.ready",
            session_id=session.session_id,
            upstream_tool_count=len(upstream_tools.tools),
        )

        # 9. Block on the proxy's stdio loop until the host disconnects.
        # T-1-01 mitigation: we ONLY use run_stdio_async — never bind a TCP socket.
        await proxy_server.run_stdio_async()
    finally:
        # Teardown order: upstream first (close the subprocess MCP session),
        # then verifier observers, then bridge, then DurableExecutor.
        if upstream_session_cm is not None:
            try:
                await upstream_session_cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001 — teardown best-effort
                pass
        if upstream_stdio_cm is not None:
            try:
                await upstream_stdio_cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        try:
            await axmgr.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            bridge.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            ws.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            await kq.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        if durable is not None:
            try:
                await durable.aclose()
            except Exception:  # noqa: BLE001
                pass
