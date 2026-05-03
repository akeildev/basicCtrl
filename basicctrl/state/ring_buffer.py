"""STATE-03 — TemporalRingBuffer.

Last 5 frames of state, in-memory. Per ARCHITECTURE.md L491 "snapshot every
60s, prune nodes >5min stale" — the ring buffer is the working set, the
on-disk snapshot is the durable copy.

PRECEDES edges link the same composite_key across consecutive frames. They
have ``src == dst`` because the same logical element is being tracked over
time; the ``timestamp_ns`` field disambiguates which frame.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque

from pydantic import BaseModel, ConfigDict, Field

from basicctrl.state.graph import Edge, EdgeKind, StateGraph, UIElement


class StateSnapshot(BaseModel):
    """An immutable view of a StateGraph at a single instant."""

    model_config = ConfigDict(frozen=True)

    nodes: dict[str, UIElement] = Field(default_factory=dict)
    timestamp_ns: int

    @classmethod
    def from_graph(cls, g: StateGraph) -> "StateSnapshot":
        """Deep-copy every node so later mutations to the live graph don't bleed in."""
        return cls(
            nodes={k: v.model_copy(deep=True) for k, v in g.nodes.items()},
            timestamp_ns=time.monotonic_ns(),
        )


class TemporalRingBuffer:
    """A bounded deque of StateSnapshots plus an emitted PRECEDES edge list."""

    def __init__(self, maxlen: int = 5) -> None:
        self.frames: Deque[StateSnapshot] = deque(maxlen=maxlen)
        self.precedes_edges: list[Edge] = []

    def push(self, snapshot: StateSnapshot) -> None:
        """Append ``snapshot``; if a previous frame exists, emit PRECEDES edges."""
        self.frames.append(snapshot)
        if len(self.frames) >= 2:
            self._link_precedes(self.frames[-2], self.frames[-1])

    def _link_precedes(self, prev: StateSnapshot, curr: StateSnapshot) -> None:
        """Emit one PRECEDES edge per composite_key present in BOTH frames.

        A key that appears for the first time in ``curr`` gets no PRECEDES
        edge — it has no predecessor.
        """
        for key in curr.nodes:
            if key in prev.nodes:
                self.precedes_edges.append(
                    Edge(
                        src=key,
                        dst=key,
                        kind=EdgeKind.PRECEDES,
                        timestamp_ns=curr.timestamp_ns,
                    )
                )
