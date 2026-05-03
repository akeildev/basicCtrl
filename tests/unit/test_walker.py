"""Unit tests for basicctrl.ax.walker.walk_subtree.

Pitfall P3 (full recursive AX walk = 15-20s on Safari) mitigation: walker
hard-caps at depth=3, children=50, total=500 nodes; emits truncated flag +
cap_hit reason. Uses iterative work-queue, never Python recursion.

Tests run against a ``MockAXElement`` so we never touch real macOS AX (those
integrations live in ``tests/integration/``).
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest

from basicctrl.ax import walker as walker_module
from basicctrl.ax.rate_limit import TokenBucket
from basicctrl.ax.walker import WalkResult, walk_subtree


# ---------------------------------------------------------------------------
# Mock AX hierarchy: a Python object that behaves like an AXUIElement for the
# attributes the walker reads. Tests build trees from this.
# ---------------------------------------------------------------------------


class MockAXElement:
    """In-memory stand-in for ``AXUIElement`` with attribute reads + children."""

    def __init__(
        self,
        role: str = "AXButton",
        label: str = "",
        children: list["MockAXElement"] | None = None,
    ) -> None:
        self.role = role
        self.label = label
        self.children = children or []

    def attr(self, name: str) -> Any:
        if name == "AXRole":
            return self.role
        if name == "AXTitle":
            return self.label or None
        if name == "AXLabel":
            return None
        if name == "AXValue":
            return None
        if name == "AXPosition":
            return (0.0, 0.0)
        if name == "AXSize":
            return (10.0, 10.0)
        if name == "AXIdentifier":
            return None
        if name == "AXEnabled":
            return True
        if name == "AXChildren":
            return self.children
        return None


def _build_chain(depth: int) -> MockAXElement:
    """Linear chain of ``depth`` nodes (root at index 0, deepest at depth-1)."""
    if depth <= 0:
        raise ValueError("depth must be >= 1")
    leaf = MockAXElement(role="AXButton", label=f"leaf-{depth - 1}")
    cur = leaf
    for i in range(depth - 2, -1, -1):
        cur = MockAXElement(role="AXGroup", label=f"node-{i}", children=[cur])
    return cur


def _build_balanced(branching: int, depth: int) -> MockAXElement:
    """Balanced tree where each node has ``branching`` children, ``depth`` levels."""
    if depth == 1:
        return MockAXElement(role="AXButton")
    return MockAXElement(
        role="AXGroup",
        children=[_build_balanced(branching, depth - 1) for _ in range(branching)],
    )


def _count_nodes(elem: MockAXElement) -> int:
    return 1 + sum(_count_nodes(c) for c in elem.children)


@pytest.fixture(autouse=True)
def _mock_read_attr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch ``walker._read_attr`` so it pulls from ``MockAXElement.attr()``."""

    async def fake(ax_elem: Any, attribute: str) -> Any:
        if isinstance(ax_elem, MockAXElement):
            return ax_elem.attr(attribute)
        return None

    monkeypatch.setattr(walker_module, "_read_attr", fake)


@pytest.mark.asyncio
async def test_caps_at_max_depth() -> None:
    """A 5-deep chain walked with max_depth=3 returns truncated, cap_hit='depth'."""
    root = _build_chain(depth=5)
    result = await walk_subtree(root, pid=1, bundle_id="test", max_depth=3)
    assert result.truncated is True
    assert result.cap_hit == "depth"
    # Root + 3 descendants = 4 nodes. We never read the 5th (depth=4).
    assert len(result.nodes) == 4


@pytest.mark.asyncio
async def test_caps_at_max_children() -> None:
    """100 children + max_children=50 → 50 enqueued, truncated, cap_hit='children'.

    Uses a high-capacity bucket so this test isolates the children cap from
    rate-limiting (the rate-limit interaction is verified separately in
    ``test_uses_rate_limit``).
    """
    children = [MockAXElement(role="AXButton", label=f"b-{i}") for i in range(100)]
    root = MockAXElement(role="AXGroup", children=children)
    big_bucket = TokenBucket(rate_per_sec=10000.0, capacity=10000)
    result = await walk_subtree(
        root,
        pid=1,
        bundle_id="test",
        max_depth=3,
        max_children=50,
        max_nodes=500,
        bucket=big_bucket,
    )
    assert result.truncated is True
    assert result.cap_hit == "children"
    # Root + 50 children = 51.
    assert len(result.nodes) == 51


