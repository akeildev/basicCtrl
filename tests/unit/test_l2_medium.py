"""Unit tests for L2Medium — Vision OCR ROI + depth-limited AX subtree.

Per VERIFY-06: L2 medium tier wraps Vision OCR (ocrmac) for ROI text diff
and depth-limited AX subtree (3 levels MAX, 50 children, 500 nodes via
Plan 03's walk_subtree). NEVER full recursive (Pitfall P3).

Per Phase 1 invariant: L2 should NOT fire for the Calculator demo —
L0+L1 alone produce confidence >= 0.50. These tests prove the L2 surface
is wired correctly so Plan 06 Task 3's escalation logic can drive it.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import time
from datetime import datetime, timezone
from typing import Any
from unittest.mock import patch

import pytest

from cua_overlay.ax.walker import WalkResult
from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.verifier.ensemble.l2_medium import L2Medium, L2Snapshot


# ----------------------------------------------------------------- helpers


def _make_target() -> UIElement:
    now = datetime.now(timezone.utc)
    return UIElement(
        role="AXButton",
        role_path="AXApplication/AXWindow/AXButton[5]",
        label="5",
        bbox=Bbox(x=100.0, y=200.0, w=40.0, h=40.0),
        source=[Source.AX],
        discovered_at=now,
        last_seen_at=now,
        pid=999,
        bundle_id="com.apple.Calculator",
        window_id=1,
    )


def _make_walk_result(
    *, nodes: int = 5, truncated: bool = False, cap_hit: str | None = None
) -> WalkResult:
    """Build a fake WalkResult with N synthetic UIElements."""
    now = datetime.now(timezone.utc)
    elems = [
        UIElement(
            role="AXGenericElement",
            role_path=f"AXApplication/Child[{i}]",
            label=f"node-{i}",
            bbox=Bbox(x=0.0, y=0.0, w=10.0, h=10.0),
            source=[Source.AX],
            discovered_at=now,
            last_seen_at=now,
            pid=999,
            bundle_id="com.apple.Calculator",
            window_id=1,
        )
        for i in range(nodes)
    ]
    return WalkResult(
        nodes=elems, truncated=truncated, cap_hit=cap_hit, duration_ms=42.0
    )


# ----------------------------------------------------------------- Test 1


def test_walk_uses_max_depth_3_default() -> None:
    """L2Medium source must call walk_subtree without overriding max_depth>3.

    The walker's default max_depth is 3 (per Plan 03). L2 reuses the default
    so the Pitfall P3 hard rule (never full recursive) is delegated.
    """
    src = inspect.getsource(L2Medium)
    assert "walk_subtree(" in src, "L2Medium must call walk_subtree (Plan 03 reuse)"
    # Forbid explicit max_depth >= 4 anywhere in the module body.
    bad = re.search(r"max_depth\s*=\s*([4-9]|\d{2,})", src)
    assert bad is None, f"max_depth override above 3 found: {bad.group(0)}"


# ----------------------------------------------------------------- Test 2


def test_no_full_recursion() -> None:
    """L2Medium must NOT call AXUIElementCopyAttributeValue directly.

    Walker delegation only — raw AX recursion is forbidden.
    """
    import cua_overlay.verifier.ensemble.l2_medium as l2_module
    src = inspect.getsource(l2_module)
    assert "AXUIElementCopyAttributeValue" not in src, (
        "L2Medium must delegate to walker, never raw AX recursion"
    )
    # Also no recursion through AXUIElementCopyAttributeValues plural.
    assert "AXUIElementCopyAttributeValues" not in src


# ----------------------------------------------------------------- Test 3


@pytest.mark.asyncio
async def test_run_executes_subchecks_in_parallel() -> None:
    """OCR + walker run via anyio task group; total elapsed <100ms.

    With OCR and walker each sleeping 60ms, sequential would be 120ms+;
    parallel should be ~60ms. 100ms gives slack for scheduler jitter.
    """
    target = _make_target()
    l2 = L2Medium()

    async def slow_ocr(bbox: Any) -> str:
        await asyncio.sleep(0.060)
        return "Result: 5"

    async def slow_walk(*args: Any, **kwargs: Any) -> WalkResult:
        await asyncio.sleep(0.060)
        return _make_walk_result(nodes=10)

    with (
        patch.object(l2, "_capture_ocr", side_effect=slow_ocr),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=slow_walk),
    ):
        before = await l2.snapshot(target, ax_element=object())

    # snapshot is the parallel boundary. Verify parallel.
    # Re-do the timing test with run() since it does snapshot().
    with (
        patch.object(l2, "_capture_ocr", side_effect=slow_ocr),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=slow_walk),
    ):
        t0 = time.monotonic()
        await l2.snapshot(target, ax_element=object())
        elapsed = time.monotonic() - t0

    assert elapsed < 0.100, f"snapshot() took {elapsed:.3f}s; expected <0.100s parallel"


# ----------------------------------------------------------------- Test 4


@pytest.mark.asyncio
async def test_truncated_signal_emitted_on_walker_truncation() -> None:
    """When walker hits a cap (truncated=True), L2 emits l2.walker_truncated=1.0."""
    target = _make_target()
    l2 = L2Medium()

    async def fake_ocr(bbox: Any) -> str:
        return "Calculator"

    async def fake_walk_truncated(*args: Any, **kwargs: Any) -> WalkResult:
        return _make_walk_result(nodes=500, truncated=True, cap_hit="depth")

    with (
        patch.object(l2, "_capture_ocr", side_effect=fake_ocr),
        patch(
            "cua_overlay.verifier.ensemble.l2_medium.walk_subtree",
            side_effect=fake_walk_truncated,
        ),
    ):
        before = await l2.snapshot(target, ax_element=object())
        signals = await l2.run(target, ax_element=object(), before=before)

    assert signals["l2.walker_truncated"] == 1.0


# ----------------------------------------------------------------- Test 5


@pytest.mark.asyncio
async def test_ocr_text_change_signal() -> None:
    """OCR text differs pre/post → l2.ocr_text_changed == 1.0; same → 0.0."""
    target = _make_target()
    l2 = L2Medium()

    # Walker returns same result both times — only OCR differs.
    async def stable_walk(*args: Any, **kwargs: Any) -> WalkResult:
        return _make_walk_result(nodes=5)

    # Case A: text changes — pre "0", post "5"
    ocr_values = iter(["0", "5"])

    async def changing_ocr(bbox: Any) -> str:
        return next(ocr_values)

    with (
        patch.object(l2, "_capture_ocr", side_effect=changing_ocr),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=stable_walk),
    ):
        before = await l2.snapshot(target, ax_element=object())
        signals_a = await l2.run(target, ax_element=object(), before=before)

    assert signals_a["l2.ocr_text_changed"] == 1.0

    # Case B: text same both times.
    async def stable_ocr(bbox: Any) -> str:
        return "Result: 5"

    with (
        patch.object(l2, "_capture_ocr", side_effect=stable_ocr),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=stable_walk),
    ):
        before = await l2.snapshot(target, ax_element=object())
        signals_b = await l2.run(target, ax_element=object(), before=before)

    assert signals_b["l2.ocr_text_changed"] == 0.0


# ----------------------------------------------------------------- Test 6


@pytest.mark.asyncio
async def test_expected_text_match_signal() -> None:
    """expected_text="5" + post OCR contains "5" → l2.expected_text_present=1.0."""
    target = _make_target()
    l2 = L2Medium()

    async def stable_walk(*args: Any, **kwargs: Any) -> WalkResult:
        return _make_walk_result(nodes=5)

    # Case A: expected text IS present in post-OCR.
    async def ocr_with_target(bbox: Any) -> str:
        return "Result: 5"

    with (
        patch.object(l2, "_capture_ocr", side_effect=ocr_with_target),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=stable_walk),
    ):
        before = await l2.snapshot(target, ax_element=object())
        signals_a = await l2.run(
            target, ax_element=object(), before=before, expected_text="5"
        )

    assert signals_a["l2.expected_text_present"] == 1.0

    # Case B: expected text NOT in post-OCR.
    async def ocr_missing_target(bbox: Any) -> str:
        return "Calculator"

    with (
        patch.object(l2, "_capture_ocr", side_effect=ocr_missing_target),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=stable_walk),
    ):
        before = await l2.snapshot(target, ax_element=object())
        signals_b = await l2.run(
            target, ax_element=object(), before=before, expected_text="5"
        )

    assert signals_b["l2.expected_text_present"] == 0.0


# ----------------------------------------------------------------- Test 7 (extra: signal types)


@pytest.mark.asyncio
async def test_run_returns_float_signals() -> None:
    """All signals returned by L2Medium.run() must be floats in [0.0, 1.0]."""
    target = _make_target()
    l2 = L2Medium()

    async def fake_ocr(bbox: Any) -> str:
        return "ok"

    async def fake_walk(*args: Any, **kwargs: Any) -> WalkResult:
        return _make_walk_result(nodes=5)

    with (
        patch.object(l2, "_capture_ocr", side_effect=fake_ocr),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=fake_walk),
    ):
        before = await l2.snapshot(target, ax_element=object())
        signals = await l2.run(target, ax_element=object(), before=before)

    for k, v in signals.items():
        assert isinstance(v, float), f"signal {k} is not float: {type(v)}"
        assert 0.0 <= v <= 1.0, f"signal {k}={v} out of [0.0, 1.0]"


# ----------------------------------------------------------------- Test 8 (snapshot dataclass)


@pytest.mark.asyncio
async def test_snapshot_returns_l2snapshot_with_fields() -> None:
    """L2Snapshot is a dataclass with ocr_text, walker_nodes, walker_truncated."""
    target = _make_target()
    l2 = L2Medium()

    async def fake_ocr(bbox: Any) -> str:
        return "abc"

    async def fake_walk(*args: Any, **kwargs: Any) -> WalkResult:
        return _make_walk_result(nodes=7, truncated=True, cap_hit="children")

    with (
        patch.object(l2, "_capture_ocr", side_effect=fake_ocr),
        patch("cua_overlay.verifier.ensemble.l2_medium.walk_subtree", side_effect=fake_walk),
    ):
        snap = await l2.snapshot(target, ax_element=object())

    assert isinstance(snap, L2Snapshot)
    assert snap.ocr_text == "abc"
    assert snap.walker_nodes == 7
    assert snap.walker_truncated is True
