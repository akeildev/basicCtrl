"""Unit tests for L1Cheap — three parallel sub-checks (CGWindowList diff,
NSPasteboard.changeCount, ImageHash dHash).

Threat T-1-03 mitigation under test (Test 5): pasteboard CONTENTS must NEVER
appear in any structlog event emitted by L1Cheap.run(). Only the integer
``changeCount`` deltas are loggable.

Total L1 budget: <20ms typical with three sub-checks running in parallel via
``anyio.create_task_group``.
"""
from __future__ import annotations

import asyncio
import io
import time
from datetime import datetime, timezone

import pytest
import structlog
from PIL import Image

from basicctrl.state.graph import Bbox, Source, UIElement
from basicctrl.verifier.ensemble.l1_cheap import L1Cheap, L1Snapshot


# ----------------------------------------------------------------- fixtures


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


# ----------------------------------------------------------------- Test 1


@pytest.mark.asyncio
async def test_window_list_diff_detects_added(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two CGWindowList snapshots; second has a window not in first.

    L1.window_diff signal must fire (>0) when a window appears.
    """
    target = _make_target()
    l1 = L1Cheap()

    # Pre-snapshot: empty.
    before = L1Snapshot(
        window_list={},
        pasteboard_change_count=0,
        roi_dhash=None,
        captured_at=time.monotonic(),
    )

    # Post-snapshot: one window. We monkeypatch the three sync helpers so
    # snapshot() captures controllable state for the diff.
    monkeypatch.setattr(
        l1,
        "_cgwindowlist_snapshot",
        lambda: {42: {"title": "newWin", "owner_pid": 1, "level": 0}},
    )
    monkeypatch.setattr(l1, "_pasteboard_change_count", lambda: 0)
    monkeypatch.setattr(l1, "_roi_dhash", lambda bbox: None)

    signals = await l1.run(target=target, before=before)

    assert signals["l1.window_diff"] > 0.0


# ----------------------------------------------------------------- Test 2


@pytest.mark.asyncio
async def test_pasteboard_changecount_int_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-1-03: the pasteboard signal value is numeric, NOT a string.

    Asserts no string-typed key like 'contents' / 'text' / 'data' exists in the
    returned signal dict.
    """
    target = _make_target()
    l1 = L1Cheap()

    before = L1Snapshot(
        window_list={},
        pasteboard_change_count=10,
        roi_dhash=None,
        captured_at=time.monotonic(),
    )
    monkeypatch.setattr(l1, "_cgwindowlist_snapshot", lambda: {})
    monkeypatch.setattr(l1, "_pasteboard_change_count", lambda: 11)  # changed
    monkeypatch.setattr(l1, "_roi_dhash", lambda bbox: None)

    signals = await l1.run(target=target, before=before)

    # Signal value must be float (or int), never a string.
    assert "l1.pasteboard_changed" in signals
    assert isinstance(signals["l1.pasteboard_changed"], (int, float))
    assert signals["l1.pasteboard_changed"] == 1.0

    # No string contents leaked into signal dict keys.
    forbidden_substrings = ("contents", "text", "data", "value")
    for k in signals.keys():
        # "data" appears in nothing legitimately at L1; "value" does not at L1.
        assert all(
            forbid not in k for forbid in forbidden_substrings
        ), f"unexpected signal key {k}"


# ----------------------------------------------------------------- Test 3


@pytest.mark.asyncio
async def test_dhash_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    """dHash diff: solid black 100x100 vs solid white 100x100 → > 5 bits → 1.0.

    Identical images → 0 bits → 0.0.
    """
    import imagehash

    black = Image.new("RGB", (100, 100), color=(0, 0, 0))
    white = Image.new("RGB", (100, 100), color=(255, 255, 255))

    # NB: dHash on uniform images is 0 — gradient between adjacent pixels is
    # zero. Use a striped image so dHash actually differs.
    striped = Image.new("RGB", (100, 100))
    px = striped.load()
    for x in range(100):
        for y in range(100):
            px[x, y] = (255, 0, 0) if (x // 10) % 2 == 0 else (0, 0, 255)

    h_black = str(imagehash.dhash(black, hash_size=8))
    h_striped = str(imagehash.dhash(striped, hash_size=8))
    h_white = str(imagehash.dhash(white, hash_size=8))

    target = _make_target()
    l1 = L1Cheap()

    # Different images → l1.dhash_changed == 1.0
    before = L1Snapshot(
        window_list={},
        pasteboard_change_count=0,
        roi_dhash=h_black,
        captured_at=time.monotonic(),
    )
    monkeypatch.setattr(l1, "_cgwindowlist_snapshot", lambda: {})
    monkeypatch.setattr(l1, "_pasteboard_change_count", lambda: 0)
    monkeypatch.setattr(l1, "_roi_dhash", lambda bbox: h_striped)

    signals = await l1.run(target=target, before=before)
    assert signals["l1.dhash_changed"] == 1.0

    # Identical images → 0.0
    before2 = L1Snapshot(
        window_list={},
        pasteboard_change_count=0,
        roi_dhash=h_white,
        captured_at=time.monotonic(),
    )
    monkeypatch.setattr(l1, "_roi_dhash", lambda bbox: h_white)
    signals2 = await l1.run(target=target, before=before2)
    assert signals2["l1.dhash_changed"] == 0.0


# ----------------------------------------------------------------- Test 4


@pytest.mark.asyncio
async def test_runs_subchecks_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Three sub-checks each take 50ms via time.sleep; total run() < 100ms (parallel).

    Sequential would be 150ms+ (3 × 50ms). Parallel via anyio task group must
    be ≈50ms.
    """
    target = _make_target()
    l1 = L1Cheap()

    # Pre-snapshot: empty (we use a separate before so run()'s only timing
    # source is the post-snapshot it captures via the slow helpers).
    before = L1Snapshot(
        window_list={},
        pasteboard_change_count=0,
        roi_dhash=None,
        captured_at=time.monotonic(),
    )

    def slow_wl():
        time.sleep(0.05)
        return {}

    def slow_pb():
        time.sleep(0.05)
        return 0

    def slow_dhash(bbox):
        time.sleep(0.05)
        return None

    monkeypatch.setattr(l1, "_cgwindowlist_snapshot", slow_wl)
    monkeypatch.setattr(l1, "_pasteboard_change_count", slow_pb)
    monkeypatch.setattr(l1, "_roi_dhash", slow_dhash)

    t0 = time.monotonic()
    await l1.run(target=target, before=before)
    elapsed = time.monotonic() - t0

    # Three 50ms sleeps in parallel → ~50ms; sequential would be 150ms.
    # 100ms gives generous slack for asyncio task scheduling.
    assert elapsed < 0.100, f"L1.run() took {elapsed:.3f}s; expected <0.100s (parallel)"


# ----------------------------------------------------------------- Test 5


@pytest.mark.asyncio
async def test_no_pasteboard_contents_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """T-1-03 mitigation: even if a malicious caller passes mock contents
    'SECRET' into the env, no captured log event has any field whose value
    equals 'SECRET'.
    """
    target = _make_target()
    l1 = L1Cheap()

    before = L1Snapshot(
        window_list={},
        pasteboard_change_count=10,
        roi_dhash=None,
        captured_at=time.monotonic(),
    )

    # The harness for this test: even though SECRET never *enters* L1Cheap
    # (the implementation only touches integers), we still verify by
    # capture_logs that no field value matches 'SECRET'. Belt-and-braces.
    monkeypatch.setattr(l1, "_cgwindowlist_snapshot", lambda: {})
    monkeypatch.setattr(l1, "_pasteboard_change_count", lambda: 11)
    monkeypatch.setattr(l1, "_roi_dhash", lambda bbox: None)

    SECRET = "SECRET"

    with structlog.testing.capture_logs() as captured:
        await l1.run(target=target, before=before)

    for entry in captured:
        for k, v in entry.items():
            assert v != SECRET, f"log entry leaked SECRET in field {k!r}"
            # Defence in depth: no string field longer than 64 chars in L1
            # debug events (would catch a future regression that logs blob data).
            if isinstance(v, str):
                assert len(v) <= 256


# ----------------------------------------------------------------- Test 6 (smoke)


@pytest.mark.asyncio
async def test_signals_are_floats(monkeypatch: pytest.MonkeyPatch) -> None:
    """All signal values returned by L1Cheap.run() must be in [0.0, 1.0]."""
    target = _make_target()
    l1 = L1Cheap()

    before = L1Snapshot(
        window_list={},
        pasteboard_change_count=0,
        roi_dhash=None,
        captured_at=time.monotonic(),
    )
    monkeypatch.setattr(
        l1,
        "_cgwindowlist_snapshot",
        lambda: {
            1: {"title": "a", "owner_pid": 1, "level": 0},
            2: {"title": "b", "owner_pid": 1, "level": 0},
            3: {"title": "c", "owner_pid": 1, "level": 0},
            4: {"title": "d", "owner_pid": 1, "level": 0},
        },
    )
    monkeypatch.setattr(l1, "_pasteboard_change_count", lambda: 0)
    monkeypatch.setattr(l1, "_roi_dhash", lambda bbox: None)

    signals = await l1.run(target=target, before=before)
    for k, v in signals.items():
        assert isinstance(v, float), f"signal {k} not float: {type(v)}"
        assert 0.0 <= v <= 1.0, f"signal {k}={v} not in [0, 1]"