@pytest.mark.asyncio
async def test_caps_at_max_nodes() -> None:
    """A balanced tree with >500 reachable nodes hits max_nodes=500.

    Uses a high-capacity bucket so this test isolates the nodes cap from
    rate-limiting.
    """
    # Branching=10, depth=4 → 1 + 10 + 100 + 1000 = 1111 nodes.
    root = _build_balanced(branching=10, depth=4)
    big_bucket = TokenBucket(rate_per_sec=100000.0, capacity=100000)
    result = await walk_subtree(
        root,
        pid=1,
        bundle_id="test",
        max_depth=10,  # high so depth doesn't trip first
        max_children=10,
        max_nodes=500,
        bucket=big_bucket,
    )
    assert result.truncated is True
    assert result.cap_hit == "nodes"
    assert len(result.nodes) <= 500


@pytest.mark.asyncio
async def test_no_truncation_when_under_caps() -> None:
    """A 4-node tree returns truncated=False, cap_hit=None, all 4 nodes."""
    root = _build_balanced(branching=3, depth=2)  # 1 + 3 = 4 nodes
    big_bucket = TokenBucket(rate_per_sec=10000.0, capacity=10000)
    result = await walk_subtree(
        root,
        pid=1,
        bundle_id="test",
        max_depth=3,
        max_children=50,
        max_nodes=500,
        bucket=big_bucket,
    )
    assert result.truncated is False
    assert result.cap_hit is None
    assert len(result.nodes) == _count_nodes(root) == 4


@pytest.mark.asyncio
async def test_emits_uielement_with_role_path() -> None:
    """Children carry a role_path like 'AXApplication/AXGroup[0]/AXButton[1]'."""
    leaf_a = MockAXElement(role="AXButton", label="a")
    leaf_b = MockAXElement(role="AXButton", label="b")
    root = MockAXElement(role="AXGroup", children=[leaf_a, leaf_b])
    big_bucket = TokenBucket(rate_per_sec=10000.0, capacity=10000)
    result = await walk_subtree(
        root,
        pid=1,
        bundle_id="test",
        max_depth=3,
        parent_role_path="AXApplication",
        bucket=big_bucket,
    )
    paths = [n.role_path for n in result.nodes]
    # Root keeps the parent_role_path.
    assert paths[0] == "AXApplication"
    # Children gain "[i]" indices.
    assert "AXApplication/AXGroup[0]" in paths
    assert "AXApplication/AXGroup[1]" in paths


@pytest.mark.asyncio
async def test_default_caps_match_research() -> None:
    """Walker signature defaults are max_depth=3, max_children=50, max_nodes=500."""
    sig = inspect.signature(walk_subtree)
    assert sig.parameters["max_depth"].default == 3
    assert sig.parameters["max_children"].default == 50
    assert sig.parameters["max_nodes"].default == 500


def test_no_recursive_python_call() -> None:
    """Walker is iterative: walk_subtree never calls itself by name."""
    src = inspect.getsource(walk_subtree)
    # The "def walk_subtree" line is allowed; any other "walk_subtree(" inside
    # the body would be recursion.
    body = src.split("def walk_subtree", 1)[1]
    # Skip the signature line up to the first newline so we drop "walk_subtree" from def.
    body_after_sig = body.split("\n", 1)[1] if "\n" in body else body
    assert "walk_subtree(" not in body_after_sig, "walker must be iterative, not recursive"
    assert "while queue" in body_after_sig or "queue.pop" in body_after_sig


@pytest.mark.asyncio
async def test_uses_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Walker calls bucket.acquire for every read; capacity=2 throttles a 5-node tree."""
    root = _build_balanced(branching=2, depth=3)  # 1 + 2 + 4 = 7 nodes

    bucket = TokenBucket(rate_per_sec=2.0, capacity=2)
    # Freeze the clock so refill never hides the cap.
    import basicctrl.ax.rate_limit as rl

    frozen = [9000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: frozen[0])

    call_count = [0]
    real_acquire = bucket.acquire

    async def counting_acquire(pid: int) -> bool:
        call_count[0] += 1
        return await real_acquire(pid)

    monkeypatch.setattr(bucket, "acquire", counting_acquire)

    result = await walk_subtree(
        root,
        pid=1,
        bundle_id="test",
        max_depth=3,
        bucket=bucket,
    )
    # bucket only had 2 tokens; first read consumes 1, second consumes 1, then deny.
    # Walker calls bucket.acquire many times (per-node + per-children) but only
    # the first two grant tokens.
    assert call_count[0] >= 3, f"expected multiple acquire calls, got {call_count[0]}"
    # Only nodes that got a token are recorded: at most 2.
    assert len(result.nodes) <= 2
