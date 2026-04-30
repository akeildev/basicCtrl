"""TRANS-05 — T5 Pixel translator unit tests with mocked T4."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from cua_overlay.state.graph import Bbox, Source, UIElement
from cua_overlay.translators.base import TargetSpec, TranslatorTarget
from cua_overlay.translators.t5_pixel import T5PixelTranslator


def _fake_t4_target() -> TranslatorTarget:
    now = datetime.now(timezone.utc)
    return TranslatorTarget(
        element=UIElement(
            role="AXUnknown",
            role_path="AXVision/yolo[1]",
            label="white pawn",
            bbox=Bbox(x=100, y=200, w=50, h=50),
            pid=1234,
            bundle_id="com.apple.Chess",
            window_id=0,
            discovered_at=now,
            last_seen_at=now,
            source=[Source.PIXEL],
        ),
        grounded_bbox=Bbox(x=100, y=200, w=50, h=50),
    )


def test_tier_is_T5() -> None:
    t = T5PixelTranslator()
    assert t.tier == "T5"


@pytest.mark.asyncio
async def test_resolve_returns_none_when_t4_returns_none() -> None:
    fake_t4 = AsyncMock()
    fake_t4.resolve = AsyncMock(return_value=None)
    t = T5PixelTranslator(t4=fake_t4)
    result = await t.resolve("com.apple.Chess", 1234, TargetSpec(label="x"))
    assert result is None


@pytest.mark.asyncio
async def test_resolve_attaches_pre_phash_when_t4_succeeds() -> None:
    fake_t4 = AsyncMock()
    fake_t4.resolve = AsyncMock(return_value=_fake_t4_target())
    t = T5PixelTranslator(t4=fake_t4)
    with patch.object(t, "_capture_roi_phash", return_value="abc123"):
        result = await t.resolve(
            "com.apple.Chess", 1234, TargetSpec(label="white pawn")
        )
    assert result is not None
    assert result.extras.get("pre_phash") == "abc123"


@pytest.mark.asyncio
async def test_resolve_preserves_t4_grounded_bbox() -> None:
    fake_t4_target_inst = _fake_t4_target()
    fake_t4 = AsyncMock()
    fake_t4.resolve = AsyncMock(return_value=fake_t4_target_inst)
    t = T5PixelTranslator(t4=fake_t4)
    with patch.object(t, "_capture_roi_phash", return_value=None):
        result = await t.resolve(
            "com.apple.Chess", 1234, TargetSpec(label="white pawn")
        )
    assert result.grounded_bbox is not None
    assert result.grounded_bbox.x == 100
    assert result.grounded_bbox.y == 200


@pytest.mark.asyncio
async def test_validate_true_when_grounded_bbox_set() -> None:
    t = T5PixelTranslator()
    target = _fake_t4_target()
    assert await t.validate(target) is True
