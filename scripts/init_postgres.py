"""One-time provisioning helper — runs ``DurableExecutor.setup()``.

Called by ``scripts/init_postgres.sh`` after ``createdb cua_maximalist``.
"""
from __future__ import annotations

import asyncio
import sys

from cua_overlay.persist.durable_step import DurableExecutor


async def main() -> None:
    durable = DurableExecutor()
    try:
        await durable.setup()
        print("Postgres tables provisioned for cua_maximalist.")
    finally:
        await durable.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # pragma: no cover — surface clean exit code
        print(f"init_postgres.py failed: {exc}", file=sys.stderr)
        sys.exit(1)
