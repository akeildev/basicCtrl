# STUB: replaced by Plan 01-03 on merge
"""AXUIElementWrapper — Wave-2 stub.

This is a Wave-2 import-compatibility stub. Plan 01-03 owns the real
implementation (see plan 01-03 Task 3). The orchestrator will overwrite this
file with Plan 01-03's full implementation via ``-X theirs`` strategy on merge.

Plan 01-04 imports nothing from this module at runtime; it exists for symbol
parity so a future ``from cua_overlay.ax.element import AXElement`` lands.
"""
from __future__ import annotations

from typing import Any

from cua_overlay.ax.rate_limit import TokenBucket


class AXUIElementWrapper:
    """Stub AXUIElementWrapper. Real impl in Plan 01-03."""

    def __init__(
        self,
        ax_element: Any,
        pid: int,
        bundle_id: str,
        bucket: TokenBucket,
    ) -> None:
        self._elem = ax_element
        self.pid = pid
        self.bundle_id = bundle_id
        self._bucket = bucket

    async def read_attribute(self, attribute: str) -> Any:
        """Stub. Real impl in Plan 01-03."""
        raise NotImplementedError("Plan 01-03 owns AXUIElementWrapper.read_attribute")


# Plan 01-03's real module also exports AXElement under the same name; we mirror
# the alias here so any caller using either name is satisfied.
AXElement = AXUIElementWrapper
