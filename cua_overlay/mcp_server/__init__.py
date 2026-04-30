"""Python MCP server that PROXIES trycua's ``cua-driver mcp`` and adds healing tools.

Per CORE-02 + MCP-01 + MCP-02:

* CORE-02 — Hook into trycua's ToolRegistry post-action callbacks via the MCP
  proxy approach (PRE-subscribe + POST-aggregate) without editing Swift.
* MCP-01 — Maintain trycua's existing MCP server surface (passthrough + wrap
  depending on whether the tool is action-class or not).
* MCP-02 — Expose self-healing wrapper as MCP tools (Phase 1: ``click_with_healing``
  ships as a thin wrapper; Phase 3 swaps the body for 5-branch parallel recovery).

Layout::

    cua_overlay/mcp_server/
    ├── __init__.py            # this file — public re-exports
    ├── main.py                # bootstrap (FastMCP + spawn cua-driver mcp + wire deps)
    ├── proxy.py               # ACTION_CLASS_TOOLS + register_proxied_tool wrapper
    ├── healing_tools.py       # click_with_healing (Phase 1)
    └── __main__.py            # entry point: ``python -m cua_overlay.mcp_server``

Threat model
------------
T-1-01 (LOW, Spoofing): the MCP server tool-call surface. Mitigated by binding
``stdio`` ONLY (never TCP) — only locally-running clients (Claude Code, Cursor,
Codex) that spawned the proxy can connect.
"""
from __future__ import annotations

from cua_overlay.mcp_server.main import ProxyDeps, main

__all__ = ["main", "ProxyDeps"]
