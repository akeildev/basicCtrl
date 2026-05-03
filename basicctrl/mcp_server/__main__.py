"""Entry point — ``python -m cua_overlay.mcp_server`` or ``uv run python -m cua_overlay.mcp_server``.

Per Plan 01-08 Task 1 step 3: a thin ``asyncio.run(main())`` shim. All bootstrap
logic lives in ``cua_overlay.mcp_server.main.main`` so it can be unit-tested
without spawning a subprocess.
"""
from __future__ import annotations

import asyncio

from cua_overlay.mcp_server.main import main

if __name__ == "__main__":
    asyncio.run(main())
